@tool
extends MCPBaseCommand
class_name MCPScreenshotCommands

const DEFAULT_MAX_WIDTH := 900
const SCREENSHOT_TIMEOUT := 5.0
const SCENE_OPEN_TIMEOUT := 10.0
const FRAME_PADDING := 1.25
const MAX_FRAME_EXTENT := 1000000.0
const MAX_MULTIMESH_BOUND_INSTANCES := 10000

var _screenshot_result: Dictionary = {}
var _screenshot_pending: bool = false


func get_commands() -> Dictionary:
	return {
		"capture_game_screenshot": capture_game_screenshot,
		"capture_editor_screenshot": capture_editor_screenshot,
		"inspect_scene_3d": inspect_scene_3d
	}


func capture_game_screenshot(params: Dictionary) -> Dictionary:
	if not EditorInterface.is_playing_scene():
		return _error("NOT_RUNNING", "No game is currently running. Use run_project first.")

	var max_width: int = params.get("max_width", DEFAULT_MAX_WIDTH)

	var debugger_plugin = _plugin.get_debugger_plugin() if _plugin else null
	if debugger_plugin == null:
		return _error("NO_DEBUGGER", "Debugger plugin not available")

	if not debugger_plugin.has_active_session():
		return _error("NO_SESSION", "No active debug session. Game may not have MCPGameBridge autoload.")
	if debugger_plugin.is_session_breaked():
		return _debugger_break_error("capturing the game framebuffer")

	_screenshot_pending = true
	_screenshot_result = {}

	debugger_plugin.screenshot_received.connect(_on_screenshot_received, CONNECT_ONE_SHOT)
	debugger_plugin.request_screenshot(max_width)

	var start_time := Time.get_ticks_msec()
	while _screenshot_pending:
		await Engine.get_main_loop().process_frame
		if debugger_plugin.is_session_breaked():
			_screenshot_pending = false
			if debugger_plugin.screenshot_received.is_connected(_on_screenshot_received):
				debugger_plugin.screenshot_received.disconnect(_on_screenshot_received)
			return _debugger_break_error("capturing the game framebuffer")
		if (Time.get_ticks_msec() - start_time) / 1000.0 > SCREENSHOT_TIMEOUT:
			_screenshot_pending = false
			if debugger_plugin.screenshot_received.is_connected(_on_screenshot_received):
				debugger_plugin.screenshot_received.disconnect(_on_screenshot_received)
			return _error("TIMEOUT", "Screenshot request timed out")

	return _screenshot_result


func _on_screenshot_received(success: bool, image_base64: String, width: int, height: int, error: String, preview_image_base64: String, preview_mime_type: String) -> void:
	_screenshot_pending = false
	if success:
		var payload := {
			"image_base64": image_base64,
			"preview_image_base64": preview_image_base64,
			"preview_mime_type": preview_mime_type,
			"width": width,
			"height": height
		}
		# Mesh-integrity warnings ride the same game message (no extra
		# round-trip, no version-skew timeout); pass them through so the
		# server can attach the advisory to the image.
		var dp = _plugin.get_debugger_plugin() if _plugin else null
		if dp != null and not (dp.last_screenshot_warnings as Array).is_empty():
			payload["mesh_warnings"] = dp.last_screenshot_warnings
		_screenshot_result = _success(payload)
	else:
		_screenshot_result = _error("CAPTURE_FAILED", error)


func capture_editor_screenshot(params: Dictionary) -> Dictionary:
	var viewport_type: String = params.get("viewport", "")
	var max_width: int = params.get("max_width", DEFAULT_MAX_WIDTH)

	var viewport: SubViewport = null

	match viewport_type:
		"2d":
			viewport = EditorInterface.get_editor_viewport_2d()
		"3d":
			viewport = EditorInterface.get_editor_viewport_3d(0)
		_:
			viewport = _find_active_viewport()

	if viewport == null:
		return _error("NO_VIEWPORT", "Could not find editor viewport")

	var image := viewport.get_texture().get_image()
	return _process_and_encode_image(image, max_width)


