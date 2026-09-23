"""Prompt and development-document builders for the generic GameLoop method."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gameloop.core.documents import development_doc_filename, write_json
from gameloop.core.evidence import (
    build_demo_evidence_matrix,
    build_loop_issues,
    build_loop_memory,
    build_public_execution_snapshot,
    build_verified_demo_claims,
)
from gameloop.core.stages import loop_tag


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PACKAGE_ROOT / "templates"
DEVELOPMENT_BRIEF_TEMPLATE = TEMPLATE_DIR / "development_brief.md"
DEVELOPMENT_DOCUMENT_TEMPLATE = TEMPLATE_DIR / "development_document.md"
DEVELOPMENT_DOC_DELTA_TEMPLATE = TEMPLATE_DIR / "development_doc_delta.md"
PROJECT_PLANNER_PROMPT_TEMPLATE = TEMPLATE_DIR / "project_planner_prompt.md"


def render_markdown_template(path: Path, values: dict[str, Any]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text.rstrip() + "\n"


def join_markdown_blocks(blocks: list[str]) -> str:
    return "\n\n".join(block.strip("\n") for block in blocks if block.strip())


def _trim_sentence(value: Any) -> str:
    return str(value or "").strip().rstrip(".。;；")


def _format_evidence(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(_trim_sentence(item) for item in value if item)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return _trim_sentence(value)


def format_issue_items(
    issues: list[dict[str, Any]],
    *,
    action_label: str,
) -> str:
    lines: list[str] = []
    for issue in issues:
        impact = _trim_sentence(issue.get("impact"))
        impact_text = f" Impact: {impact}." if impact else ""
        evidence = _format_evidence(issue.get("evidence"))
        evidence_text = f" Evidence: {evidence}." if evidence else ""
        lines.append(
            "- `{id}` {severity}: {title}.{impact}{evidence} {action_label}: {recommendation}".format(
                id=issue.get("id"),
                severity=issue.get("severity"),
                title=_trim_sentence(issue.get("title")),
                impact=impact_text,
                evidence=evidence_text,
                action_label=action_label,
                recommendation=_trim_sentence(issue.get("recommendation")),
            )
        )
    return "\n".join(lines)


def format_verified_claim_items(
    verified_demo_claims: list[dict[str, Any]] | None,
) -> str:
    lines: list[str] = []
    for claim in verified_demo_claims or []:
        demos = ", ".join(claim.get("demo_ids") or [])
        demo_text = f" in demos `{demos}`" if demos else ""
        lines.append(
            "- `{claim_id}`{demo_text}: {evidence}".format(
                claim_id=claim.get("claim_id"),
                demo_text=demo_text,
                evidence=claim.get("evidence", ""),
            )
        )
    return "\n".join(lines)


def format_evidence_history(
    evidence_history: list[dict[str, Any]] | None,
) -> str:
    if not evidence_history:
        return ""
    lines = [
        "## Prior Public Evidence Ledger",
        "",
        (
            "This is a bounded regression summary. The complete lossless public "
            "ledger remains in the loop artifact `evidence_history.json`; do not "
            "reopen an older item unless current evidence shows a regression."
        ),
    ]
    for entry in evidence_history[-3:]:
        if not isinstance(entry, dict):
            continue
        source_loop = entry.get("source_loop")
        snapshot = entry.get("public_execution_snapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        qa = entry.get("qa_tester_evidence")
        qa = qa if isinstance(qa, dict) else {}
        lines.extend(
            [
                "",
                f"### Loop {source_loop}",
                "",
                (
                    "- Execution: build={build}; demos={demos}; public errors={errors}."
                ).format(
                    build=snapshot.get("build_ok"),
                    demos=snapshot.get("num_demos"),
                    errors=len(snapshot.get("errors") or []),
                ),
            ]
        )
        for label, keys in (
            ("Open at that loop", ("remaining_bugs", "evidence_gaps")),
            ("Planned next", ("next_loop_goals",)),
            ("Preserve", ("preserve",)),
        ):
            items: Any = None
            for key in keys:
                candidate = qa.get(key)
                if isinstance(candidate, list) and candidate:
                    items = candidate
                    break
            summaries = []
            for item in (items or [])[:3]:
                summary = _compact_history_item(item)
                if summary:
                    summaries.append(summary)
            if summaries:
                lines.append(f"- {label}: " + " | ".join(summaries))
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) <= 6000:
        return text
    clipped = text[:5900].rsplit("\n", 1)[0]
    return clipped + "\n- Older detail omitted from the prompt; see `evidence_history.json`.\n"


def _compact_history_item(value: Any, *, max_chars: int = 220) -> str:
    if isinstance(value, dict):
        parts = []
        for key in (
            "id",
            "title",
            "goal",
            "area",
            "status",
            "player_impact",
            "recommendation",
        ):
            text = " ".join(str(value.get(key) or "").split())
            if text and text not in parts:
                parts.append(text)
        result = ": ".join(parts[:3])
    else:
        result = " ".join(str(value or "").split())
    if len(result) <= max_chars:
        return result
    return result[: max_chars - 1].rstrip() + "…"


def build_project_planner_evidence_packet(
    *,
    public_execution_snapshot: dict[str, Any],
    issues: list[dict[str, Any]],
    qa_tester_evidence: dict[str, Any] | None,
    evidence_history: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Return bounded, actionable public evidence for the planning call.

    Lossless evidence remains in Runtime artifacts and the constrained scaffold.
    Repeating entire QA reports and the full history here makes later planning
    calls attend to old prose instead of current product gaps.
    """

    compact_issues = []
    for issue in issues[:8]:
        if not isinstance(issue, dict):
            continue
        compact_issues.append(
            {
                key: _compact_history_item(issue.get(key), max_chars=240)
                for key in ("id", "severity", "title", "recommendation")
                if issue.get(key)
            }
        )
    qa = qa_tester_evidence if isinstance(qa_tester_evidence, dict) else {}
    compact_qa: dict[str, Any] = {}
    for key, limit in (
        ("remaining_bugs", 4),
        ("evidence_gaps", 4),
        ("next_loop_goals", 3),
        ("preserve", 3),
    ):
        values = qa.get(key)
        if isinstance(values, list) and values:
            summaries = []
            for value in values[:limit]:
                summary = _compact_history_item(value, max_chars=240)
                if summary:
                    summaries.append(summary)
            compact_qa[key] = summaries
    status = qa.get("status") or qa.get("review_status")
    if status:
        compact_qa["status"] = _compact_history_item(status, max_chars=80)
    return {
        "public_execution_snapshot": public_execution_snapshot,
        "current_open_issues": compact_issues,
        "latest_qa_summary": compact_qa,
        "prior_completed_loops": [
            entry.get("source_loop")
            for entry in (evidence_history or [])[-3:]
            if isinstance(entry, dict) and entry.get("source_loop") is not None
        ],
        "lossless_artifacts": [
            "issues.json",
            "evidence_history.json",
            "development_brief.md",
        ],
    }


