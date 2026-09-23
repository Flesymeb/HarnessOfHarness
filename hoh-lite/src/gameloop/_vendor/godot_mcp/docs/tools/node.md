# Node Tools

Node manipulation and script attachment tools

## Tools

- [godot_node_read](#godot_node_read)
- [godot_node_edit](#godot_node_edit)

---

## godot_node_read

Inspect scene nodes: while a game is running, get_properties, find, inspect_ui and inspect_skeleton query the live runtime tree (including spawned nodes); otherwise they query the scene open in the editor. inspect_ui exposes Control geometry and input interception; inspect_skeleton exposes real bone pose/socket/animation bindings that screenshots or synthetic marker telemetry cannot prove. get_scene_tree always reports the editor-open scene, including children inside instanced sub-scenes. Use exact paths returned by find in the same run. It cannot modify anything; to update properties or reparent a node, use godot_node_edit.

### Actions

#### `get_properties`

Get a node's properties

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `node_path` | string | Yes | Path to the node |

#### `get_scene_tree`

Full hierarchy of the open scene as the editor sees it, including children inside instanced sub-scenes (a .tscn file read cannot show those). Deep or wide scenes can be large — cap the result with max_depth and/or max_children; any node whose children are cut off carries "truncated_children": <count of omitted direct children> instead of (or alongside) "children".

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `max_depth` | integer | No | Cap recursion depth (root = depth 1). Omit for the full tree. |
| `max_children` | integer | No | Cap how many children are listed per node. Omit to list every child. |

#### `find`

Find nodes by name and/or type. Searches the RUNNING game's live tree when a game is playing (spawned entities included); otherwise searches the scene open in the editor.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name_pattern` | string | No | Glob pattern to match node names, e.g. "*Spawner*", "Turret?" |
| `type` | string | No | Filter by node type, e.g. "CharacterBody2D", "Area2D" |
| `root_path` | string | No | Path to start search from (defaults to scene root) |

#### `inspect_ui`

Inspect bounded Control layout and input behavior in the running game, or in the editor-open scene when stopped. Returns global rectangles, anchors, offsets, clipping, z-order, focus, mouse_filter and explicit full-screen input risks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `root_path` | string | No | Optional subtree root. Defaults to the current scene root. |
| `max_depth` | integer | No | Maximum descendant depth to inspect (default 12). |
| `max_nodes` | integer | No | Maximum Control nodes to return (default 128). |

#### `inspect_skeleton`

Inspect a Skeleton3D live pose, hierarchy, BoneAttachment3D/Marker3D bindings and nearby AnimationPlayer/AnimationTree state. Use a path returned by find(type="Skeleton3D").

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `node_path` | string | Yes | Exact Skeleton3D path. |
| `max_bones` | integer | No | Maximum bones to return (default 128). |

### Examples

```json
// get_properties
{
  "action": "get_properties",
  "node_path": "/root/Main/Player"
}
```

```json
// get_scene_tree
{
  "action": "get_scene_tree"
}
```

```json
// find
{
  "action": "find",
  "name_pattern": "*Enemy*"
}
```

*2 more actions available: `inspect_ui`, `inspect_skeleton`*

---

## godot_node_edit

Modify scene nodes in the editor: update a node's properties, or reparent it (the editor rewrites child paths and signal connections correctly; hand-editing .tscn for a reparent does not). Use it to change existing nodes in the open scene. To inspect properties, the scene tree, or search for nodes, use godot_node_read; to add or remove nodes, or attach scripts and connect signals, edit the .tscn file directly, then verify with godot_node_read's get_scene_tree.

### Actions

#### `update`

Update a node's properties

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `node_path` | string | Yes | Path to the node |
| `properties` | Record<string, unknown> | Yes | Properties to set on the node |

#### `reparent`

Move a node to a new parent

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `node_path` | string | Yes | Path to the node |
| `new_parent_path` | string | Yes | Path to the new parent node |

### Examples

```json
// update
{
  "action": "update",
  "node_path": "/root/Main/Player",
  "properties": {
    "position": {
      "x": 100,
      "y": 50
    }
  }
}
```

```json
// reparent
{
  "action": "reparent",
  "node_path": "/root/Main/Player",
  "new_parent_path": "/root/UI"
}
```

---

