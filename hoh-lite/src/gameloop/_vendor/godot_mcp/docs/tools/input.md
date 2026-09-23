# Input Tools

Input injection for testing running games: named actions, joypad controls, raw keys, event-path absolute pointer clicks/moves, relative mouse-look, and text typing. Absolute pointer events drive Godot event coordinates but do not move the physical OS cursor.

## Tools

- [godot_input](#godot_input)

---

## godot_input

Inject input into a running Godot game for testing: named actions, joypad controls, raw keys, event-path absolute mouse movement/clicks, wheel events, and relative mouse-look. Use `mouse_position:[x,y]` followed by a positioned `mouse_button:left` entry for deterministic UI interaction. These events drive Control and `_input` coordinates but do not move the physical OS cursor or guarantee polled `Viewport.get_mouse_position()`.

### Actions

#### `get_map`

List available input actions from the project Input Map

*No parameters.*

#### `sequence`

Execute an input timeline. While the game runs at real speed, keep tightly-timed inputs in ONE call — e.g. the run-starting menu press AND the gameplay that follows — because seconds of uncontrolled game time pass between two separate tool calls. For a window longer than one call can hold, drive input through godot_game_time step instead.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `inputs` | array | Yes | Mix named actions, joypad buttons/axes/sticks, raw keys, `mouse_position:[x,y]`, positioned `mouse_button` left/right/middle clicks or holds, wheel events, and relative `look:[dx,dy]` on one timeline. Absolute pointer events drive Godot's event path; they do not move the physical OS cursor. |
| `report` | string[] | No | Optional effect probe: GDScript expressions evaluated once before the first input and again after the last, to prove the inputs actually changed something (vs. falling into the void — player dead, UI focus elsewhere, wrong action). Reference autoloads by name (e.g. "G.shots", "G.wave") plus `tree`/`root` (e.g. "tree.get_nodes_in_group('enemies').size()"), same context as godot_game_time step_until. Each expression returns {before, after, changed}; the result also carries any_changed. Expressions do NOT short-circuit and a parse/eval error rejects the call. For a single node property, the shorthand "/root/Game/Player:global_position" is accepted and normalized to root.get_node(...).global_position. The after-reading is sampled a couple frames past the final input, so only near-immediate effects register — for slower effects use godot_game_time or runtime_state watch. |
| `watch` | object {specs, signals, hz} | No | Optional state-over-time sampler owned by THIS input call. It starts immediately before the sequence and stops immediately after it, eliminating model/tool latency between watch_start and input. Prefer this for movement, animation, combat, and UI-transition evidence. The measured sequence must span at most 4500ms; split longer scenarios. |
| `screenshot_at_ms` | integer[] | No | Optional: millisecond offsets (from sequence start) at which to capture a lossless PNG frame DURING the real-time run. The bridge owns the sequence clock, so it grabs each frame at the right moment and returns them with the result — letting you catch transient visuals (muzzle flashes, explosions, kill banners) that fade long before a separate screenshot call could land. Up to 8 frames, each returned as an image labeled with its actual offset; an offset (like the whole sequence) must fall within the 40000ms single-call window. COST: each frame is a SEPARATE image that persists in context every following turn and never decays; cost scales with resolution (~1 visual token per 28x28px patch), independent of format. Use multi-frame ONLY for transient/animated visuals — a static layout needs exactly ONE frame. Prefer a few well-timed native-resolution frames over many redundant ones; for frozen/precise inspection use godot_game_time step + screenshot_game instead. |
| `screenshot_max_width` | integer | No | Max width in px for captured frames (default 1280). GameLoop acceptance uses the native 1280x720 viewport so weapon orientation, arm seams, HUD text, and motion frames remain inspectable. Lower it only for explicitly non-acceptance diagnostic captures. |

#### `type_text`

Type text into the focused UI element

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | Yes | Text to type |
| `delay_ms` | integer | No | Delay between keystrokes in milliseconds (default 50) |
| `submit` | boolean | No | Press Enter after typing to submit (for LineEdit text_submitted) |

### Examples

```json
// get_map
{
  "action": "get_map"
}
```

```json
// sequence
{
  "action": "sequence",
  "inputs": [
    {
      "action_name": "example"
    }
  ]
}
```

```json
// type_text
{
  "action": "type_text",
  "text": "example"
}
```

---
