extends SceneTree

## Guards the dual screenshot contract used by GameLoop Runtime:
## - the authoritative evidence remains a full-resolution PNG;
## - the model-facing JPEG preview keeps the same dimensions;
## - preview bytes stay below native Codex's large-image fallback boundary.

const WIDTH := 1280
const HEIGHT := 720
const MAX_PREVIEW_BYTES := 700 * 1024


func _initialize() -> void:
	var bytes := PackedByteArray()
	bytes.resize(WIDTH * HEIGHT * 3)
	for index in bytes.size():
		bytes[index] = (index * 37 + (index / 997) * 101) % 256
	var image := Image.create_from_data(WIDTH, HEIGHT, false, Image.FORMAT_RGB8, bytes)
	var commands := MCPScreenshotCommands.new()
	var response := commands._process_and_encode_image(image, WIDTH)
	var payload: Dictionary = response.get("result", {})
	var png := Marshalls.base64_to_raw(str(payload.get("image_base64", "")))
	var preview := Marshalls.base64_to_raw(str(payload.get("preview_image_base64", "")))

	var preview_image := Image.new()
	var preview_status := preview_image.load_jpg_from_buffer(preview)
	var ok: bool = (
		response.get("status") == "success"
		and png.size() > 24
		and png.slice(0, 8).hex_encode() == "89504e470d0a1a0a"
		and preview.size() > 4
		and preview.size() <= MAX_PREVIEW_BYTES
		and preview_status == OK
		and preview_image.get_width() == WIDTH
		and preview_image.get_height() == HEIGHT
		and payload.get("preview_mime_type") == "image/jpeg"
	)
	print("context preview bytes=%d png_bytes=%d dimensions=%dx%d" % [
		preview.size(), png.size(), preview_image.get_width(), preview_image.get_height()
	])
	quit(0 if ok else 1)
