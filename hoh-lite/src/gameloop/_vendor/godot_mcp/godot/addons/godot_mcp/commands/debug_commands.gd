@tool
extends MCPBaseCommand
class_name MCPDebugCommands

# Keep in sync with LAUNCH_FROZEN_ENV in mcp_game_bridge.gd.
const LAUNCH_FROZEN_ENV := "GODOT_MCP_LAUNCH_FROZEN"
const STOP_TIMEOUT := 5.0
const START_TIMEOUT := 5.0
# Complete authored environments can spend more than 15 seconds loading their
# first runtime scene even after editor import has succeeded.  Keep the launch
# bounded, but do not reap a healthy heavy candidate before it can announce the
# debugger bridge.
const BRIDGE_READY_TIMEOUT := 45.0


func get_commands() -> Dictionary:
	return {
		"run_project": run_project,
		"stop_project": stop_project,
		"get_log_messages": get_log_messages,
		"get_runtime_log_messages": get_runtime_log_messages,
		"get_stack_trace": get_stack_trace,
	}


func run_project(params: Dictionary) -> Dictionary:
	var scene_path: String = params.get("scene_path", "")
	var frozen: bool = params.get("frozen", false)
	var replaced_previous_run := false
	var debugger_plugin = _plugin.get_debugger_plugin() if _plugin else null

	# stop_playing_scene() is asynchronous.  Starting again while the old
	# debugger session is still tearing down can leave EditorInterface claiming
	# the project is playing even though the new game never acquires a usable
	# debugger/bridge session.  Make run idempotently replace the old run and do
	# not launch until teardown is observable.
	if EditorInterface.is_playing_scene():
		replaced_previous_run = true
		EditorInterface.stop_playing_scene()
		if not await _wait_for_play_state(false, STOP_TIMEOUT):
			return _error(
				"STOP_TIMEOUT",
				"The previous game did not stop within %.1f seconds; no replacement was launched. Do not repeat run blindly; inspect the editor/game process first." % STOP_TIMEOUT
			)

	# EditorDebuggerPlugin may keep one session id across several play runs.
	# Reset only the per-run readiness bit: calling has_active_session() while
	# play mode is false would retire that still-valid id and make the next
	# bridge-ready message look stale.
	if debugger_plugin != null:
		debugger_plugin.prepare_for_launch()

	# Launch-frozen: the spawned game inherits the editor's environment, so
	# setting this before play makes the bridge freeze the tree in _ready —
	# before the first process frame. Deterministic, unlike sending a freeze
	# message after the debug session comes up (which races the game's first
	# frames against the agent's latency).
	if frozen:
		OS.set_environment(LAUNCH_FROZEN_ENV, "1")

	if scene_path.is_empty():
		EditorInterface.play_main_scene()
	else:
		EditorInterface.play_custom_scene(scene_path)

	if frozen:
		# The child captured its environment at spawn; clear promptly so a
		# manual F5 run doesn't inherit the freeze. Two frames covers a
		# deferred spawn. (Godot has no unset; empty fails the == "1" check.)
		await Engine.get_main_loop().process_frame
		await Engine.get_main_loop().process_frame
		OS.set_environment(LAUNCH_FROZEN_ENV, "")

	if not await _wait_for_play_state(true, START_TIMEOUT):
		return _error(
			"START_FAILED",
			"Godot did not enter play mode within %.1f seconds. Inspect editor logs for parse, import, main-scene, or resource-load failures before one corrected run." % START_TIMEOUT
		)

	var bridge_ready := false
	var debugger_break := false
	if debugger_plugin != null:
		var started_at := Time.get_ticks_msec()
		while EditorInterface.is_playing_scene():
			if debugger_plugin.is_bridge_ready():
				bridge_ready = true
				break
			if debugger_plugin.is_session_breaked():
				debugger_break = true
				break
			await Engine.get_main_loop().process_frame
			if (Time.get_ticks_msec() - started_at) / 1000.0 > BRIDGE_READY_TIMEOUT:
				break

	if not bridge_ready:
		var runtime_diagnostic: String = (
			debugger_plugin.runtime_diagnostic_summary()
			if debugger_plugin != null else ""
		)
		# A half-started process poisons every following runtime/screenshot call
		# with the same timeout.  Reap it here and return the causal recovery
		# instruction once instead of allowing an unbounded stop/run loop.
		if EditorInterface.is_playing_scene():
			EditorInterface.stop_playing_scene()
			await _wait_for_play_state(false, STOP_TIMEOUT)
		if debugger_break or not runtime_diagnostic.is_empty():
			return _error(
				"GAME_DEBUGGER_BREAK",
				("The candidate entered Godot's runtime debugger before its MCP bridge became ready. "
				+ "This is a product runtime error, not a sidecar/rebind failure. Fix the candidate and run once again."
				+ ("\nRuntime diagnostic:\n" + runtime_diagnostic if not runtime_diagnostic.is_empty() else ""))
			)
		return _error(
			"BRIDGE_NOT_READY",
			"The game launched but its MCP bridge was not ready within %.1f seconds, so the half-started run was stopped. No candidate runtime diagnostic was captured. Request one Runtime-owned rebind; do not repeat unchanged stop/run or runtime calls." % BRIDGE_READY_TIMEOUT
		)

	return _success({
		"bridge_ready": true,
		"frozen": frozen,
		"replaced_previous_run": replaced_previous_run,
	})


