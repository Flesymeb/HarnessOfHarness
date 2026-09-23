"""GameCraft-specific prompt adapters around the generic GameLoop prompt core."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gameloop.core.documents import development_doc_filename, load_public_task_instruction
from gameloop.core.prompts import build_loop_artifacts, render_markdown_template


ADAPTER_ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ADAPTER_ROOT / "templates"
BASE_TEMPLATE = TEMPLATE_DIR / "extra_instruction_base.md"
OUTER_LOOP_ATTEMPT_TEMPLATE = TEMPLATE_DIR / "outer_loop_attempt.md"
VISUAL_TESTER_PROMPT_TEMPLATE = TEMPLATE_DIR / "visual_tester_prompt.md"
WARM_START_SECTION_TEMPLATE = TEMPLATE_DIR / "warm_start_section.md"


FINAL_ITERATION_DEVELOPER_SECTION = """## Final Iteration Completion Gate

This is the final available Developer pass. Before editing, inventory the
prominent mechanics, content families, progression/result states, visual
surfaces, and replay promises explicitly named by the public task. Preserve the
working build, then implement the one or two largest feasible missing promises
as complete player-visible slices. A feature is complete only when real input,
state change, consequence, visible presentation, and shipped replay evidence
agree. Do not spend the final pass on metadata, broad refactoring, receipt
collection, or repeated diagnostics while a higher-impact public promise is
still absent. Nothing can be deferred to another development loop.
"""


def build_visual_tester_prompt(
    *,
    loop_index: int,
    task_dir: Path,
    trial: dict[str, Any] | None,
    development_document: str,
    screenshot_manifest: dict[str, Any],
    tester_phase: str = "next_loop",
    final_iteration: bool = False,
) -> str:
    media_items = screenshot_manifest.get("media") or []
    if media_items:
        media_lines = [
            "- `{path}` ({kind})".format(
                path=item.get("path"),
                kind=item.get("kind"),
            )
            for item in media_items[:80]
            if isinstance(item, dict)
        ]
    else:
        media_lines = [
            "- No screenshot or replay media was discovered. Run available Godot screenshot/replay helpers if they exist, then report the missing evidence explicitly."
        ]

    trial_name = (trial or {}).get("trial_name") or "no completed trial"
    trial_dir = (trial or {}).get("trial_dir") or "no completed trial directory"
    if tester_phase == "acceptance":
        if final_iteration:
            tester_phase_instruction = (
                "You are the inner acceptance tester for the final available loop. "
                "Derive a concise checklist from both the public task and the current "
                "development document, then audit the complete requested player-facing "
                "game—not only this loop's incremental targets. Treat the one or two "
                "highest-impact missing named mechanics, content families, presentation "
                "states, or replay surfaces as same-loop repair blockers. Nothing can be "
                "deferred to a nonexistent next loop."
            )
        else:
            tester_phase_instruction = (
                "You are the inner acceptance tester for the current loop. First derive "
                "a concise acceptance checklist from the current development document. "
                "Then check whether the generated game visibly satisfies those current-loop "
                "requirements. Report developer-owned mismatches that should be repaired "
                "inside this same loop. Do not propose broad next-loop upgrades here."
            )
        tester_phase_output_contract = "\n".join(
            [
                "For the inner acceptance phase, the JSON must include:",
                "",
                "- `phase`: `acceptance`",
                "- `status`: `pass` only when the required acceptance surface is visibly satisfied; otherwise `partial`, `fail`, or `blocked`",
                "- `repair_required`: boolean",
                "- `acceptance_checklist`: checklist items derived from the current development document",
                "- `mismatches`: developer-owned current-loop requirements that are missing, weak, or not replay-visible",
                "- `evidence`: public screenshots, videos, traces, or files inspected",
                "- `recommendation`: focused same-loop repair instructions",
                "",
                "Do not include `next_loop_goals` in the inner acceptance report.",
            ]
        )
    else:
        tester_phase_instruction = (
            "You are the outer next-loop tester. Review the final candidate for this "
            "loop, record remaining public gameplay bugs, and identify the next loop's "
            "highest-impact development targets."
        )
        tester_phase_output_contract = "\n".join(
            [
                "For the outer next-loop phase, the JSON must include:",
                "",
                "- `phase`: `next_loop`",
                "- `status`: `pass`, `partial`, `fail`, or `blocked` for the final candidate",
                "- `remaining_bugs`: public gameplay, demo, or presentation issues still visible after the current loop",
                "- `next_loop_goals`: concrete PM-facing goals for the next development document",
                "- `preserve`: visible working elements that should not be regressed next loop",
                "- `evidence`: public screenshots, videos, traces, or files inspected",
                "- `recommendation`: concise next-loop planning advice",
                "",
                "Do not request same-loop repair in this outer report.",
            ]
        )
    return render_markdown_template(
        VISUAL_TESTER_PROMPT_TEMPLATE,
        {
            "loop_index": loop_index,
            "task_dir": task_dir,
            "trial_name": trial_name,
            "trial_dir": trial_dir,
            "development_doc_filename": development_doc_filename(loop_index),
            "development_document": development_document.rstrip(),
            "media_lines": "\n".join(media_lines),
            "tester_phase_instruction": tester_phase_instruction,
            "tester_phase_output_contract": tester_phase_output_contract,
        },
    )


def build_extra_instruction(
    *,
    mode: str,
    attempt: int,
    task_dir: Path,
    previous_best: dict[str, Any] | None,
    warm_started: bool,
    previous_demo_evidence: dict[str, Any] | None = None,
    development_document: str | None = None,
    final_iteration: bool = False,
) -> str:
    base = BASE_TEMPLATE.read_text(encoding="utf-8") if BASE_TEMPLATE.exists() else ""
    warm_start_section = (
        WARM_START_SECTION_TEMPLATE.read_text(encoding="utf-8").strip()
        if warm_started
        else ""
    )

    if development_document is None:
        artifacts = build_loop_artifacts(
            loop_index=attempt,
            previous_best=previous_best,
            previous_demo_evidence=previous_demo_evidence,
            public_task_instruction=load_public_task_instruction(task_dir),
            method_name="GameCraft",
            task_source_name="GameCraft",
        )
        development_document = artifacts["development_document"]
    wrapper = render_markdown_template(
        OUTER_LOOP_ATTEMPT_TEMPLATE,
        {
            "attempt": attempt,
            "warm_start_section": warm_start_section,
        },
    )
    return "\n\n".join(
        part.strip()
        for part in [
            base,
            wrapper,
            FINAL_ITERATION_DEVELOPER_SECTION if final_iteration else "",
            development_document,
        ]
        if part.strip()
    ).rstrip() + "\n"