def build_development_brief(
    *,
    loop_index: int,
    public_execution_snapshot: dict[str, Any],
    issues: list[dict[str, Any]],
    verified_demo_claims: list[dict[str, Any]] | None = None,
) -> str:
    evidence_gap_issues = [
        issue for issue in issues if issue.get("source") == "demo_evidence_gap"
    ]
    evidence_gap_section = ""
    if evidence_gap_issues:
        evidence_gap_section = join_markdown_blocks(
            [
                "## Demo Evidence Gaps From Previous Loop",
                format_issue_items(
                    evidence_gap_issues,
                    action_label="Required next action",
                ),
            ]
        )
    preserve_section = ""
    if verified_demo_claims:
        preserve_section = join_markdown_blocks(
            [
                "## Preserve Verified Demo Evidence",
                "Do not remove or weaken these previously verified public demo signals while fixing new gaps:",
                format_verified_claim_items(verified_demo_claims),
            ]
        )
    return render_markdown_template(
        DEVELOPMENT_BRIEF_TEMPLATE,
        {
            "loop_index": loop_index,
            "build_ok": public_execution_snapshot.get("build_ok"),
            "num_demos": public_execution_snapshot.get("num_demos"),
            "evidence_gap_section": evidence_gap_section,
            "preserve_section": preserve_section,
            "issue_items": format_issue_items(issues, action_label="Recommendation"),
        },
    )


