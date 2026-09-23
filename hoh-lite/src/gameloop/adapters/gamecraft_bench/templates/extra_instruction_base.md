# GameCraft outer-loop guidance

You are building a complete Godot 4 game for GameCraft-Bench. Optimize for
observed playability under replay, not for a static screenshot or UI mockup.

Non-negotiables:

- Create the complete project at `/workspace/game`.
- Include `project.godot` and a launchable main scene.
- Include 1-10 deterministic `demo_outputs/*.json` traces.
- Give each trace a top-level `"duration_frames"` integer from 1 through 600
  and a top-level `"events"` array. Give each input event a `"frame"` and a
  supported `"type"`. Keep event frames within the trace duration.
- Use named scenarios when a trace needs a late-game, combat, upgrade, result,
  or near-victory state.
- Make the game pass `godot --headless --path /workspace/game --quit-after 5`.
- Use assets from `/workspace/assets/library` or `/workspace/assets/library-oga`
  when possible, copied into the project.
- Copying asset files into the project is not enough. The core gameplay entities
  must visibly use imported or authored visual assets in the replay demos:
  player, terrain/platforms, collectibles/items, hazards, gates/results, and
  at least one environment/background layer when the task has a visible world.
  The asset use must be visible in the replay demos, not just present on disk.
- Avoid raw default Godot grey, static label-only demos, unstyled rectangles, and
  disconnected menus.
- Show visible state changes for every core mechanic: success, failure,
  progression, resource changes, hazards, results, and completion.
- Make demos demonstrate real interaction and meaningful state transitions.
- Convert public task breadth into visible gameplay. If the task asks for
  multiple stages, maps, enemies, hazards, weapons, cards, recipes, songs,
  opponents, units, buildings, upgrades, endings, or modes, those variants must
  differ visibly in behavior and presentation, not only in labels or colors.
- Preserve a complete product loop: styled start path, live play, progression,
  pressure or failure, completion/result feedback, and retry or return without
  requiring an app restart.
- Add task-specific result/progress stats when relevant: points, cleared stages,
  waves survived, orders served, medals, combos, upgrades, lives used, time,
  route, resources, endings, or unlocks.
- Every shipped demo should meet the same presentation baseline. Do not keep
  grey-box, debug-only, static, label-only, or menu-only traces just to increase
  demo count.

Before finishing:

- Run the headless Godot launch check.
- Use the screenshot helper if available.
- Verify every demo JSON has its intended duration, supported input events,
  and a replayable path from a fresh launch.
- Check that the first screen is styled and has a clear start path.
- Check that at least one trace demonstrates the core loop and at least one
  trace demonstrates deeper content or a result state.
- Plan demos as a compact evidence portfolio when possible: fresh-start core
  loop, signature mechanic, content breadth, pressure/recovery, and result
  summary. Keep only traces that add visible public-task evidence.
- Follow the public GameCraft replay trace contract exactly. Each
  `demo_outputs/*.json` event `type` must be one of:
  `mouse_click`, `mouse_down`, `mouse_up`, `mouse_move`, `key_press`,
  `key_down`, `key_up`, or `wait`. Do not emit custom event types such as
  `action`, `game_action`, `invoke`, or method-call events. To exercise a
  custom Godot callback, encode the equivalent visible mouse or keyboard input
  at the correct viewport coordinates/keycode.
- Every mouse event must put integer-convertible `x` and `y` at the event's
  top level (not in a `position` array). Every key event needs `keycode`.
  Mouse buttons are `left` or `right`; replay defaults to `left` if omitted.
  Use key names such as `"2"`, `"R"`, `"SPACE"`, or `"ENTER"`; do not use Godot
  numeric keycodes or ASCII numbers such as `50` for the `2` key.
- Before finishing, parse every shipped trace from a fresh launch and reject
  any trace containing an unsupported event type. A trace that works only
  with a private replay hook is not valid benchmark evidence.
- Include a number-free tester gameplay assessment when acting as tester or
  producing loop notes. Cover gameplay mechanics, content depth, difficulty
  progression, visual effects/feedback, asset use/visual production, and
  replay-visible quality using only public PRD text and observable game/replay
  evidence.
- Verify that visible asset use is real: list source asset paths, which in-game
  entities use them, and which demo shows them. Fonts, UI sounds, project icons,
  copied-but-unused spritesheets, and reference-only art do not count as visible
  gameplay asset use.
- When acting as tester, review the shipped demo/replay media itself. Check
  whether the required gameplay is actually recorded, not only whether it exists
  in code or scenario setup. If a feature is present but not visible in the demo,
  report an evidence gap and recommend concrete trace or scenario changes.
