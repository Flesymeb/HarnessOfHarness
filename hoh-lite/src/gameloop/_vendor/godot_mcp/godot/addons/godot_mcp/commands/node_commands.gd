@tool
extends MCPBaseCommand
class_name MCPNodeCommands

const FIND_NODES_TIMEOUT := 5.0
const RUNTIME_PROPERTIES_TIMEOUT := 5.0
const UI_INSPECT_TIMEOUT := 5.0
const UIInspector := preload("res://addons/godot_mcp/game_bridge/mcp_ui_inspector.gd")
const SkeletonInspector := preload("res://addons/godot_mcp/game_bridge/mcp_skeleton_inspector.gd")

var _find_nodes_pending := false
var _find_nodes_result: Dictionary = {}


func get_commands() -> Dictionary:
	return {
		"get_node_properties": get_node_properties,
		"inspect_ui": inspect_ui,
		"inspect_skeleton": inspect_skeleton,
		"find_nodes": find_nodes,
		"update_node": update_node,
		"reparent_node": reparent_node
	}


func get_node_properties(params: Dictionary) -> Dictionary:
	var node_path: String = params.get("node_path", "")
	if node_path.is_empty():
		return _error("INVALID_PARAMS", "node_path is required")

	var debugger := _plugin.get_debugger_plugin() as MCPDebuggerPlugin
	if debugger and EditorInterface.is_playing_scene() and debugger.has_active_session():
		return await _get_node_properties_via_game(debugger, node_path)

	var node := _get_node(node_path)
	if not node:
		return _error("NODE_NOT_FOUND", "Node not found: %s" % node_path)

	var properties := {}
	for prop in node.get_property_list():
		var name: String = prop["name"]
		if name.begins_with("_") or prop["usage"] & PROPERTY_USAGE_SCRIPT_VARIABLE == 0:
			if prop["usage"] & PROPERTY_USAGE_EDITOR == 0:
				continue

		var value = node.get(name)
		properties[name] = _serialize_value(value)

	return _success({"properties": properties})


func _get_node_properties_via_game(debugger: MCPDebuggerPlugin, node_path: String) -> Dictionary:
	var msg_type := "get_node_properties"
	if not debugger.send_game_message(msg_type, [node_path]):
		return _error("SEND_FAILED", "Failed to request runtime node properties")

	var start_time := Time.get_ticks_msec()
	while not debugger.has_response(msg_type):
		await Engine.get_main_loop().process_frame
		if (Time.get_ticks_msec() - start_time) / 1000.0 > RUNTIME_PROPERTIES_TIMEOUT:
			debugger.clear_response(msg_type)
			return _error(
				"TIMEOUT",
				"Game did not return node properties within %d seconds" % int(RUNTIME_PROPERTIES_TIMEOUT)
			)

	var response = debugger.get_response(msg_type)
	debugger.clear_response(msg_type)
	if not response is Dictionary:
		return _error("GAME_ERROR", "Runtime node-properties response was malformed")
	var error_message: String = str(response.get("error", ""))
	if not error_message.is_empty():
		return _error("NODE_NOT_FOUND", error_message)
	return _success({"properties": response.get("properties", {})})


func inspect_ui(params: Dictionary) -> Dictionary:
	var root_path: String = params.get("root_path", "")
	var max_depth: int = int(params.get("max_depth", 12))
	var max_nodes: int = int(params.get("max_nodes", 128))
	var debugger := _plugin.get_debugger_plugin() as MCPDebuggerPlugin
	if debugger and EditorInterface.is_playing_scene() and debugger.has_active_session():
		return await _inspect_ui_via_game(debugger, root_path, max_depth, max_nodes)

	var scene_check := _require_scene_open()
	if not scene_check.is_empty():
		return scene_check
	var root: Node = EditorInterface.get_edited_scene_root()
	if not root_path.is_empty():
		root = _get_node(root_path)
		if root == null:
			return _error("NODE_NOT_FOUND", "UI inspection root not found: %s" % root_path)
	return _success({"inspection": UIInspector.inspect(root, max_depth, max_nodes)})


