extends SceneTree

const UIInspector := preload("res://addons/godot_mcp/game_bridge/mcp_ui_inspector.gd")


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var root := Control.new()
	root.name = "HUD"
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_STOP
	get_root().add_child(root)
	var button := Button.new()
	button.name = "Start"
	button.position = Vector2(20, 30)
	button.size = Vector2(160, 48)
	root.add_child(button)
	await process_frame

	var result := UIInspector.inspect(root, 8, 16)
	_assert(result["control_count"] == 2, "expected root and button")
	_assert(result["controls"][0]["mouse_filter"] == "stop", "mouse filter must be named")
	_assert(result["controls"][1]["disabled"] == false, "button state must be exposed")
	_assert(not result["input_risks"].is_empty(), "visible STOP controls must be diagnosed")
	_assert(result["truncated"] == false, "bounded complete traversal must not truncate")
	root.queue_free()
	print("ui_inspector_headless_test: PASS")
	quit(0)


func _assert(condition: bool, message: String) -> void:
	if condition:
		return
	push_error(message)
	quit(1)
