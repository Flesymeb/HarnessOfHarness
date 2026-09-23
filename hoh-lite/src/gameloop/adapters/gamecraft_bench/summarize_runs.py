#!/usr/bin/env python3
"""Summarize HoH-lite run summaries without private evaluator context."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Iterable

from .paths import RUNS_ROOT


def _observation_totals(observations: Iterable[dict[str, Any]]) -> dict[str, int]:
    totals = {"calls": 0, "images": 0, "debug_cycles": 0}
    seen_roots: set[str] = set()
    for observation in observations:
        root = str(observation.get("root") or "")
        if root and root in seen_roots:
            continue
        if root:
            seen_roots.add(root)
        totals["calls"] += int(observation.get("call_count", 0) or 0)
        totals["images"] += int(observation.get("image_count", 0) or 0)
        totals["debug_cycles"] += int(
            observation.get("debug_cycle_count", 0) or 0
        )
    return totals


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _attempt_protocol_error(attempt: dict[str, Any]) -> dict[str, Any]:
    explicit = _mapping(attempt.get("trial_error"))
    if explicit:
        return explicit
    final_evaluation = _mapping(attempt.get("final_evaluation"))
    if final_evaluation.get("status") == "failed":
        return {
            "type": "verifier_infrastructure_failure",
            "inferred_from_legacy_stage_status": True,
        }
    visual_tester = _mapping(attempt.get("visual_tester"))
    tester_status = str(visual_tester.get("status") or "")
    if tester_status in {
        "infrastructure_failed",
        "failed",
        "invalid_mcp_coverage",
        "invalid_report",
        "invalid_candidate_mutation",
    } or int(visual_tester.get("returncode", 0) or 0) != 0:
        return {
            "type": "tester_infrastructure_failure",
            "inferred_from_legacy_stage_status": True,
            "stage_status": tester_status or None,
        }
    return {}


def _correct_shared_tester_observations(
    developer: list[dict[str, Any]],
    tester: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Remove Developer receipts from legacy cumulative Tester snapshots.

    Early MCP runs could point the outer Tester at the same evidence root as
    the primary Developer. The Tester snapshot was then cumulative, while the
    already-recorded Developer snapshot remained a clean prefix. Subtract that
    prefix for reporting only; raw artifacts remain untouched.
    """

    by_root = {
        str(item.get("root")): item
        for item in developer
        if str(item.get("root") or "")
    }
    corrected = []
    warnings: list[str] = []
    for observation in tester:
        root = str(observation.get("root") or "")
        developer_prefix = by_root.get(root)
        if developer_prefix is None:
            corrected.append(observation)
            continue
        counter_keys = ("call_count", "image_count", "debug_cycle_count")
        if any(
            int(observation.get(key, 0) or 0)
            < int(developer_prefix.get(key, 0) or 0)
            for key in counter_keys
        ):
            corrected.append(observation)
            marker = "shared_developer_tester_mcp_root_not_cumulative"
            if marker not in warnings:
                warnings.append(marker)
            continue
        item = dict(observation)
        for output_key, source_key in (
            ("call_count", "call_count"),
            ("image_count", "image_count"),
            ("debug_cycle_count", "debug_cycle_count"),
        ):
            item[output_key] = max(
                0,
                int(observation.get(source_key, 0) or 0)
                - int(developer_prefix.get(source_key, 0) or 0),
            )
        corrected.append(item)
        marker = "legacy_shared_developer_tester_mcp_root_corrected"
        if marker not in warnings:
            warnings.append(marker)
    return corrected, warnings


def _attempt_mcp_totals(
    attempt: dict[str, Any],
) -> tuple[dict[str, dict[str, int]], list[str]]:
    developer = [_mapping(attempt.get("developer_mcp"))]
    tester = []
    for key in ("inner_acceptance", "visual_tester"):
        phase = _mapping(attempt.get(key))
        tester.append(_mapping(phase.get("mcp_observation")))
    for repair_value in attempt.get("inner_repairs") or []:
        repair = _mapping(repair_value)
        developer.append(_mapping(repair.get("developer_mcp")))
        acceptance = _mapping(repair.get("inner_acceptance"))
        tester.append(_mapping(acceptance.get("mcp_observation")))
    developer = [item for item in developer if item]
    tester = [item for item in tester if item]
    tester, warnings = _correct_shared_tester_observations(developer, tester)
    return {
        "developer": _observation_totals(item for item in developer if item),
        "tester": _observation_totals(item for item in tester if item),
    }, warnings