# One bounded editor-navigation transaction for Tester mode. It opens an
# already-existing project-local scene, selects a Node3D, frames the visible
# geometry below it, and captures the resulting 3D editor viewport. It never
# calls save_scene*, reload_scene*, or any resource/source mutation API.
func inspect_scene_3d(params: Dictionary) -> Dictionary:
	var scene_path: String = str(params.get("scene_path", ""))
	var node_path: String = str(params.get("node_path", ""))
	var max_width: int = int(params.get("max_width", DEFAULT_MAX_WIDTH))

	var validation := _validate_inspection_params(scene_path, node_path, max_width)
	if not validation.is_empty():
		return validation

	scene_path = scene_path.simplify_path()
	# open_scene_from_path adds/selects an editor tab; it does not close, save, or
	# reload the current tab, including when that tab has unsaved changes.
	EditorInterface.open_scene_from_path(scene_path)

	var deadline := Time.get_ticks_msec() + int(SCENE_OPEN_TIMEOUT * 1000.0)
	var root := EditorInterface.get_edited_scene_root()
	while not root or not _same_scene_path(root.scene_file_path, scene_path):
		if Time.get_ticks_msec() >= deadline:
			return _error(
				"OPEN_FAILED",
				"Godot did not finish opening the existing scene within %d seconds: %s" % [int(SCENE_OPEN_TIMEOUT), scene_path]
			)
		await Engine.get_main_loop().process_frame
		root = EditorInterface.get_edited_scene_root()

	var node := _get_node(node_path)
	if not node:
		return _error("NODE_NOT_FOUND", "Node not found in %s: %s" % [scene_path, node_path])
	if not node is Node3D:
		return _error("NOT_NODE3D", "Node is not a Node3D and cannot be framed in the 3D editor: %s" % node_path)

	var selection := EditorInterface.get_selection()
	selection.clear()
	selection.add_node(node)
	EditorInterface.edit_node(node)
	EditorInterface.set_main_screen_editor("3D")

	# Let the scene tab, 3D panel, selection gizmo, and viewport become current
	# before moving its editor camera.
	await Engine.get_main_loop().process_frame
	await Engine.get_main_loop().process_frame

	var viewport := EditorInterface.get_editor_viewport_3d(0)
	if not viewport:
		return _error("NO_VIEWPORT", "Could not access the 3D editor viewport")

	var framing := _frame_node_in_viewport(node as Node3D, viewport)
	if framing.has("status"):
		return framing

	# Camera transforms applied by a tool script are adopted by Godot's 3D
	# editor on the following frame. A second frame ensures the viewport texture
	# contains the new view and the selection overlay before capture.
	await Engine.get_main_loop().process_frame
	await Engine.get_main_loop().process_frame

	var screenshot := _process_and_encode_image(viewport.get_texture().get_image(), max_width)
	if screenshot.get("status", "error") != "success":
		return screenshot

	var payload: Dictionary = screenshot.get("result", {})
	payload["scene_path"] = scene_path
	payload["node_path"] = _usable_node_path(root, node)
	payload["node_type"] = node.get_class()
	payload["framing"] = framing
	return screenshot


func _validate_inspection_params(scene_path: String, node_path: String, max_width: int) -> Dictionary:
	if scene_path.is_empty():
		return _error("INVALID_PARAMS", "scene_path is required")
	if not scene_path.begins_with("res://"):
		return _error("INVALID_PARAMS", "scene_path must be project-local and begin with res://")
	for segment in scene_path.trim_prefix("res://").split("/"):
		if segment == "..":
			return _error("INVALID_PARAMS", "scene_path must not contain parent-directory segments")
	if not scene_path.get_extension().to_lower() in ["tscn", "scn"]:
		return _error("INVALID_PARAMS", "scene_path must end in .tscn or .scn")
	if not FileAccess.file_exists(scene_path):
		return _error("FILE_NOT_FOUND", "Scene file not found: %s" % scene_path)
	# Godot presents a modal asking to create an inherited copy when opening an
	# imported scene. Reject it up front so a non-interactive Tester never hangs.
	if FileAccess.file_exists(scene_path + ".import"):
		return _error("IMPORTED_SCENE", "Imported scenes cannot be opened for direct editor inspection: %s" % scene_path)
	if node_path.is_empty():
		return _error("INVALID_PARAMS", "node_path is required")
	if max_width < 16 or max_width > 1920:
		return _error("INVALID_PARAMS", "max_width must be between 16 and 1920")
	return {}


