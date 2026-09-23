# Loop {{loop_index}} development input

Treat the public task instruction as the PRD. This brief is sanitized: it may
include build status, demo count, public execution errors, and role-produced
evidence, but it must not include numeric evaluation outputs, hidden tests,
private evaluator text, private formulas, requirement IDs, or evaluator-only
rationales.

## Loop Goal

- Produce or improve a playable MVP that is visible through shipped replay traces.
- Convert the previous loop's observable issues into concrete development tasks.
- Treat the warm-start candidate as the baseline when warm-started: preserve
  working visible features and improve the next observable gap rather than
  replacing it with a smaller reset.
- Treat each loop after the first as a substantial product iteration: fix
  observable gaps, then improve mechanics, content breadth, difficulty,
  visual production, result surfaces, or demo evidence.
- Require tester gameplay QA for mechanics, content depth, difficulty progression,
  visual effects/feedback, and asset use/visual production.
- Keep role communication document-based; do not rely on hidden chat state.

## Public Execution Snapshot

- Build ok: `{{build_ok}}`
- Demo count observed: `{{num_demos}}`

{{evidence_gap_section}}

{{preserve_section}}

## Issues For This Loop

{{issue_items}}

## Visible Asset Use Required

Copying files into `assets/` is not enough. Fonts, UI sounds, project icons,
or unused reference sprites do not satisfy visual production by themselves.
Use imported or authored visual assets for player, terrain/platforms, collectibles/items, hazards, gates/results.
Also include at least one environment layer when the task has a visible world.
These assets must be visible in at least one shipped demo, preferably in
the demo that exercises the related mechanic.

The tester must record asset evidence in the demo evidence matrix: source
asset path, in-game entity that uses it, demo id where it is visible, and
any remaining core entity that still renders as a raw programmatic shape.

## Replay-Visible Quality Strategy

Use the public task text as a product brief and convert its nouns into visible
gameplay obligations. When the task asks for multiple stages, maps, enemies,
hazards, weapons, cards, recipes, songs, opponents, units, buildings, upgrades,
or endings, implement enough distinct variants to make that breadth obvious
through behavior, art, UI state, and replay coverage.

- Build-first: a richer game that fails launch or replay is not useful.
- Full loop: show styled start, live play, progression, pressure or failure,
  completion/result feedback, and a retry or return path without restarting
  the app.
- Signature mechanic: for each central mechanic, show player input, state or
  resource change, consequence, readable feedback, and demo proof.
- Result surfaces: add task-specific stats and progress labels where relevant,
  such as points, cleared stages, waves survived, orders served, medals, combos,
  upgrades, lives used, time, route, resources, endings, or unlocked content.
- Presentation baseline: every shipped demo should look like the same finished
  game. Do not include grey-box, debug-only, static, or menu-only traces.

## Demo Portfolio Required

Plan replay traces as a compact evidence portfolio rather than a random set
of recordings. Use up to the available trace budget, but only keep traces
that add visible evidence and maintain the presentation baseline.

- Fresh-start core loop trace: start screen into ordinary play with the main verb.
- Signature-mechanic trace: the central mechanic in complete form, including
  feedback and consequence.
- Breadth trace: distinct public-task content such as later stage/map/wave,
  enemy pattern, item, card, recipe, track, opponent, building, or upgrade.
- Pressure or recovery trace: failure risk, damage, resource shortage, comeback,
  loss, continue, or restart when relevant.
- Result trace: visible win, loss, summary, unlock, leaderboard, ending, or
  task-specific stats.

## Replay Regression Guardrails

- Before editing demo traces, preserve each existing demo's purpose: core-loop
  traces should still show live core play, breadth traces should still show
  distinct content breadth, pressure traces should still show risk/recovery,
  and result traces should keep clear result dwell.
- When adding missing proof to an existing trace, do not compress investigation,
  play, setup, or result beats out of the video. Shorten low-value waits or
  add a separate trace instead.
- Keep result dwell after wins, losses, completions, unlocks, and failure states
  so the outcome is visible in replay sampling.
- A feature is not preserved if it exists in code but the new demo portfolio no
  longer shows the previous visible evidence.

## Tester Gameplay QA Required

Tester must produce a number-free gameplay assessment with entries for:

- gameplay mechanics
- content depth
- difficulty progression
- visual effects and feedback
- asset use and visual production
- replay-visible quality

Each entry must include status, evidence, player impact, likely owner, and
recommendation. Use only public PRD text, the generated game, replay media,
screenshots, and role notes.

## Demo Evidence Review Required

Tester must review the shipped demo/replay media as product evidence, not
just the source code or scenario setup. For each important PRD gameplay
promise, decide whether the required gameplay is actually recorded in at
least one demo: core verb, progression beat, mechanic interaction, failure
or recovery, completion/result state, UI feedback, and asset/visual effect.

If a feature exists in code but is not visible in the captured demo path,
mark it as an evidence gap and recommend concrete trace or scenario changes
for the next loop. Keep this review number-free and based only on public
task text plus observable game/replay evidence.

When practical, write the structured review to
`/workspace/game/reports/playtest/demo_evidence_matrix.json` using fields
`demos`, `claim_reviews`, and `evidence_gaps` so the next loop can carry
forward exact visible-evidence gaps.
