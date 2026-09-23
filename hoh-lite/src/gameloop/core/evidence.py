"""Evidence model defaults for iterative game-development loops."""

from __future__ import annotations

from typing import Any

from gameloop.core.stages import loop_tag


GAMEPLAY_REVIEW_DIMENSIONS = [
    "gameplay_mechanics",
    "content_depth",
    "difficulty_progression",
    "visual_effects_feedback",
    "asset_use_visual_production",
    "replay_visible_quality",
]

DEMO_EVIDENCE_PROMISES = [
    "core_verbs_and_controls",
    "mechanic_interactions",
    "progression_or_content_depth",
    "difficulty_escalation",
    "failure_restart_recovery",
    "win_or_result_state",
    "ui_hud_feedback",
    "asset_animation_effects",
    "visible_core_asset_use",
    "full_loop_start_play_result_restart",
    "task_specific_result_stats",
]

PASSLIKE_EVIDENCE_STATUSES = {
    "pass",
    "passed",
    "verified",
    "ok",
    "present",
    "present with generated content",
    "complete",
    "completed",
    "done",
}


def _slugify(value: str) -> str:
    clean = []
    for char in value:
        if char.isalnum() or char in {"-", "_"}:
            clean.append(char)
        elif char in {"/", "\\", ".", " "}:
            clean.append("-")
    slug = "".join(clean).strip("-")
    return slug or "gameloop-item"


def _public_execution(public_execution_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluated": public_execution_snapshot.get("evaluated"),
        "build_ok": public_execution_snapshot.get("build_ok"),
        "num_demos": public_execution_snapshot.get("num_demos"),
        "errors": list(public_execution_snapshot.get("errors") or []),
    }


