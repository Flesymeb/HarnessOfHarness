#!/usr/bin/env python3
"""Summarize GameCraft-Bench results for GameLoop runs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .paths import default_jobs_dir


DIMENSION_PREFIXES = ("M", "D", "V", "A")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _judge_from_breakdown(
    data: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    judge = data.get("judge")
    if isinstance(judge, dict):
        return judge.get("name"), judge.get("model"), judge.get("protocol")
    return data.get("judge_name"), data.get("judge_model"), data.get("judge_protocol")


def _dimension_means(variables: dict[str, Any]) -> dict[str, float]:
    grouped: dict[str, list[float]] = {prefix: [] for prefix in DIMENSION_PREFIXES}
    for key, value in variables.items():
        if not key:
            continue
        prefix = key[0].upper()
        if prefix not in grouped:
            continue
        try:
            grouped[prefix].append(float(value))
        except (TypeError, ValueError):
            continue
    return {
        prefix: round(sum(values) / len(values), 6)
        for prefix, values in grouped.items()
        if values
    }


def _quality_score(judge_name: str | None, judge_model: str | None) -> bool:
    if not judge_name:
        return False
    if judge_name == "StubJudge":
        return False
    return judge_model == "gpt-5.5"


def summarize_breakdown_file(path: Path) -> dict[str, Any]:
    data = read_json(path)
    judge_name, judge_model, judge_protocol = _judge_from_breakdown(data)
    variables = data.get("variables")
    if not isinstance(variables, dict):
        variables = {}

    return {
        "path": str(path),
        "reward": data.get("reward"),
        "build_ok": data.get("build_ok"),
        "judge_name": judge_name,
        "judge_model": judge_model,
        "judge_protocol": judge_protocol,
        "quality_score": _quality_score(judge_name, judge_model),
        "dimension_means": _dimension_means(variables),
        "num_requirements": len(data.get("requirements") or []),
        "num_errors": len(data.get("errors") or []),
    }


def infer_method(job_name: str) -> str:
    """Infer broad baseline labels without reading agent-private artifacts."""

    lowered = job_name.lower()
    if "skills" in lowered:
        return "Skill-Enhanced Codex"
    if "vanilla" in lowered:
        return "Vanilla Codex"
    return "HoH-lite"


def _trial_task(trial_dir: Path) -> str:
    return trial_dir.name.split("__", 1)[0]


def iter_trial_breakdowns(
    jobs_dir: Path,
    task_filters: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job_dir in sorted(path for path in jobs_dir.iterdir() if path.is_dir()):
        for trial_dir in sorted(path for path in job_dir.iterdir() if path.is_dir()):
            task = _trial_task(trial_dir)
            if task_filters and task not in task_filters:
                continue
            for breakdown in sorted(trial_dir.glob("verifier*/breakdown.json")):
                summary = summarize_breakdown_file(breakdown)
                summary.update(
                    {
                        "task": task,
                        "job": job_dir.name,
                        "trial": trial_dir.name,
                        "verifier": breakdown.parent.name,
                        "method": infer_method(job_dir.name),
                        "running": False,
                    }
                )
                rows.append(summary)
            if not any(trial_dir.glob("verifier*/breakdown.json")):
                rows.append(
                    {
                        "task": task,
                        "job": job_dir.name,
                        "trial": trial_dir.name,
                        "verifier": "",
                        "method": infer_method(job_dir.name),
                        "running": True,
                        "reward": None,
                        "build_ok": None,
                        "judge_name": None,
                        "judge_model": None,
                        "judge_protocol": None,
                        "quality_score": False,
                        "dimension_means": {},
                        "path": "",
                        "num_requirements": 0,
                        "num_errors": 0,
                    }
                )
    return rows


def format_markdown(rows: list[dict[str, Any]]) -> str:
    header = [
        "| Task | Method | Job | Verifier | Reward | M | D | V | A | Judge | Build | Quality? |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    lines = header[:]
    for row in rows:
        dims = row.get("dimension_means") or {}
        judge_name = row.get("judge_name") or ""
        judge_model = row.get("judge_model") or ""
        judge = f"{judge_name}:{judge_model}" if judge_name or judge_model else ""
        reward = row.get("reward")
        reward_text = "" if reward is None else f"{float(reward):.6f}"
        dim_text = {key: "" if key not in dims else f"{float(dims[key]):.3f}" for key in DIMENSION_PREFIXES}
        lines.append(
            "| {task} | {method} | {job} | {verifier} | {reward} | {M} | {D} | {V} | {A} | {judge} | {build} | {quality} |".format(
                task=row.get("task", ""),
                method=row.get("method", ""),
                job=row.get("job", ""),
                verifier=row.get("verifier", ""),
                reward=reward_text,
                M=dim_text["M"],
                D=dim_text["D"],
                V=dim_text["V"],
                A=dim_text["A"],
                judge=judge,
                build=row.get("build_ok"),
                quality="yes" if row.get("quality_score") else "no",
            )
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    configured_jobs = os.environ.get("GAMELOOP_JOBS_DIR")
    default_jobs = (
        Path(configured_jobs).expanduser()
        if configured_jobs
        else default_jobs_dir()
    )
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=default_jobs,
        help=(
            "Harbor jobs directory. Defaults to GAMELOOP_JOBS_DIR or "
            "<GAMELOOP_HOME>/jobs/gameloop."
        ),
    )
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = iter_trial_breakdowns(args.jobs_dir, set(args.task))
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(format_markdown(rows), end="")


if __name__ == "__main__":
    main()