func stop_project(_params: Dictionary) -> Dictionary:
	if not EditorInterface.is_playing_scene():
		return _success({"already_stopped": true})
	EditorInterface.stop_playing_scene()
	if not await _wait_for_play_state(false, STOP_TIMEOUT):
		return _error(
			"STOP_TIMEOUT",
			"The game did not stop within %.1f seconds. Inspect the bound game process before retrying; do not start a replacement while teardown is incomplete." % STOP_TIMEOUT
		)
	return _success({"already_stopped": false})


func _wait_for_play_state(expected: bool, timeout_seconds: float) -> bool:
	var started_at := Time.get_ticks_msec()
	while EditorInterface.is_playing_scene() != expected:
		await Engine.get_main_loop().process_frame
		if (Time.get_ticks_msec() - started_at) / 1000.0 > timeout_seconds:
			return false
	return true


func get_log_messages(params: Dictionary) -> Dictionary:
	var clear: bool = params.get("clear", false)
	var limit: int = int(params.get("limit", 50))
	var severity: String = params.get("severity", "all")
	var since: int = int(params.get("since", 0))

	var result := MCPLogger.query(since, severity, limit)

	if clear:
		MCPLogger.clear_errors()

	# The phantom "Identifier not found: <autoload>" errors that mislead agents
	# come from the editor running stale after project.godot was edited on disk
	# (#245). When that divergence is present, attach it here so the caller reads
	# the log and the "your editor is stale, restart it" advisory in one shot,
	# instead of chasing compile errors that do not exist at runtime.
	var staleness := MCPUtils.detect_project_staleness()
	if staleness.get("stale", false):
		result["staleness"] = staleness

	return _success(result)


func get_runtime_log_messages(params: Dictionary) -> Dictionary:
	var debugger_plugin = _plugin.get_debugger_plugin() if _plugin else null
	if debugger_plugin == null:
		return _error("NO_DEBUGGER", "The Godot runtime debugger is unavailable.")
	return _success(debugger_plugin.get_runtime_diagnostics(int(params.get("limit", 50))))


func get_stack_trace(_params: Dictionary) -> Dictionary:
	var frames := MCPLogger.get_last_stack_trace()
	var errors := MCPLogger.get_errors()
	var last_error: Dictionary = errors[-1] if not errors.is_empty() else {}
	return _success({
		"error": last_error.get("message", ""),
		"error_type": last_error.get("type", ""),
		"file": last_error.get("file", ""),
		"line": last_error.get("line", 0),
		"frames": frames,
	})
