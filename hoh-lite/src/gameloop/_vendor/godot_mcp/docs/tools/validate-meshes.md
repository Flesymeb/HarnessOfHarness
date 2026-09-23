# Mesh Validation Tools

Detect silently corrupt procedurally generated mesh data (inside-out winding, dropped triangles, degenerate UVs, NaN normals/tangents) that renders without errors and masquerades as lighting problems. Findings carry their likely cause and fix; a cheap scene-load sniff also attaches one-line warnings to game screenshots.

## Tools

- [godot_validate_meshes](#godot_validate_meshes)

---

## godot_validate_meshes

Check runtime-visible ArrayMesh surfaces in the RUNNING game for silent data corruption that renders WITHOUT any error. Run this FIRST when rendering looks wrong and no error is reported anywhere: surfaces pure black or far too dark, floors/walls invisible or see-through, geometry visible from only one side, lighting that ignores light-energy changes, scenes that "tuning" cannot fix. Detects: inside-out or mixed triangle winding (Godot front faces wind clockwise — wrong winding = culled faces or inverted lighting normals), dropped triangles / orphaned vertices (e.g. SurfaceTool.append_from of an indexed mesh mixed with raw add_vertex silently discards most of the batch), degenerate UVs that make generate_tangents() emit garbage, and NaN/zero normals or tangents. Every finding includes its likely cause and the fix. Read-only and cheap. Walks the current scene only (meshes parented elsewhere under root are not seen). Hidden 3D subtrees are excluded by default; set include_hidden=true only for a source-asset audit. Also run it after writing or changing mesh-generation code — BEFORE spending time tuning lights or materials to rescue a "too dark" scene.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `max_findings` | integer | No | Cap on findings returned (default 25). The total count is always reported. |
| `include_hidden` | boolean | No | Also validate intentionally hidden 3D subtrees such as retarget/calibration sources. Defaults to false so product-facing validation covers runtime-visible meshes only. |

---