def summarize_run(data: dict[str, Any]) -> dict[str, Any]:
    attempts = [item for item in data.get("attempts") or [] if isinstance(item, dict)]
    loops = []
    developer_totals = {"calls": 0, "images": 0, "debug_cycles": 0}
    tester_totals = {"calls": 0, "images": 0, "debug_cycles": 0}
    warnings: list[str] = []
    provenance_warnings: list[str] = []
    for attempt in attempts:
        error = _attempt_protocol_error(attempt)
        valid = attempt.get("trial_valid") is True and not error
        reward = attempt.get("reported_reward") if valid else None
        loops.append(
            {
                "loop": attempt.get("attempt"),
                "valid": valid,
                "reward": reward,
                "error_type": error.get("type"),
            }
        )
        mcp, attempt_provenance_warnings = _attempt_mcp_totals(attempt)
        for role, totals in (("developer", developer_totals), ("tester", tester_totals)):
            for key in totals:
                totals[key] += mcp[role][key]
        for warning in attempt.get("developer_mcp_warnings") or []:
            text = str(warning)
            if text not in warnings:
                warnings.append(text)
        for warning in attempt_provenance_warnings:
            if warning not in provenance_warnings:
                provenance_warnings.append(warning)

    first_reward = loops[0]["reward"] if loops else None
    last_reward = loops[-1]["reward"] if loops else None
    comparable_delta = (
        float(last_reward) - float(first_reward)
        if (
            len(loops) >= 2
            and first_reward is not None
            and last_reward is not None
        )
        else None
    )
    valid_rewards = [item["reward"] for item in loops if item["reward"] is not None]
    return {
        "run_id": data.get("run_id"),
        "task": data.get("task"),
        "model": data.get("model"),
        "loops": loops,
        "attempt_count": len(loops),
        "valid_attempt_count": sum(item["valid"] for item in loops),
        "invalid_attempt_count": sum(not item["valid"] for item in loops),
        "final_attempt_valid": loops[-1]["valid"] if loops else None,
        "latest_valid_reward": valid_rewards[-1] if valid_rewards else None,
        "first_to_last_delta": comparable_delta,
        "developer_mcp": developer_totals,
        "tester_mcp": tester_totals,
        "developer_mcp_warnings": warnings,
        "mcp_provenance_warnings": provenance_warnings,
    }