func _same_scene_path(left: String, right: String) -> bool:
	return _resolved_scene_path(left) == _resolved_scene_path(right)


func _resolved_scene_path(path: String) -> String:
	if path.begins_with("uid://"):
		var uid := ResourceUID.text_to_id(path)
		if ResourceUID.has_id(uid):
			path = ResourceUID.get_id_path(uid)
	return ProjectSettings.globalize_path(path).simplify_path()


func _usable_node_path(root: Node, node: Node) -> String:
	var path := "/root/" + str(root.name)
	var relative := root.get_path_to(node)
	if relative != NodePath("."):
		path += "/" + str(relative)
	return path


# Fit an axis-aligned world-space subtree AABB against the camera's current
# orientation. Keeping the user's viewing angle makes successive inspections
# easy to compare; only the optical center/distance (or orthographic size)
# changes. Godot's Node3DEditorViewport detects this external camera move and
# adopts it as its navigation state on the next frame.
func _frame_node_in_viewport(node: Node3D, viewport: SubViewport) -> Dictionary:
	var camera := viewport.get_camera_3d()
	if not camera:
		return _error("NO_CAMERA", "The 3D editor viewport has no camera")

	var bounds_state := {
		"first": true,
		"count": 0,
		"aabb": AABB(),
		"invalid_count": 0,
		"invalid_message": "",
	}
	_collect_visible_bounds(node, bounds_state)
	if bounds_state.invalid_count > 0:
		return _error("UNFRAMEABLE_BOUNDS", str(bounds_state.invalid_message))

	var used_fallback: bool = int(bounds_state.count) == 0
	var center := node.global_position
	var half_extents := Vector3(0.5, 0.5, 0.5)
	if not used_fallback:
		var bounds: AABB = bounds_state.aabb
		center = bounds.get_center()
		half_extents = bounds.size * 0.5
		# Flat or point-like visuals still need a practical inspection scale.
		half_extents.x = max(half_extents.x, 0.05)
		half_extents.y = max(half_extents.y, 0.05)
		half_extents.z = max(half_extents.z, 0.05)
	if not _safe_point(center):
		return _error(
			"UNFRAMEABLE_BOUNDS",
			"Node position is non-finite or outside the safe editor framing range: %s" % str(node.get_path())
		)

	var basis := camera.global_transform.basis.orthonormalized()
	if not basis.x.is_finite() or not basis.y.is_finite() or not basis.z.is_finite():
		basis = Basis.IDENTITY

	var projected_x := _projected_extent(half_extents, basis.x)
	var projected_y := _projected_extent(half_extents, basis.y)
	var projected_depth := _projected_extent(half_extents, basis.z)
	var aspect := max(float(viewport.size.x) / max(float(viewport.size.y), 1.0), 0.1)
	var distance: float
	var projection: String

	if camera.projection == Camera3D.PROJECTION_ORTHOGONAL:
		projection = "orthogonal"
		camera.size = max(2.0 * max(projected_y, projected_x / aspect) * FRAME_PADDING, 0.1)
		distance = max(projected_depth + camera.near * 4.0, 4.0)
	else:
		projection = "perspective"
		var half_fov := deg_to_rad(clamp(camera.fov, 1.0, 179.0)) * 0.5
		var tan_vertical := max(tan(half_fov), 0.001)
		var tan_horizontal := max(tan_vertical * aspect, 0.001)
		distance = projected_depth + max(projected_y / tan_vertical, projected_x / tan_horizontal) * FRAME_PADDING
		distance = max(distance, camera.near * 4.0, 0.1)

	# Keep the target safely inside the editor camera's far plane. Extremely
	# large scenes may not fit in full, but their selected bounds remain visible.
	distance = min(distance, max(camera.far * 0.8, camera.near * 4.0))
	var origin := center + basis.z.normalized() * distance
	camera.global_transform = Transform3D(basis, origin)
	camera.force_update_transform()

	var result := {
		"center": _serialize_value(center),
		"distance": distance,
		"projection": projection,
		"geometry_count": bounds_state.count,
		"used_fallback_bounds": used_fallback,
	}
	if not used_fallback:
		result["bounds"] = _serialize_aabb(bounds_state.aabb)
	return result


