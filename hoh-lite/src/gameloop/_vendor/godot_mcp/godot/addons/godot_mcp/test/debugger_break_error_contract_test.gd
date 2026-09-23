extends SceneTree

## Headless contract test for the typed debugger-break diagnostic shared by
## game-time, input, and framebuffer relays.  The live is_breaked transition is
## owned by Godot's EditorDebuggerSession and needs an editor integration test;
## this keeps the stable agent-facing code/message semantics independently
## testable.

const BaseCommand := preload("res://addons/godot_mcp/core/base_command.gd")


func _initialize() -> void:
	var command = BaseCommand.new()
	var result: Dictionary = command._debugger_break_error("stepping game time")
	var error: Dictionary = result.get("error", {})
	var passed: bool = (
		result.get("status") == "error"
		and error.get("code") == "GAME_DEBUGGER_BREAK"
		and str(error.get("message", "")).contains("candidate runtime error")
		and str(error.get("message", "")).contains("not a transport timeout")
	)
	print("1..1")
	if passed:
		print("ok 1 - debugger break is a typed non-transport product diagnostic")
		quit(0)
	else:
		printerr("not ok 1 - unexpected debugger break payload: %s" % str(result))
		quit(1)
