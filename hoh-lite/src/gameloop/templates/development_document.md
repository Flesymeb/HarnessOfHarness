# {{method_name}} development document {{version}}

This is the PM-authored developer document for the next vanilla-like build pass.
The original public {{task_source_name}} instruction remains the task source of truth; this
document only clarifies implementation logic, visible proof targets, and the
next high-impact repairs from public runtime evidence.

## Loop Policy

- Developer owns the main build budget and should make the game, traces, and assets work in one focused pass.
- PM owns document refinement only: convert public task text and prior visible evidence into concrete development requirements.
- LLM tester reviews Godot screenshots, replay traces, and visible gameplay evidence after development; tester does not write production code.
- Avoid splitting work into supervisor, artist, developer, tester, and repair subroles inside the developer pass.
- Keep the implementation close to a normal single-agent {{task_source_name}} run, with this document as extra product context.

## Version Context

- Current document: `{{development_doc_filename}}`
- Planning inputs: `{{planning_inputs}}`
- Build ok observed last loop: `{{build_ok}}`
- Demo count observed last loop: `{{num_demos}}`

## Public Task Brief

{{public_task_instruction}}

## Development Focus For This Loop

{{focus_items}}

{{no_gap_section}}

## PM Iteration Upgrade Plan

This loop is not just a patch pass. After any blocker or high-severity
visible-evidence gap is handled, spend the remaining developer budget on
2-3 high-impact upgrades that make the game feel more complete.

- Mechanics upgrade: deepen one core interaction, combo, resource tradeoff, ability trigger, physics rule, or player decision that is already part of the task.
- Content upgrade: add a distinct stage, wave, enemy/hazard pattern, card/unit/item type, objective, upgrade, or scenario variant that changes play rather than only changing labels.
- Difficulty upgrade: add a readable escalation step, pressure state, failure/recovery moment, close win, or named deeper scenario.
- Presentation upgrade: improve authored/imported assets, animation, particles, hit flashes, camera framing, HUD state, menus, or result screens for the primary gameplay path.
- Demo proof upgrade: update traces so the new mechanic/content/presentation improvement is visible live, not just present in code.

Prefer upgrades that reuse the current playable foundation. Do not replace
a working game with a smaller reset unless launchability is broken.
Protect the strongest previous core-play route and demo quality while
broadening content; a new system should not make movement, controls,
readability, or the primary replay path worse than the prior candidate.

## Replay Regression Guardrails

- Before changing `demo_outputs`, compare the prior demo evidence matrix with
  the new trace plan and preserve each existing demo's purpose.
- If a trace was previously the core-loop trace, do not turn it into a menu-only
  or setup-only trace. If a trace was the breadth trace, do not turn it into a
  solve-only trace that no longer shows the distinct location, stage, case,
  enemy, item, or scenario breadth.
- When adding missing proof, do not compress live play, investigation, setup,
  or result beats out of the recording. Reduce low-value waits or add another
  deterministic trace.
- Preserve explicit result dwell: after win/loss/completion/failure, keep the
  result or summary screen visible long enough to be sampled.
- Do not add a deeper mechanic unless its input, state change, consequence,
  feedback, and result are visible in the shipped replay portfolio.

## Replay-Visible Quality Heuristics

- Build-first: keep the project launchable, replayable, and deterministic before adding breadth.
- Public breadth: extract explicit content nouns and counts from the public task. If it asks for stages, maps, worlds, waves, enemies, hazards, weapons, cards, recipes, songs, opponents, units, buildings, upgrades, endings, or modes, make those variants visible through behavior, art, UI state, and replay evidence.
- Asset coverage: core gameplay entities should use authored/imported visuals when available. Copied-but-unused assets, fonts, icons, UI sounds, or hidden reference art do not prove visual production.
- Full loop: preserve a styled start path, live play, progress, failure or pressure, win/loss/result feedback, and retry/return without requiring an app restart.
- Signature mechanics: each central mechanic should show input, resource or state change, consequence, readable feedback, and replay proof.
- Task-specific results: add summary/progress stats that fit the genre, such as points, cleared stages, waves survived, orders served, medals, combos, upgrades, lives used, time, route, resources, endings, or unlocks.
- Demo quality floor: every shipped demo should look like the same finished game. Remove or upgrade traces that are grey-box, debug-only, static, label-only, or menu-only.

## Demo Portfolio Plan

Use replay traces as product evidence. Prefer a compact set of strong traces
over many weak ones; add traces only when they prove a different public
gameplay promise.