func _inspect_ui_via_game(
		debugger: MCPDebuggerPlugin,
		root_path: String,
		max_depth: int,
		max_nodes: int
	) -> Dictionary:
	var msg_type := "inspect_ui"
	if not debugger.send_game_message(msg_type, [root_path, max_depth, max_nodes]):
		return _error("SEND_FAILED", "Failed to request runtime UI inspection")
	var start_time := Time.get_ticks_msec()
	while not debugger.has_response(msg_type):
		await Engine.get_main_loop().process_frame
		if debugger.is_session_breaked():
			debugger.clear_response(msg_type)
			return _debugger_break_error("inspecting runtime UI")
		if (Time.get_ticks_msec() - start_time) / 1000.0 > UI_INSPECT_TIMEOUT:
			debugger.clear_response(msg_type)
			return _error("TIMEOUT", "Game did not return UI layout within %d seconds" % int(UI_INSPECT_TIMEOUT))

	var response = debugger.get_response(msg_type)
	debugger.clear_response(msg_type)
	if not response is Dictionary:
		return _error("GAME_ERROR", "Runtime UI-inspection response was malformed")
	var error_message: String = str(response.get("error", ""))
	if not error_message.is_empty():
		return _error("NODE_NOT_FOUND", error_message)
	return _success({"inspection": response.get("inspection", {})})


func inspect_skeleton(params: Dictionary) -> Dictionary:
	var node_path: String = params.get("node_path", "")
	var max_bones: int = int(params.get("max_bones", 128))
	if node_path.is_empty():
		return _error("INVALID_PARAMS", "node_path is required")
	var debugger := _plugin.get_debugger_plugin() as MCPDebuggerPlugin
	if debugger and EditorInterface.is_playing_scene() and debugger.has_active_session():
		return await _inspect_skeleton_via_game(debugger, node_path, max_bones)

	var node := _get_node(node_path)
	if node == null:
		return _error("NODE_NOT_FOUND", "Skeleton not found: %s" % node_path)
	if not node is Skeleton3D:
		return _error("INVALID_NODE_TYPE", "Node is not a Skeleton3D: %s" % node_path)
	return _success({"inspection": SkeletonInspector.inspect(node as Skeleton3D, max_bones)})


func _inspect_skeleton_via_game(
		debugger: MCPDebuggerPlugin,
		node_path: String,
		max_bones: int
	) -> Dictionary:
	var msg_type := "inspect_skeleton"
	if not debugger.send_game_message(msg_type, [node_path, max_bones]):
		return _error("SEND_FAILED", "Failed to request runtime skeleton inspection")
	var start_time := Time.get_ticks_msec()
	while not debugger.has_response(msg_type):
		await Engine.get_main_loop().process_frame
		if debugger.is_session_breaked():
			debugger.clear_response(msg_type)
			return _debugger_break_error("inspecting runtime skeleton")
		if (Time.get_ticks_msec() - start_time) / 1000.0 > UI_INSPECT_TIMEOUT:
			debugger.clear_response(msg_type)
			return _error("TIMEOUT", "Game did not return skeleton pose within %d seconds" % int(UI_INSPECT_TIMEOUT))

	var response = debugger.get_response(msg_type)
	debugger.clear_response(msg_type)
	if not response is Dictionary:
		return _error("GAME_ERROR", "Runtime skeleton-inspection response was malformed")
	var error_message: String = str(response.get("error", ""))
	if not error_message.is_empty():
		return _error(str(response.get("code", "GAME_ERROR")), error_message)
	return _success({"inspection": response.get("inspection", {})})


func find_nodes(params: Dictionary) -> Dictionary:
	var name_pattern: String = params.get("name_pattern", "")
	var type_filter: String = params.get("type", "")
	var root_path: String = params.get("root_path", "")

	if name_pattern.is_empty() and type_filter.is_empty():
		return _error("INVALID_PARAMS", "At least one of name_pattern or type is required")

	var debugger := _plugin.get_debugger_plugin() as MCPDebuggerPlugin
	if debugger and EditorInterface.is_playing_scene() and debugger.has_active_session():
		return await _find_nodes_via_game(debugger, name_pattern, type_filter, root_path)

	var scene_check := _require_scene_open()
	if not scene_check.is_empty():
		return scene_check

	var scene_root := EditorInterface.get_edited_scene_root()
	var search_root: Node = scene_root

	if not root_path.is_empty():
		search_root = _get_node(root_path)
		if not search_root:
			return _error("NODE_NOT_FOUND", "Root node not found: %s" % root_path)

	var matches: Array[Dictionary] = []
	_find_recursive(search_root, scene_root, name_pattern, type_filter, matches)

	return _success({"matches": matches, "count": matches.size()})


