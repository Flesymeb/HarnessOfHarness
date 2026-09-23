@tool
extends MCPBaseCommand
class_name MCPSystemCommands


const RESTART_ACK_GRACE_SEC := 0.3


func get_commands() -> Dictionary:
	return {
		"mcp_handshake": mcp_handshake,
		"heartbeat": heartbeat,
		"restart_editor": restart_editor,
	}


func mcp_handshake(params: Dictionary) -> Dictionary:
	var server_version: String = params.get("server_version", "unknown")

	if _plugin and _plugin.has_method("on_server_version_received"):
		_plugin.on_server_version_received(server_version)

	return _success({
		"addon_version": _get_addon_version(),
		"godot_version": Engine.get_version_info()["string"],
		"project_path": ProjectSettings.globalize_path("res://"),
		"project_name": ProjectSettings.get_setting("application/config/name", ""),
		"server_version_received": server_version
	})


func heartbeat(_params: Dictionary) -> Dictionary:
	return _success({"status": "ok"})


func restart_editor(params: Dictionary) -> Dictionary:
	var save: bool = params.get("save", true)

	# Restarting tears down this websocket along with the editor, so defer the
	# actual restart by a short grace period. The websocket command can be
	# dispatched while the peer is being polled outside the SceneTree's safe
	# mutation point. Creating the timer there and letting its callback restart
	# the editor can trip Godot's thread-safety guard in
	# `propagate_notification()` during shutdown. Hop to the main idle queue
	# first, then create the acknowledgement timer from that safe context.
	call_deferred("_restart_editor_after_ack", save)

	return _success({"restarting": true, "save": save})


func _restart_editor_after_ack(save: bool) -> void:
	var tree := Engine.get_main_loop() as SceneTree
	if tree:
		await tree.create_timer(RESTART_ACK_GRACE_SEC).timeout
	if OS.get_environment("GAMELOOP_GODOT_MCP_SUPERVISED_EDITOR") == "1":
		# The outer launcher owns the editor and its Xvfb session. Godot's
		# built-in restart would outlive xvfb-run, losing DISPLAY before the
		# replacement editor can reconnect. Exit and let the launcher respawn.
		if save:
			EditorInterface.save_all_scenes()
		if tree:
			tree.quit()
		return
	EditorInterface.restart_editor(save)


func _get_addon_version() -> String:
	var config := ConfigFile.new()
	var err := config.load("res://addons/godot_mcp/plugin.cfg")
	if err == OK:
		return config.get_value("plugin", "version", "unknown")
	return "unknown"
