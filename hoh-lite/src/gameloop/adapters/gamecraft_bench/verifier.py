"""Verifier entry point that extends, but never modifies, GameCraft-Bench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gamecraft_bench import config as bench_config
from gamecraft_bench.verifier.judges import get_judge as get_upstream_judge
from gamecraft_bench.verifier.score import ScoreResult, score_project

from .judges.codex_cli import CodexCliJudge


def _judge(backend: str | None, model: str | None):
    name = (backend or bench_config.JUDGE_BACKEND).strip().lower()
    if name in {"codex", "codex-cli"}:
        return CodexCliJudge(model=model or bench_config.JUDGE_MODEL)
    return get_upstream_judge(backend=name, model=model)


def _write_outputs(output: Path, result: ScoreResult) -> None:
    (output / "reward.txt").write_text(f"{result.reward:.6f}\n", encoding="utf-8")
    tests = [
        {
            "name": "build_check",
            "status": "passed" if result.build_ok else "failed",
            "duration": 0,
        }
    ]
    for requirement in result.requirements:
        tests.append(
            {
                "name": f"requirement::{requirement.requirement_id}",
                "status": "passed" if requirement.aggregated >= 0.5 else "failed",
                "duration": 0,
                "message": requirement.description,
            }
        )
    passed = sum(item["status"] == "passed" for item in tests)
    ctrf = {
        "results": {
            "tool": {"name": "gameloop-gamecraft-verifier"},
            "summary": {
                "tests": len(tests),
                "passed": passed,
                "failed": len(tests) - passed,
                "pending": 0,
                "skipped": 0,
                "other": 0,
                "start": 0,
                "stop": 0,
            },
            "tests": tests,
            "extra": {"reward": result.reward, "errors": result.errors},
        }
    }
    (output / "ctrf.json").write_text(json.dumps(ctrf, indent=2), encoding="utf-8")


def _annotate_judge_protocol(output: Path, judge: object) -> None:
    """Add Lite-owned protocol identity without patching upstream scoring code."""

    protocol = getattr(judge, "protocol", None)
    breakdown_path = output / "breakdown.json"
    if not protocol or not breakdown_path.is_file():
        return
    data = json.loads(breakdown_path.read_text(encoding="utf-8"))
    metadata = data.get("judge")
    if not isinstance(metadata, dict):
        metadata = {
            "name": data.get("judge_name", type(judge).__name__),
            "model": data.get("judge_model", getattr(judge, "model", None)),
        }
    metadata["protocol"] = str(protocol)
    data["judge"] = metadata
    breakdown_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gameloop-gamecraft-verifier")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--record-width", type=int, default=854)
    parser.add_argument("--record-height", type=int, default=480)
    parser.add_argument("--frame-interval-seconds", type=float, default=0.5)
    parser.add_argument("--max-demo-seconds", type=float, default=None)
    parser.add_argument("--max-demos", type=int, default=None)
    parser.add_argument("--pass-threshold", type=float, default=0.5)
    args = parser.parse_args(argv)

    args.output.mkdir(parents=True, exist_ok=True)
    judge = _judge(args.judge, args.judge_model)
    result = score_project(
        project_dir=args.project,
        rubric_path=args.rubric,
        output_dir=args.output,
        judge=judge,
        fps=args.fps,
        viewport=(args.width, args.height),
        record_size=(args.record_width, args.record_height),
        frame_interval_seconds=args.frame_interval_seconds,
        max_demo_seconds=args.max_demo_seconds,
        max_demos=args.max_demos,
    )
    _annotate_judge_protocol(args.output, judge)
    _write_outputs(args.output, result)
    print(f"[verifier] reward={result.reward:.6f} build_ok={result.build_ok}", flush=True)
    for error in result.errors:
        print(f"[verifier] ! {error}", flush=True)
    # A zero threshold allows a valid low score, not missing replay or judge
    # evidence. Callers must be able to distinguish infrastructure failure.
    return 0 if not result.errors and result.reward >= args.pass_threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