func _projected_extent(half_extents: Vector3, axis: Vector3) -> float:
	return (
		abs(axis.x) * half_extents.x
		+ abs(axis.y) * half_extents.y
		+ abs(axis.z) * half_extents.z
	)


func _collect_visible_bounds(node: Node, state: Dictionary) -> void:
	if node is VisualInstance3D and (node as VisualInstance3D).is_visible_in_tree():
		var visual := node as VisualInstance3D
		var resolved_bounds: Variant = _resolve_visual_bounds(visual, state)
		if resolved_bounds is AABB:
			var global_aabb: AABB = resolved_bounds
			if state.first:
				state.aabb = global_aabb
				state.first = false
			else:
				var combined: AABB = state.aabb
				state.aabb = combined.merge(global_aabb)
			state.count += 1

	for child in node.get_children():
		_collect_visible_bounds(child, state)


func _resolve_visual_bounds(visual: VisualInstance3D, state: Dictionary) -> Variant:
	var local_bounds := visual.get_aabb()
	if not _nonempty_aabb(local_bounds) and visual is MultiMeshInstance3D:
		var manual: Variant = _multimesh_local_bounds(visual as MultiMeshInstance3D, state)
		if manual is AABB:
			local_bounds = manual
		else:
			return null

	# A visual with no geometry/custom bounds contributes nothing. The selected
	# Node3D still receives a practical one-unit fallback frame when its whole
	# subtree is empty.
	if not _nonempty_aabb(local_bounds):
		return null

	var global_bounds := visual.global_transform * local_bounds
	if not _safe_aabb(global_bounds):
		_mark_invalid_bounds(
			state,
			"Visual bounds are non-finite or exceed the safe editor framing range: %s" % str(visual.get_path())
		)
		return null
	return global_bounds


func _multimesh_local_bounds(instance: MultiMeshInstance3D, state: Dictionary) -> Variant:
	var multimesh := instance.multimesh
	if not multimesh or not multimesh.mesh:
		return null
	if multimesh.transform_format != MultiMesh.TRANSFORM_3D:
		_mark_invalid_bounds(state, "MultiMesh does not use 3D transforms: %s" % str(instance.get_path()))
		return null

	var count: int = multimesh.visible_instance_count
	if count < 0:
		count = multimesh.instance_count
	count = min(count, multimesh.instance_count)
	if count <= 0:
		return null
	if count > MAX_MULTIMESH_BOUND_INSTANCES:
		_mark_invalid_bounds(
			state,
			"MultiMesh has %d visible instances but no usable AABB; set custom_aabb or inspect a smaller target (safe calculation cap: %d): %s" % [
				count,
				MAX_MULTIMESH_BOUND_INSTANCES,
				str(instance.get_path()),
			]
		)
		return null

	var mesh_bounds: AABB = multimesh.mesh.get_aabb()
	if not _nonempty_aabb(mesh_bounds):
		return null

	var combined := AABB()
	var first := true
	for index in range(count):
		var item_bounds := multimesh.get_instance_transform(index) * mesh_bounds
		if not _safe_aabb(item_bounds):
			_mark_invalid_bounds(
				state,
				"MultiMesh instance %d has unsafe bounds: %s" % [index, str(instance.get_path())]
			)
			return null
		if first:
			combined = item_bounds
			first = false
		else:
			combined = combined.merge(item_bounds)
	return combined


