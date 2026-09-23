extends RefCounted

## Bounded, read-only Control inspection shared by the editor command layer and
## the running-game bridge.  It exposes the layout and input facts that a
## screenshot cannot prove: global rectangles, anchors, clipping, focus and
## mouse filtering.


static func inspect(root: Node, max_depth: int = 12, max_nodes: int = 128) -> Dictionary:
	max_depth = clampi(max_depth, 1, 32)
	max_nodes = clampi(max_nodes, 1, 512)
	var viewport := root.get_viewport()
	var viewport_rect := Rect2()
	if viewport != null:
		viewport_rect = viewport.get_visible_rect()

	var controls: Array[Dictionary] = []
	var input_risks: Array[Dictionary] = []
	var state := {"truncated": false}
	_collect(root, 0, max_depth, max_nodes, viewport_rect, controls, input_risks, state)
	return {
		"root_path": str(root.get_path()),
		"viewport_rect": _rect(viewport_rect),
		"control_count": controls.size(),
		"truncated": bool(state["truncated"]),
		"controls": controls,
		"input_risks": input_risks,
	}


static func _collect(
		node: Node,
		depth: int,
		max_depth: int,
		max_nodes: int,
		viewport_rect: Rect2,
		controls: Array[Dictionary],
		input_risks: Array[Dictionary],
		state: Dictionary
	) -> void:
	if controls.size() >= max_nodes:
		state["truncated"] = true
		return
	if node is Control:
		var control := node as Control
		var entry := _control_entry(control, viewport_rect)
		controls.append(entry)
		if entry["input_risk"] != "none":
			input_risks.append({
				"path": entry["path"],
				"risk": entry["input_risk"],
				"mouse_filter": entry["mouse_filter"],
				"global_rect": entry["global_rect"],
			})

	if depth >= max_depth:
		if node.get_child_count() > 0:
			state["truncated"] = true
		return
	for child in node.get_children():
		_collect(child, depth + 1, max_depth, max_nodes, viewport_rect, controls, input_risks, state)
		if controls.size() >= max_nodes:
			state["truncated"] = true
			return


static func _control_entry(control: Control, viewport_rect: Rect2) -> Dictionary:
	var global_rect := control.get_global_rect()
	var visible := control.is_visible_in_tree()
	var overlap := global_rect.intersection(viewport_rect) if viewport_rect.has_area() else Rect2()
	var viewport_area := viewport_rect.size.x * viewport_rect.size.y
	var overlap_area := overlap.size.x * overlap.size.y
	var coverage := overlap_area / viewport_area if viewport_area > 0.0 else 0.0
	var filter_value := int(control.mouse_filter)
	var input_risk := "none"
	if visible and overlap.has_area() and filter_value == Control.MOUSE_FILTER_STOP:
		input_risk = "full_viewport_stop" if coverage >= 0.9 else "mouse_stop"
	elif visible and overlap.has_area() and filter_value == Control.MOUSE_FILTER_PASS:
		input_risk = "mouse_pass"

	var entry: Dictionary = {
		"path": str(control.get_path()),
		"type": control.get_class(),
		"visible": control.visible,
		"visible_in_tree": visible,
		"global_rect": _rect(global_rect),
		"viewport_coverage": snapped(coverage, 0.0001),
		"outside_viewport": viewport_rect.has_area() and not global_rect.intersects(viewport_rect),
		"anchors": {
			"left": snapped(control.anchor_left, 0.0001),
			"top": snapped(control.anchor_top, 0.0001),
			"right": snapped(control.anchor_right, 0.0001),
			"bottom": snapped(control.anchor_bottom, 0.0001),
		},
		"offsets": {
			"left": snapped(control.offset_left, 0.01),
			"top": snapped(control.offset_top, 0.01),
			"right": snapped(control.offset_right, 0.01),
			"bottom": snapped(control.offset_bottom, 0.01),
		},
		"clip_contents": control.clip_contents,
		"z_index": control.z_index,
		"z_as_relative": control.z_as_relative,
		"mouse_filter": _mouse_filter_name(filter_value),
		"mouse_filter_value": filter_value,
		"mouse_force_pass_scroll_events": control.mouse_force_pass_scroll_events,
		"focus_mode": _focus_mode_name(int(control.focus_mode)),
		"has_focus": control.has_focus(),
		"input_risk": input_risk,
	}
	if control is BaseButton:
		entry["disabled"] = (control as BaseButton).disabled
	return entry


static func _rect(value: Rect2) -> Dictionary:
	return {
		"x": snapped(value.position.x, 0.01),
		"y": snapped(value.position.y, 0.01),
		"width": snapped(value.size.x, 0.01),
		"height": snapped(value.size.y, 0.01),
	}


static func _mouse_filter_name(value: int) -> String:
	match value:
		Control.MOUSE_FILTER_STOP:
			return "stop"
		Control.MOUSE_FILTER_PASS:
			return "pass"
		Control.MOUSE_FILTER_IGNORE:
			return "ignore"
	return "unknown"


static func _focus_mode_name(value: int) -> String:
	match value:
		Control.FOCUS_NONE:
			return "none"
		Control.FOCUS_CLICK:
			return "click"
		Control.FOCUS_ALL:
			return "all"
		Control.FOCUS_ACCESSIBILITY:
			return "accessibility"
	return "unknown"