def collect_run_summaries(
    runs_dir: Path,
    *,
    run_ids: set[str] | None = None,
    prefixes: tuple[str, ...] = (),
    tasks: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    if not runs_dir.is_dir():
        return rows
    for path in sorted(runs_dir.glob("*/summary.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read run summary {path}: {error}") from error
        if not isinstance(data, dict):
            raise ValueError(f"run summary {path} must contain a JSON object")
        run_id = str(data.get("run_id") or path.parent.name)
        task = str(data.get("task") or "")
        if run_ids and run_id not in run_ids:
            continue
        if prefixes and not any(run_id.startswith(prefix) for prefix in prefixes):
            continue
        if tasks and task not in tasks and Path(task).name not in tasks:
            continue
        rows.append(summarize_run(data))
    return rows


def summarize_suite(
    rows: list[dict[str, Any]],
    *,
    expected_loops: tuple[int, ...] = (1, 2, 3),
) -> dict[str, Any]:
    """Aggregate only explicitly selected rows without resolving duplicates.

    A duplicate task/loop is ambiguous: it can represent a retry, a restart, or
    an attempted best-of-N selection.  Refusing it keeps suite composition an
    explicit caller decision instead of silently choosing a score.
    """

    observations: dict[tuple[str, int], dict[str, Any]] = {}
    tasks: set[str] = set()
    developer_totals = {"calls": 0, "images": 0, "debug_cycles": 0}
    tester_totals = {"calls": 0, "images": 0, "debug_cycles": 0}
    for row in rows:
        task = str(row.get("task") or "")
        if not task:
            raise ValueError("cannot aggregate a run without a task")
        tasks.add(task)
        for role, totals in (
            ("developer_mcp", developer_totals),
            ("tester_mcp", tester_totals),
        ):
            source = _mapping(row.get(role))
            for key in totals:
                totals[key] += int(source.get(key, 0) or 0)
        for item in row.get("loops") or []:
            loop = item.get("loop")
            if not isinstance(loop, int):
                raise ValueError(f"cannot aggregate non-integer loop for {task}")
            key = (task, loop)
            if key in observations:
                raise ValueError(
                    f"duplicate task/loop in selected runs: {task} loop {loop}"
                )
            observations[key] = item

    loop_stats = []
    for loop in expected_loops:
        items = [
            item
            for (task, item_loop), item in observations.items()
            if item_loop == loop
        ]
        scores = [
            float(item["reward"])
            for item in items
            if item.get("valid") is True and item.get("reward") is not None
        ]
        loop_stats.append(
            {
                "loop": loop,
                "observed_task_count": len(items),
                "valid_scored_count": len(scores),
                "valid_unscored_count": sum(
                    item.get("valid") is True and item.get("reward") is None
                    for item in items
                ),
                "invalid_count": sum(item.get("valid") is not True for item in items),
                "missing_task_count": len(tasks) - len(items),
                "mean_reward": statistics.fmean(scores) if scores else None,
                "median_reward": statistics.median(scores) if scores else None,
            }
        )

    paired_tasks = sorted(
        task
        for task in tasks
        if all(
            (item := observations.get((task, loop))) is not None
            and item.get("valid") is True
            and item.get("reward") is not None
            for loop in expected_loops
        )
    )
    paired_means = {
        str(loop): (
            statistics.fmean(
                float(observations[(task, loop)]["reward"])
                for task in paired_tasks
            )
            if paired_tasks
            else None
        )
        for loop in expected_loops
    }
    first_loop = expected_loops[0] if expected_loops else None
    last_loop = expected_loops[-1] if expected_loops else None
    paired_delta = None
    if paired_tasks and first_loop is not None and last_loop is not None:
        paired_delta = statistics.fmean(
            float(observations[(task, last_loop)]["reward"])
            - float(observations[(task, first_loop)]["reward"])
            for task in paired_tasks
        )

    return {
        "run_count": len(rows),
        "task_count": len(tasks),
        "expected_loops": list(expected_loops),
        "loop_stats": loop_stats,
        "fully_paired_task_count": len(paired_tasks),
        "fully_paired_tasks": paired_tasks,
        "paired_loop_mean_rewards": paired_means,
        "paired_first_to_last_mean_delta": paired_delta,
        "developer_mcp": developer_totals,
        "tester_mcp": tester_totals,
    }


def _score(value: Any) -> str:
    return "—" if value is None else f"{float(value):.6f}"


def _loop_text(loops: list[dict[str, Any]]) -> str:
    values = []
    for item in loops:
        label = f"L{item.get('loop')}"
        if item.get("valid") and item.get("reward") is not None:
            value = _score(item["reward"])
        elif item.get("valid"):
            value = "unscored"
        else:
            value = f"invalid:{item.get('error_type') or 'unknown'}"
        values.append(f"{label}={value}")
    return "; ".join(values) or "—"


def format_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Run | Task | Raw loop results | Δ first→last | Valid/invalid | Developer MCP c/i/d | Tester MCP c/i/d |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        developer = row["developer_mcp"]
        tester = row["tester_mcp"]
        lines.append(
            "| `{run}` | `{task}` | {loops} | {delta} | {valid}/{invalid} | {dc}/{di}/{dd} | {tc}/{ti}/{td} |".format(
                run=row.get("run_id") or "",
                task=row.get("task") or "",
                loops=_loop_text(row["loops"]),
                delta=_score(row.get("first_to_last_delta")),
                valid=row["valid_attempt_count"],
                invalid=row["invalid_attempt_count"],
                dc=developer["calls"],
                di=developer["images"],
                dd=developer["debug_cycles"],
                tc=tester["calls"],
                ti=tester["images"],
                td=tester["debug_cycles"],
            )
        )
    provenance = [
        (str(row.get("run_id") or ""), str(warning))
        for row in rows
        for warning in row.get("mcp_provenance_warnings") or []
    ]
    if provenance:
        lines.extend(["", "MCP provenance warnings:"])
        lines.extend(f"- `{run_id}`: {warning}" for run_id, warning in provenance)
    return "\n".join(lines) + "\n"


def format_suite_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "## Aggregate",
        "",
        "| Loop | Observed tasks | Valid scored | Valid unscored | Invalid | Missing | Mean | Median |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["loop_stats"]:
        lines.append(
            "| L{loop} | {observed} | {scored} | {unscored} | {invalid} | {missing} | {mean} | {median} |".format(
                loop=item["loop"],
                observed=item["observed_task_count"],
                scored=item["valid_scored_count"],
                unscored=item["valid_unscored_count"],
                invalid=item["invalid_count"],
                missing=item["missing_task_count"],
                mean=_score(item["mean_reward"]),
                median=_score(item["median_reward"]),
            )
        )
    paired = summary["fully_paired_task_count"]
    means = summary["paired_loop_mean_rewards"]
    mean_text = ", ".join(
        f"L{loop}={_score(means[str(loop)])}"
        for loop in summary["expected_loops"]
    )
    lines.extend(
        [
            "",
            f"Fully paired tasks: {paired}/{summary['task_count']}.",
            f"Paired means: {mean_text}.",
            "Paired first-to-last mean delta: "
            f"{_score(summary['paired_first_to_last_mean_delta'])}.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=RUNS_ROOT)
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--prefix", action="append", default=[])
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    rows = collect_run_summaries(
        args.runs_dir,
        run_ids=set(args.run_id),
        prefixes=tuple(args.prefix),
        tasks=set(args.task),
    )
    aggregate = summarize_suite(rows) if args.aggregate else None
    if args.json:
        payload: Any = {"runs": rows, "aggregate": aggregate} if aggregate else rows
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_markdown(rows), end="")
        if aggregate:
            print()
            print(format_suite_markdown(aggregate), end="")


if __name__ == "__main__":
    main()