func _mark_invalid_bounds(state: Dictionary, message: String) -> void:
	state.invalid_count += 1
	if str(state.invalid_message).is_empty():
		state.invalid_message = message


func _nonempty_aabb(bounds: AABB) -> bool:
	return (
		bounds.position.is_finite()
		and bounds.size.is_finite()
		and bounds.size.x >= 0.0
		and bounds.size.y >= 0.0
		and bounds.size.z >= 0.0
		and bounds.size.length_squared() > 0.000000000001
	)


func _safe_point(point: Vector3) -> bool:
	return (
		point.is_finite()
		and abs(point.x) <= MAX_FRAME_EXTENT
		and abs(point.y) <= MAX_FRAME_EXTENT
		and abs(point.z) <= MAX_FRAME_EXTENT
	)


func _safe_aabb(bounds: AABB) -> bool:
	return (
		_nonempty_aabb(bounds)
		and _safe_point(bounds.position)
		and _safe_point(bounds.end)
		and bounds.size.x <= MAX_FRAME_EXTENT
		and bounds.size.y <= MAX_FRAME_EXTENT
		and bounds.size.z <= MAX_FRAME_EXTENT
	)


func _serialize_aabb(bounds: AABB) -> Dictionary:
	return {
		"position": _serialize_value(bounds.position),
		"size": _serialize_value(bounds.size),
		"end": _serialize_value(bounds.end),
	}


# Preserve a lossless PNG for the evidence sink, and add a same-resolution JPEG
# preview for the model-facing MCP response. Native Codex currently degrades an
# image block larger than about 1 MiB into truncated JSON text; the compact
# preview avoids that transport fallback while the PNG remains authoritative.
func _encode_context_preview(image: Image) -> String:
	var preview_buffer := PackedByteArray()
	for quality in [0.86, 0.72, 0.58, 0.44, 0.30]:
		preview_buffer = image.save_jpg_to_buffer(quality)
		if preview_buffer.size() <= 700 * 1024:
			break
	return Marshalls.raw_to_base64(preview_buffer)


func _process_and_encode_image(image: Image, max_width: int) -> Dictionary:
	if image == null:
		return _error("CAPTURE_FAILED", "Failed to capture image from viewport")

	if max_width > 0 and image.get_width() > max_width:
		var scale_factor := float(max_width) / float(image.get_width())
		var new_height := int(image.get_height() * scale_factor)
		image.resize(max_width, new_height, Image.INTERPOLATE_LANCZOS)

	var png_buffer := image.save_png_to_buffer()
	var base64 := Marshalls.raw_to_base64(png_buffer)
	var preview_base64 := _encode_context_preview(image)

	return _success({
		"image_base64": base64,
		"preview_image_base64": preview_base64,
		"preview_mime_type": "image/jpeg",
		"width": image.get_width(),
		"height": image.get_height()
	})


# Returns the SubViewport of whichever main-screen tab (2D or 3D) is currently
# active. EditorInterface always hands back both viewports regardless of the
# active tab, so we pick the one whose editor panel is actually on screen. When
# neither is active (e.g. the Script or AssetLib tab is selected) we fall back to
# the 2D canvas so the call still returns an image rather than erroring.
func _find_active_viewport() -> SubViewport:
	var v2d := EditorInterface.get_editor_viewport_2d()
	if v2d and _viewport_on_active_tab(v2d):
		return v2d

	var v3d := EditorInterface.get_editor_viewport_3d(0)
	if v3d and _viewport_on_active_tab(v3d):
		return v3d

	return v2d if v2d else v3d


# A main-screen editor panel (and the viewport nested inside it) is hidden when
# its tab is not the selected one. is_visible_in_tree() on the viewport's
# container is true only when every ancestor is visible, i.e. this is the active
# tab.
func _viewport_on_active_tab(viewport: SubViewport) -> bool:
	var container := viewport.get_parent()
	if container is CanvasItem:
		return (container as CanvasItem).is_visible_in_tree()
	return true