def build_development_doc_delta(
    *,
    loop_index: int,
    issues: list[dict[str, Any]],
    verified_demo_claims: list[dict[str, Any]] | None = None,
) -> str:
    previous_name = development_doc_filename(loop_index - 1) if loop_index > 1 else "public task instruction"
    current_name = development_doc_filename(loop_index)
    preserve_section = ""
    if verified_demo_claims:
        preserve_section = join_markdown_blocks(
            [
                "## Preserve From Previous Document",
                format_verified_claim_items(verified_demo_claims),
            ]
        )
    return render_markdown_template(
        DEVELOPMENT_DOC_DELTA_TEMPLATE,
        {
            "loop_index": loop_index,
            "previous_name": previous_name,
            "current_name": current_name,
            "target_items": format_issue_items(
                issues,
                action_label="Developer-facing change",
            ),
            "preserve_section": preserve_section,
        },
    )


def build_development_document(
    *,
    loop_index: int,
    public_execution_snapshot: dict[str, Any],
    issues: list[dict[str, Any]],
    development_brief: str,
    verified_demo_claims: list[dict[str, Any]] | None = None,
    evidence_history: list[dict[str, Any]] | None = None,
    public_task_instruction: str = "",
    method_name: str = "GameLoop",
    task_source_name: str = "Benchmark",
) -> str:
    version = f"v{loop_index:03d}"
    planning_inputs = (
        f"the public {task_source_name} instruction plus previous public execution "
        "and QA evidence"
        if loop_index > 1
        else f"the public {task_source_name} instruction only"
    )
    no_gap_iteration = bool(issues) and all(
        issue.get("id") == f"{loop_tag(loop_index)}-public-playtest"
        for issue in issues
    )
    no_gap_section = ""
    if no_gap_iteration:
        no_gap_section = join_markdown_blocks(
            [
                "## No-Gap Iteration Target",
                "The previous tester matrix did not report an open evidence gap. Treat this",
                "loop as a portfolio pass, not a rewrite.",
                "",
                "- Preserve the current playable foundation and demo purposes.",
                "- Add one deeper mechanics/content/difficulty/presentation improvement from",
                "  the public task brief.",
                "- Update or add replay proof so the improvement is visible live with input,",
                "  state change, consequence, feedback, and result dwell.",
                "- Do not add complexity that makes the prior core loop, breadth trace,",
                "  pressure trace, or result trace harder to read.",
            ]
        )
    preserve_visible_section = ""
    if verified_demo_claims:
        preserve_visible_section = join_markdown_blocks(
            [
                "## Preserve Visible Working Evidence",
                "Do not remove or weaken these already-visible signals while repairing new gaps:",
                format_verified_claim_items(verified_demo_claims),
            ]
        )
    public_task_text = (
        public_task_instruction.strip()
        or (
            "No public task instruction text was available to copy into this document. "
            "Use the original task prompt as the source of truth."
        )
    )
    return render_markdown_template(
        DEVELOPMENT_DOCUMENT_TEMPLATE,
        {
            "method_name": method_name,
            "task_source_name": task_source_name,
            "version": version,
            "development_doc_filename": development_doc_filename(loop_index),
            "planning_inputs": planning_inputs,
            "build_ok": public_execution_snapshot.get("build_ok"),
            "num_demos": public_execution_snapshot.get("num_demos"),
            "public_task_instruction": public_task_text,
            "focus_items": format_issue_items(
                issues,
                action_label="Required development action",
            ),
            "no_gap_section": no_gap_section,
            "preserve_visible_section": preserve_visible_section,
            "development_brief": development_brief.rstrip(),
            "evidence_history_section": format_evidence_history(evidence_history),
        },
    )