def build_public_execution_snapshot(
    previous_best: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = (previous_best or {}).get("breakdown_summary") or {}
    has_evaluation = (
        bool((previous_best or {}).get("evaluated"))
        or summary.get("reward") is not None
        or (previous_best or {}).get("reward") is not None
    )
    return {
        "schema_version": 1,
        "source": "public_execution_snapshot",
        "evaluated": has_evaluation,
        "build_ok": summary.get("build_ok"),
        "num_demos": summary.get("num_demos"),
        "errors": list(summary.get("errors") or []),
        "trial_name": (previous_best or {}).get("trial_name"),
    }


def feedback_text(previous: dict[str, Any] | None) -> str:
    if not previous:
        return ""
    summary = previous.get("breakdown_summary") or {}
    if not summary:
        return ""
    lines = [
        "## Previous attempt feedback",
        "",
        f"- Build ok: {summary.get('build_ok')}",
        f"- Demo count observed: {summary.get('num_demos')}",
    ]
    errors = summary.get("errors") or []
    if errors:
        lines.append("- Public execution errors:")
        for err in errors:
            lines.append(f"  - {err}")
    return "\n".join(lines) + "\n"


def build_demo_evidence_gap_issues(
    *,
    loop_index: int,
    previous_demo_evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(previous_demo_evidence, dict):
        return []

    gap_items = previous_demo_evidence.get("remaining_bugs")
    if not isinstance(gap_items, list) or not gap_items:
        gap_items = previous_demo_evidence.get("evidence_gaps")
    if not isinstance(gap_items, list):
        gap_items = []

    issues: list[dict[str, Any]] = []
    allowed_severities = {"blocker", "high", "medium", "low"}
    resolved_statuses = {"pass", "resolved", "closed"}
    for index, gap in enumerate(gap_items, start=1):
        if isinstance(gap, str):
            gap = {"title": gap.strip()}
        if not isinstance(gap, dict):
            continue
        status = str(gap.get("status") or "").strip().lower()
        if status in resolved_statuses:
            continue
        raw_claim = str(gap.get("claim_id") or gap.get("id") or f"gap-{index}")
        claim_slug = _slugify(raw_claim)
        severity = str(gap.get("severity") or "high").strip().lower()
        if severity not in allowed_severities:
            severity = "high"
        missing = str(
            gap.get("missing_evidence")
            or gap.get("gap")
            or gap.get("title")
            or gap.get("player_impact")
            or "A required gameplay promise is not visible in replay evidence."
        )
        impact = str(gap.get("impact") or gap.get("player_impact") or "").strip()
        evidence = gap.get("evidence") or gap.get("observable_evidence")
        recommendation = str(
            gap.get("recommended_change")
            or gap.get("recommendation")
            or "Update the scenario or deterministic trace so the missing gameplay is visible."
        )
        issues.append(
            {
                "id": f"{loop_tag(loop_index)}-evidence-{claim_slug}",
                "source": "demo_evidence_gap",
                "severity": severity,
                "title": missing,
                "impact": impact,
                "evidence": evidence,
                "recommendation": recommendation,
                "claim_id": raw_claim,
            }
        )

    goal_items = previous_demo_evidence.get("next_loop_goals")
    if isinstance(goal_items, list):
        for index, goal in enumerate(goal_items, start=1):
            if isinstance(goal, dict):
                goal_text = str(
                    goal.get("goal") or goal.get("title") or goal.get("id") or ""
                ).strip()
                recommendation = str(
                    goal.get("recommendation")
                    or goal.get("recommended_change")
                    or "Implement and demonstrate this tester-prioritized product upgrade."
                ).strip()
                evidence = goal.get("evidence") or goal.get("observable_evidence")
                impact = goal.get("impact") or goal.get("player_impact")
            else:
                goal_text = str(goal).strip()
                recommendation = (
                    "Implement and demonstrate this tester-prioritized product upgrade."
                )
                evidence = None
                impact = None
            if not goal_text:
                continue
            goal_slug = _slugify(goal_text)
            issues.append(
                {
                    "id": f"{loop_tag(loop_index)}-tester-goal-{goal_slug}",
                    "source": "tester_next_loop_goal",
                    "severity": "high",
                    "title": f"Tester next-loop goal: {goal_text}",
                    "impact": impact,
                    "evidence": evidence,
                    "recommendation": recommendation,
                    "claim_id": goal_text,
                }
            )
    return issues


def build_loop_issues(
    *,
    loop_index: int,
    public_execution_snapshot: dict[str, Any],
    previous_best: dict[str, Any] | None,
    previous_demo_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    issues = build_demo_evidence_gap_issues(
        loop_index=loop_index,
        previous_demo_evidence=previous_demo_evidence,
    )
    if not previous_best:
        issues.append(
            {
                "id": f"{loop_tag(loop_index)}-mvp",
                "source": "initial_prd",
                "severity": "high",
                "title": "Produce a playable MVP before broad polish expansion",
                "recommendation": (
                    "Implement a launchable game project with deterministic replay "
                    "traces that demonstrate the public task's core loop."
                ),
            }
        )
        return issues

    if public_execution_snapshot.get("build_ok") is False:
        issues.append(
            {
                "id": f"{loop_tag(loop_index)}-build",
                "source": "public_execution_snapshot",
                "severity": "blocker",
                "title": "Previous candidate did not pass build or launch verification",
                "recommendation": "Prioritize launchability and replay validity first.",
            }
        )
    if not public_execution_snapshot.get("evaluated"):
        issues.append(
            {
                "id": f"{loop_tag(loop_index)}-unevaluated",
                "source": "public_execution_snapshot",
                "severity": "blocker",
                "title": "Previous candidate did not complete external evaluation",
                "recommendation": "Fix the failure that prevented evaluation before adding features.",
            }
        )
    if not public_execution_snapshot.get("num_demos"):
        issues.append(
            {
                "id": f"{loop_tag(loop_index)}-demos",
                "source": "public_execution_snapshot",
                "severity": "high",
                "title": "No replay demos were observed",
                "recommendation": "Add deterministic replay traces for the core loop.",
            }
        )
    for index, err in enumerate(public_execution_snapshot.get("errors") or [], start=1):
        issues.append(
            {
                "id": f"{loop_tag(loop_index)}-public-error-{index}",
                "source": "public_execution_snapshot",
                "severity": "medium",
                "title": "Public execution surfaced an observable runtime error",
                "evidence": str(err),
                "recommendation": "Repair the observable runtime or replay issue.",
            }
        )
    if not issues:
        issues.append(
            {
                "id": f"{loop_tag(loop_index)}-public-playtest",
                "source": "public_execution_snapshot",
                "severity": "medium",
                "title": "Improve visible MVP quality from public evidence",
                "recommendation": (
                    "Use the PRD, generated game, replay traces, screenshots, and "
                    "role reports to choose the next highest-impact public fix."
                ),
            }
        )
    return issues


def _demo_ids_from_evidence(item: dict[str, Any]) -> list[str]:
    raw_values: list[Any] = []
    for key in ("demo_ids", "demos", "demo_id", "visible_in_demos", "visible_in_demo"):
        value = item.get(key)
        if value:
            raw_values.append(value)

    demo_ids: list[str] = []
    for value in raw_values:
        values = value if isinstance(value, list) else str(value).split(",")
        for part in values:
            if isinstance(part, dict):
                part = part.get("id") or part.get("demo_id") or part.get("name")
            text = str(part or "").strip()
            if text and text not in demo_ids:
                demo_ids.append(text)
    return demo_ids


def _brief_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def build_verified_demo_claims(
    previous_demo_evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(previous_demo_evidence, dict):
        return []

    claims: list[dict[str, Any]] = []

    def add_claim(item: dict[str, Any], *, source: str, fallback_id: str) -> None:
        claim_id = str(
            item.get("claim_id")
            or item.get("id")
            or item.get("claim")
            or item.get("entity")
            or fallback_id
        )
        evidence = _brief_text(
            item.get("evidence")
            or item.get("observable_evidence")
            or item.get("player_impact")
            or item.get("entity")
            or "Previously verified in public demo evidence."
        )
        if not claim_id or not evidence:
            return
        claims.append(
            {
                "claim_id": claim_id,
                "source": source,
                "evidence": evidence,
                "demo_ids": _demo_ids_from_evidence(item),
            }
        )

    for key, source in (
        ("claim_reviews", "claim_reviews"),
        ("asset_visibility_checks", "asset_visibility_checks"),
    ):
        items = previous_demo_evidence.get(key)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status in PASSLIKE_EVIDENCE_STATUSES:
                add_claim(item, source=source, fallback_id=f"{source}-{index}")

    demo_items = previous_demo_evidence.get("demos")
    if isinstance(demo_items, list):
        for index, item in enumerate(demo_items, start=1):
            if not isinstance(item, dict):
                continue
            demo_id = str(item.get("id") or item.get("demo_id") or f"demo-{index}").strip()
            if not demo_id:
                continue
            visible = item.get("visible_evidence")
            visible_parts: list[str] = []
            if isinstance(visible, list):
                visible_parts = [str(part).strip() for part in visible if str(part).strip()]
            elif visible:
                visible_parts = [str(visible).strip()]
            assessment = str(item.get("assessment") or "").strip()
            if not visible_parts and not assessment:
                continue
            evidence = "; ".join(visible_parts)
            if assessment:
                evidence = f"{evidence}. {assessment}" if evidence else assessment
            copied = dict(item)
            copied["claim_id"] = f"demo:{demo_id}"
            copied["demo_ids"] = [demo_id]
            copied["evidence"] = evidence
            add_claim(copied, source="demo_portfolio", fallback_id=f"demo-{index}")

    asset_items = previous_demo_evidence.get("asset_evidence")
    if isinstance(asset_items, list):
        for index, item in enumerate(asset_items, start=1):
            if not isinstance(item, dict):
                continue
            entity = item.get("entity") or item.get("project_path") or f"asset-{index}"
            project_path = item.get("project_path")
            source_path = item.get("source_path")
            evidence = f"{entity} uses {project_path or 'a visible asset'}"
            if source_path:
                evidence += f" from {source_path}"
            copied = dict(item)
            copied["claim_id"] = f"asset:{entity}"
            copied["evidence"] = evidence
            add_claim(copied, source="asset_evidence", fallback_id=f"asset-{index}")

    preserve_items = previous_demo_evidence.get("preserve")
    if isinstance(preserve_items, list):
        for index, item in enumerate(preserve_items, start=1):
            if isinstance(item, dict):
                copied = dict(item)
                copied.setdefault("claim_id", f"tester-preserve-{index}")
                add_claim(
                    copied,
                    source="tester_preserve",
                    fallback_id=f"tester-preserve-{index}",
                )
            elif str(item).strip():
                add_claim(
                    {
                        "claim_id": f"tester-preserve-{index}",
                        "evidence": str(item).strip(),
                    },
                    source="tester_preserve",
                    fallback_id=f"tester-preserve-{index}",
                )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        key = (claim["source"], claim["claim_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def build_loop_memory(
    *,
    loop_index: int,
    public_execution: dict[str, Any] | None = None,
    public_execution_snapshot: dict[str, Any] | None = None,
    issues: list[dict[str, Any]],
    verified_demo_claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    execution = public_execution if public_execution is not None else public_execution_snapshot or {}
    return {
        "schema_version": 1,
        "loop_index": loop_index,
        "source": "clean_loop_memory",
        "public_execution": _public_execution(execution),
        "prd_claims": [],
        "implemented_claims": [],
        "verified_demo_claims": list(verified_demo_claims or []),
        "open_issues": [
            {
                "id": issue.get("id"),
                "source": issue.get("source"),
                "severity": issue.get("severity"),
                "title": issue.get("title"),
                "impact": issue.get("impact"),
                "evidence": issue.get("evidence"),
                "recommendation": issue.get("recommendation"),
                "claim_id": issue.get("claim_id"),
            }
            for issue in issues
        ],
        "next_loop_targets": [
            {
                "issue_id": issue.get("id"),
                "target": issue.get("recommendation"),
            }
            for issue in issues
        ],
    }


def build_demo_evidence_matrix(*, loop_index: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "loop_index": loop_index,
        "source": "tester_demo_evidence_review",
        "review_status": "pending",
        "required_review_dimensions": GAMEPLAY_REVIEW_DIMENSIONS,
        "required_demo_promises": DEMO_EVIDENCE_PROMISES,
        "asset_manifest": [],
        "asset_visibility_checks": [
            {
                "claim_id": "visible_asset_use",
                "status": "pending",
                "required_evidence": (
                    "Core gameplay entities use imported or authored visual assets "
                    "and those assets are visible in shipped replay demos."
                ),
                "core_entities": [
                    "player",
                    "terrain/platforms",
                    "collectibles/items",
                    "hazards",
                    "gates/results",
                    "environment/background layer",
                ],
            }
        ],
        "demos": [],
        "claim_reviews": [],
        "evidence_gaps": [],
        "instructions": (
            "Tester should fill this matrix from public PRD text, replay media, "
            "screenshots, and observable gameplay evidence. Do not use numeric "
            "evaluation outputs, hidden tests, private formulas, hidden requirement "
            "IDs, or private evaluator rationales. Asset checks must be based on what is visible in replay "
            "media, not merely on files copied into the project."
        ),
    }