func _find_nodes_via_game(debugger: MCPDebuggerPlugin, name_pattern: String, type_filter: String, root_path: String) -> Dictionary:
	_find_nodes_pending = true
	_find_nodes_result = {}

	if debugger.find_nodes_received.is_connected(_on_find_nodes_received):
		debugger.find_nodes_received.disconnect(_on_find_nodes_received)
	debugger.find_nodes_received.connect(_on_find_nodes_received, CONNECT_ONE_SHOT)
	debugger.request_find_nodes(name_pattern, type_filter, root_path)

	var start_time := Time.get_ticks_msec()
	while _find_nodes_pending:
		await Engine.get_main_loop().process_frame
		if (Time.get_ticks_msec() - start_time) / 1000.0 > FIND_NODES_TIMEOUT:
			_find_nodes_pending = false
			if debugger.find_nodes_received.is_connected(_on_find_nodes_received):
				debugger.find_nodes_received.disconnect(_on_find_nodes_received)
			return _error("TIMEOUT", "Game did not respond within %d seconds" % int(FIND_NODES_TIMEOUT))

	return _find_nodes_result


func _on_find_nodes_received(matches: Array, count: int, error: String) -> void:
	_find_nodes_pending = false
	if not error.is_empty():
		_find_nodes_result = _error("GAME_ERROR", error)
	else:
		_find_nodes_result = _success({"matches": matches, "count": count})


func _find_recursive(node: Node, scene_root: Node, name_pattern: String, type_filter: String, results: Array[Dictionary]) -> void:
	var name_matches := name_pattern.is_empty() or node.name.matchn(name_pattern)
	var type_matches := type_filter.is_empty() or node.is_class(type_filter)

	if name_matches and type_matches:
		var relative_path := scene_root.get_path_to(node)
		var usable_path := "/root/" + scene_root.name
		if relative_path != NodePath("."):
			usable_path += "/" + str(relative_path)

		results.append({
			"path": usable_path,
			"type": node.get_class()
		})

	for child in node.get_children():
		_find_recursive(child, scene_root, name_pattern, type_filter, results)


func update_node(params: Dictionary) -> Dictionary:
	var node_path: String = params.get("node_path", "")
	var properties: Dictionary = params.get("properties", {})

	if node_path.is_empty():
		return _error("INVALID_PARAMS", "node_path is required")
	if properties.is_empty():
		return _error("INVALID_PARAMS", "properties is required")

	var node := _get_node(node_path)
	if not node:
		return _error("NODE_NOT_FOUND", "Node not found: %s" % node_path)

	for key in properties:
		if key in node:
			var deserialized := MCPUtils.deserialize_value(properties[key])
			node.set(key, deserialized)

	return _success({})


func reparent_node(params: Dictionary) -> Dictionary:
	var scene_check := _require_scene_open()
	if not scene_check.is_empty():
		return scene_check

	var node_path: String = params.get("node_path", "")
	var new_parent_path: String = params.get("new_parent_path", "")

	if node_path.is_empty():
		return _error("INVALID_PARAMS", "node_path is required")
	if new_parent_path.is_empty():
		return _error("INVALID_PARAMS", "new_parent_path is required")

	var node := _get_node(node_path)
	if not node:
		return _error("NODE_NOT_FOUND", "Node not found: %s" % node_path)

	var new_parent := _get_node(new_parent_path)
	if not new_parent:
		return _error("NODE_NOT_FOUND", "New parent not found: %s" % new_parent_path)

	var root := EditorInterface.get_edited_scene_root()
	if node == root:
		return _error("CANNOT_REPARENT_ROOT", "Cannot reparent the root node")

	if new_parent == node or node.is_ancestor_of(new_parent):
		return _error("INVALID_REPARENT", "Cannot reparent a node to itself or its descendant")

	node.reparent(new_parent)

	return _success({"new_path": str(root.get_path_to(node))})
