extends SceneTree

const SkeletonInspector := preload("res://addons/godot_mcp/game_bridge/mcp_skeleton_inspector.gd")


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var rig := Node3D.new()
	rig.name = "Rig"
	get_root().add_child(rig)
	var skeleton := Skeleton3D.new()
	skeleton.name = "Skeleton3D"
	rig.add_child(skeleton)
	var root_bone := skeleton.add_bone("Root")
	var hand_bone := skeleton.add_bone("Hand.R")
	skeleton.set_bone_parent(hand_bone, root_bone)
	skeleton.set_bone_rest(hand_bone, Transform3D(Basis.IDENTITY, Vector3(0.2, 1.0, -0.4)))
	var attachment := BoneAttachment3D.new()
	attachment.name = "Grip"
	attachment.bone_name = "Hand.R"
	skeleton.add_child(attachment)
	var marker := Marker3D.new()
	marker.name = "Muzzle"
	attachment.add_child(marker)
	await process_frame

	var result := SkeletonInspector.inspect(skeleton, 16)
	_assert(result["bone_count"] == 2, "expected two bones")
	_assert(result["bones"][1]["parent_name"] == "Root", "bone hierarchy must be exposed")
	_assert(result["bone_attachments"][0]["bone_name"] == "Hand.R", "attachment binding must be exposed")
	_assert(result["markers"][0]["path"].ends_with("/Muzzle"), "marker path must be exposed")
	_assert(result["truncated"] == false, "complete pose must not truncate")
	rig.queue_free()
	print("skeleton_inspector_headless_test: PASS")
	quit(0)


func _assert(condition: bool, message: String) -> void:
	if condition:
		return
	push_error(message)
	quit(1)