def build_project_planner_prompt(
    *,
    loop_index: int,
    public_task_instruction: str,
    evidence_packet: dict[str, Any] | None,
    scaffold_document: str,
    final_iteration: bool = False,
    method_name: str = "GameLoop",
    task_source_name: str = "Benchmark",
) -> str:
    version = f"v{loop_index:03d}"
    evidence_text = (
        "No previous-iteration evidence is available. Plan the first development "
        "pass from the public specification alone."
        if loop_index == 1 or not evidence_packet
        else "```json\n"
        + json.dumps(evidence_packet, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n```"
    )
    iteration_policy = (
        "This is the final available development iteration. Compare every prominent "
        "publicly named mechanic, content family, progression/result state, visual "
        "surface, and replay promise against the supplied evidence. Do not treat one "
        "new feature as completion while other high-impact public requirements remain "
        "absent. Choose the one or two largest feasible completeness gaps plus any "
        "replay/presentation work needed to make them visible. Nothing may be deferred "
        "to a later loop."
        if final_iteration
        else (
            "This is an intermediate iteration. Repair concrete regressions first, "
            "then choose the highest-impact feasible public-task depth improvement "
            "while preserving a strong path for the next loop."
        )
    )
    return render_markdown_template(
        PROJECT_PLANNER_PROMPT_TEMPLATE,
        {
            "loop_index": loop_index,
            "method_name": method_name,
            "task_source_name": task_source_name,
            "version": version,
            "public_task_instruction": public_task_instruction.strip(),
            "evidence_packet": evidence_text,
            "iteration_policy": iteration_policy,
            "scaffold_document": scaffold_document.rstrip(),
        },
    )


def build_loop_artifacts(
    *,
    loop_index: int,
    previous_best: dict[str, Any] | None,
    previous_demo_evidence: dict[str, Any] | None = None,
    evidence_history: list[dict[str, Any]] | None = None,
    public_task_instruction: str = "",
    method_name: str = "GameLoop",
    task_source_name: str = "Benchmark",
) -> dict[str, Any]:
    public_execution_snapshot = build_public_execution_snapshot(previous_best)
    verified_demo_claims = build_verified_demo_claims(previous_demo_evidence)
    issues = build_loop_issues(
        loop_index=loop_index,
        public_execution_snapshot=public_execution_snapshot,
        previous_best=previous_best,
        previous_demo_evidence=previous_demo_evidence,
    )
    loop_memory = build_loop_memory(
        loop_index=loop_index,
        public_execution=public_execution_snapshot,
        issues=issues,
        verified_demo_claims=verified_demo_claims,
    )
    loop_memory["prior_public_evidence"] = list(evidence_history or [])
    development_brief = build_development_brief(
        loop_index=loop_index,
        public_execution_snapshot=public_execution_snapshot,
        issues=issues,
        verified_demo_claims=verified_demo_claims,
    )
    development_document = build_development_document(
        loop_index=loop_index,
        public_execution_snapshot=public_execution_snapshot,
        issues=issues,
        development_brief=development_brief,
        verified_demo_claims=verified_demo_claims,
        evidence_history=evidence_history,
        public_task_instruction=public_task_instruction,
        method_name=method_name,
        task_source_name=task_source_name,
    )
    return {
        "public_execution_snapshot": public_execution_snapshot,
        "issues": issues,
        "loop_memory": loop_memory,
        "demo_evidence_matrix": build_demo_evidence_matrix(loop_index=loop_index),
        "development_brief": development_brief,
        "development_document": development_document,
        "development_doc_delta": build_development_doc_delta(
            loop_index=loop_index,
            issues=issues,
            verified_demo_claims=verified_demo_claims,
        ),
        "development_doc_filename": development_doc_filename(loop_index),
        "evidence_history": list(evidence_history or []),
    }


def write_loop_artifacts(loop_dir: Path, artifacts: dict[str, Any]) -> None:
    loop_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        loop_dir / "public_execution_snapshot.json",
        artifacts["public_execution_snapshot"],
    )
    write_json(loop_dir / "issues.json", artifacts["issues"])
    write_json(loop_dir / "loop_memory.json", artifacts["loop_memory"])
    write_json(loop_dir / "evidence_history.json", artifacts["evidence_history"])
    write_json(loop_dir / "demo_evidence_matrix.json", artifacts["demo_evidence_matrix"])
    (loop_dir / artifacts["development_doc_filename"]).write_text(
        artifacts["development_document"],
        encoding="utf-8",
    )
    (loop_dir / "development_doc_delta.md").write_text(
        artifacts["development_doc_delta"],
        encoding="utf-8",
    )
    (loop_dir / "developer_extra_instruction.md").write_text(
        artifacts["development_document"],
        encoding="utf-8",
    )
    for name in ("development_brief.md", "next_loop_input.md"):
        (loop_dir / name).write_text(artifacts["development_brief"], encoding="utf-8")