- Core-loop trace: fresh start into normal play with the main controls, objective, HUD feedback, and progress.
- Signature-mechanic trace: the defining mechanic in complete form, including consequence and feedback.
- Breadth trace: later or alternate public-task content, such as stage/map/world, enemy/hazard, card/item, track/song, opponent, recipe, building, upgrade, or ending.
- Pressure/recovery trace: damage, failure risk, resource shortage, comeback, loss, continue, restart, or close win when relevant.
- Result trace: visible completion, loss, summary, unlock, leaderboard, or task-specific stats.

## Genre Breadth Planner

Adapt these public-safe checks to the task text without inventing unrelated
systems:

- Action/shooter/combat: stages or arenas, enemy behaviors, hazards, weapon or ability progression, boss/elite pressure, health/lives, result summary.
- Platformer/open world/puzzle: level spaces, movement constraints, collectibles, gates/objectives, escalating obstacles, completion state.
- Strategy/tycoon/idle/simulation: resources, units/buildings/tools, upgrades, events, production or economy feedback, win/loss or milestone screens.
- Racing/sports/rhythm: events or tracks, opponents/patterns, points/combo/timing feedback, difficulty ramp, medals/results.
- Card/roguelike/narrative/horror: deck/encounter/content variety, risk/reward, branching or unlock evidence, readable state and ending/result feedback.

{{preserve_visible_section}}

## Mechanics Requirements

- Identify the core verbs, controls, resources, game state values, collisions, and result conditions before coding.
- Make each important interaction visible through gameplay action: input, state change, feedback, and consequence.
- Prefer a small set of coherent mechanics that work together over many isolated systems.
- For the signature mechanic, prove the whole chain in replay: trigger, state/resource update, consequence, feedback, and result.

## Content And Progression Requirements

- Include distinct playable situations when feasible: stages, lanes, waves, enemy patterns, hazards, objectives, upgrades, cards, items, or scenario variants.
- Connect content to the core loop so variety changes player decisions instead of only changing labels or colors.
- Use the public task's own nouns and counts to decide breadth. If a requested variant is implemented, make it visibly distinct through both behavior and presentation.
- Preserve already-visible working content from prior loops and extend the next missing beat rather than resetting the game.

## Difficulty Requirements

- Show readable escalation from an easy opening state into a deeper or riskier scenario.
- Include failure/recovery or pressure evidence when the task asks for combat, hazards, survival, races, waves, or resource tension.
- Avoid hidden rules: the HUD, animation, and result feedback should explain why the player is succeeding or failing.

## Visual And Feedback Requirements

- Use visible authored or imported assets for the main player/avatar, terrain or board, interactables, hazards/enemies, results, and at least one environment/background layer when relevant.
- Add HUD state, animation, particles/effects, hit flashes, transitions, camera framing, and result screens where they clarify action and consequence.
- Add result or progress screens with task-specific stats when the game has completion, points, survival, delivery, stages, resources, upgrades, or endings.
- Avoid raw default Godot grey, debug-only shapes, label-only proof, static final states, and disconnected menus.

## Demo Trace Requirements

- Include a core-loop trace from a fresh start.
- Include a deeper-content trace that starts near a later stage, wave, upgrade, card combo, obstacle, or objective when the task supports it.
- Include a result/recovery trace that visibly demonstrates completion, loss, restart, win/result panel, or recovery from failure.
- Include only traces that preserve visual quality and add evidence; a weak placeholder trace can hurt the perceived build quality.
- Keep traces deterministic and short enough for replay sampling while still showing live transitions.

## Compact Quality Checklist

- Core loop: player verb, objective, progression, success/failure, feedback, restart.
- Mechanics: interactions must be visible in live gameplay, not only encoded in setup.
- Content depth: include distinct situations, stages, enemies, hazards, upgrades, or objectives when the task asks for breadth.
- Difficulty progression: demonstrate a readable ramp through scenario setup or trace coverage.
- Presentation: use visible assets, animation, effects, HUD feedback, and styled screens where they affect player understanding.
- Demo proof: include traces that show the first playable path, a deeper content beat, and a result or recovery state.

## Compatibility Brief

- Treat the public task, current focus items, preservation gates, and acceptance
  requirements above as the complete Developer-facing plan for this loop.
- The lossless sanitized execution/QA brief remains a separate Runtime artifact;
  it is not duplicated here because repeated history competes with implementation
  attention.
- Preserve the recorded build/demo baseline, repair current visible gaps, and
  spend remaining time on the highest-impact public-task completeness work.

{{evidence_history_section}}
