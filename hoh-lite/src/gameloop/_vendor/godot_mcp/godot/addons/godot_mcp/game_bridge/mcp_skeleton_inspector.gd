extends RefCounted

## Bounded, read-only Skeleton3D pose inspection.  The payload is intentionally
## made of primitives so it is safe to transport through EngineDebugger and
## useful for comparing gun/hand/enemy bindings across animation states.


static func inspect(skeleton: Skeleton3D, max_bones: int = 128) -> Dictionary:
	max_bones = clampi(max_bones, 1, 512)
	var total_bones := skeleton.get_bone_count()
	var returned_bones := mini(total_bones, max_bones)
	var bones: Array[Dictionary] = []
	for bone_index in range(returned_bones):
		var parent_index := skeleton.get_bone_parent(bone_index)
		var global_pose := skeleton.get_bone_global_pose(bone_index)
		bones.append({
			"index": bone_index,
			"name": skeleton.get_bone_name(bone_index),
			"parent_index": parent_index,
			"parent_name": skeleton.get_bone_name(parent_index) if parent_index >= 0 else "",
			"enabled": skeleton.is_bone_enabled(bone_index),
			"rest": _transform(skeleton.get_bone_rest(bone_index)),
			"pose": _transform(Transform3D(
				Basis.from_scale(skeleton.get_bone_pose_scale(bone_index)) * Basis(skeleton.get_bone_pose_rotation(bone_index)),
				skeleton.get_bone_pose_position(bone_index)
			)),
			"global_pose": _transform(global_pose),
			"world_origin": _vector3(skeleton.to_global(global_pose.origin)),
		})

	var attachments: Array[Dictionary] = []
	var markers: Array[Dictionary] = []
	_collect_bindings(skeleton, attachments, markers, 256)
	return {
		"skeleton_path": str(skeleton.get_path()),
		"bone_count": total_bones,
		"returned_bone_count": bones.size(),
		"truncated": returned_bones < total_bones,
		"bones": bones,
		"bone_attachments": attachments,
		"markers": markers,
		"animation_drivers": _animation_drivers(skeleton),
	}


static func _collect_bindings(
		node: Node,
		attachments: Array[Dictionary],
		markers: Array[Dictionary],
		max_nodes: int
	) -> void:
	if attachments.size() + markers.size() >= max_nodes:
		return
	if node is BoneAttachment3D:
		var attachment := node as BoneAttachment3D
		attachments.append({
			"path": str(attachment.get_path()),
			"bone_name": str(attachment.bone_name),
			"bone_index": attachment.get_bone_idx(),
			"use_external_skeleton": attachment.use_external_skeleton,
			"external_skeleton": str(attachment.external_skeleton),
			"world_origin": _vector3(attachment.global_position),
			"world_rotation_degrees": _vector3(attachment.global_rotation_degrees),
		})
	elif node is Marker3D:
		var marker := node as Marker3D
		markers.append({
			"path": str(marker.get_path()),
			"world_origin": _vector3(marker.global_position),
			"world_rotation_degrees": _vector3(marker.global_rotation_degrees),
		})
	for child in node.get_children():
		_collect_bindings(child, attachments, markers, max_nodes)
		if attachments.size() + markers.size() >= max_nodes:
			return


static func _animation_drivers(skeleton: Skeleton3D) -> Array[Dictionary]:
	var search_root: Node = skeleton.get_parent() if skeleton.get_parent() != null else skeleton
	var drivers: Array[Dictionary] = []
	_collect_animation_drivers(search_root, drivers, 64)
	return drivers


static func _collect_animation_drivers(node: Node, drivers: Array[Dictionary], max_nodes: int) -> void:
	if drivers.size() >= max_nodes:
		return
	if node is AnimationPlayer:
		var player := node as AnimationPlayer
		drivers.append({
			"path": str(player.get_path()),
			"type": "AnimationPlayer",
			"playing": player.is_playing(),
			"current_animation": str(player.current_animation),
			"assigned_animation": str(player.assigned_animation),
			"position": snapped(player.current_animation_position, 0.0001),
			"length": snapped(player.current_animation_length, 0.0001),
		})
	elif node is AnimationTree:
		var tree := node as AnimationTree
		var entry: Dictionary = {
			"path": str(tree.get_path()),
			"type": "AnimationTree",
			"active": tree.active,
			"process_callback": int(tree.callback_mode_process),
			"tree_root_type": tree.tree_root.get_class() if tree.tree_root != null else "",
		}
		var playback = tree.get("parameters/playback")
		if playback is Object and playback.has_method("get_current_node"):
			entry["current_state"] = str(playback.call("get_current_node"))
		drivers.append(entry)
	for child in node.get_children():
		_collect_animation_drivers(child, drivers, max_nodes)
		if drivers.size() >= max_nodes:
			return


static func _transform(value: Transform3D) -> Dictionary:
	var rotation := value.basis.get_rotation_quaternion()
	return {
		"origin": _vector3(value.origin),
		"rotation_quaternion": {
			"x": snapped(rotation.x, 0.0001),
			"y": snapped(rotation.y, 0.0001),
			"z": snapped(rotation.z, 0.0001),
			"w": snapped(rotation.w, 0.0001),
		},
		"scale": _vector3(value.basis.get_scale()),
	}


static func _vector3(value: Vector3) -> Dictionary:
	return {
		"x": snapped(value.x, 0.0001),
		"y": snapped(value.y, 0.0001),
		"z": snapped(value.z, 0.0001),
	}
