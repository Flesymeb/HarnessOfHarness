@tool
class_name MCPBaseCommand
extends RefCounted

var _plugin: EditorPlugin


func setup(plugin: EditorPlugin) -> void:
	_plugin = plugin


func get_commands() -> Dictionary:
	return {}


func _success(result: Dictionary) -> Dictionary:
	return MCPUtils.success(result)


func _error(code: String, message: String) -> Dictionary:
	return MCPUtils.error(code, message)


# A game paused in Godot's debugger cannot service the next frame of an
# asynchronous runtime request.  Report the causal state immediately instead
# of letting every relay degrade into an unrelated TIMEOUT.  Do not continue
# the session automatically: a script error/assert needs a product fix, while
# a user breakpoint needs an explicit debugger decision.
func _debugger_break_error(operation: String) -> Dictionary:
	var recent := MCPLogger.query(maxi(0, MCPLogger.get_seq() - 5), "error", 5)
	var summaries: PackedStringArray = []
	for entry in recent.get("messages", []):
		var location := str(entry.get("file", ""))
		var line := int(entry.get("line", 0))
		if not location.is_empty() and line > 0:
			location += ":%d" % line
		var message := str(entry.get("message", "")).strip_edges()
		if not location.is_empty() and not message.is_empty():
			summaries.append("%s %s" % [location, message])
		elif not message.is_empty():
			summaries.append(message)
	var detail := ""
	if not summaries.is_empty():
		detail = " Recent debugger errors: " + " | ".join(summaries)
	return _error(
		"GAME_DEBUGGER_BREAK",
		"The running game entered Godot's debugger break while %s. Treat this as a candidate runtime error or an intentional breakpoint, not a transport timeout. Inspect get_log_messages/get_stack_trace, then fix the candidate or stop the exact run before retrying.%s" % [operation, detail]
	)


func _get_node(path: String) -> Node:
	return MCPUtils.get_node_from_path(path)


func _serialize_value(value: Variant) -> Variant:
	return MCPUtils.serialize_value(value)


func _require_scene_open() -> Dictionary:
	var root := EditorInterface.get_edited_scene_root()
	if not root:
		return _error("NO_SCENE", "No scene is currently open")
	return {}
