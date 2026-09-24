"""Public contracts that need no benchmark checkout or provider credentials."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gameloop import cli
from gameloop.adapters.gamecraft_bench import planner, runner
from gameloop.adapters.gamecraft_bench.adapter import GameCraftBenchAdapter
from gameloop.adapters.gamecraft_bench.artifacts import select_resume_trial
from gameloop.benchmarks.base import BenchmarkContext, CandidateRef, EvaluationResult, TaskSpec
from gameloop.benchmarks.registry import BenchmarkRegistry
from gameloop.core.documents import write_json
from gameloop.core.loop_engine import LoopEngine
from gameloop.core.reproducibility import build_reproducibility_manifest
from gameloop.core.roles import default_role_bindings
from gameloop.core.runtime import GameLoopRuntime


class PublicContracts(unittest.TestCase):
    def test_existing_runtime_receipt_is_never_overwritten(self) -> None:
        with TemporaryDirectory() as directory:
            run_dir = Path(directory)
            runtime = GameLoopRuntime(run_dir=run_dir, roles=default_role_bindings())
            runtime.begin_loop(1)
            before = runtime.receipt_path.read_bytes()
            with self.assertRaises(FileExistsError):
                GameLoopRuntime(run_dir=run_dir, roles=default_role_bindings())
            self.assertEqual(runtime.receipt_path.read_bytes(), before)

    def test_json_replacement_failure_keeps_previous_record(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            write_json(path, {"state": "before"})
            before = path.read_bytes()
            with patch("gameloop.core.documents.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    write_json(path, {"state": "after"})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(path.parent.iterdir()), [path])

    def test_resume_selects_last_completed_loop(self) -> None:
        with TemporaryDirectory() as directory:
            run_dir = Path(directory) / "old-run"
            run_dir.mkdir()
            complete_trial = run_dir / "trial-1"
            partial_trial = run_dir / "trial-2"
            complete_trial.mkdir()
            partial_trial.mkdir()
            write_json(
                run_dir / "summary.json",
                {
                    "run_id": "old-run",
                    "task": "tasks/demo",
                    "attempts": [
                        {"attempt": 1, "returncode": 0, "trial_valid": True,
                         "reported_trial": {"trial_dir": str(complete_trial)}},
                        {"attempt": 2, "returncode": 0, "trial_valid": True,
                         "reported_trial": {"trial_dir": str(partial_trial)}},
                    ],
                },
            )
            write_json(
                run_dir / "runtime_receipt.json",
                {"schema_version": 1, "active_loop": 2, "events": [
                    {"loop_index": 1, "role": "tester"},
                    {"loop_index": 2, "role": "tester"},
                ]},
            )
            self.assertEqual(
                select_resume_trial(run_dir), (complete_trial, 2, "tasks/demo")
            )

    def test_complete_generic_loop_writes_role_receipt(self) -> None:
        class Adapter:
            benchmark_id = "example"

            def load_task(self, task_id: str) -> TaskSpec:
                return TaskSpec(self.benchmark_id, task_id, "Build a demo")

            def create_context(self, *, run_dir: Path, task: TaskSpec,
                               loop_index: int, parent: CandidateRef | None = None) -> BenchmarkContext:
                return BenchmarkContext(run_dir, run_dir, task, loop_index)

            def evaluate(self, *, context: BenchmarkContext,
                         candidate: CandidateRef) -> EvaluationResult:
                return EvaluationResult("completed", score=1.0)

        order: list[str] = []
        with TemporaryDirectory() as directory:
            run_dir = Path(directory)
            engine = LoopEngine(
                runtime=GameLoopRuntime(run_dir=run_dir, roles=default_role_bindings()),
                benchmark=Adapter(),
            )
            result = engine.run(
                run_dir=run_dir,
                task_id="demo",
                loop_index=1,
                planner=lambda inputs: order.append("planner") or "plan",
                developer=lambda inputs, plan: order.append("developer") or CandidateRef(
                    run_dir / "game", "candidate-1"
                ),
                tester=lambda inputs, plan, candidate: order.append("tester") or "pass",
            )
            self.assertEqual(order, ["planner", "developer", "tester"])
            self.assertEqual(result.evaluation.score, 1.0)
            receipt = json.loads((run_dir / "runtime_receipt.json").read_text())
            self.assertIsNone(receipt["active_loop"])
            self.assertEqual(
                [event["role"] for event in receipt["events"]], order
            )

    def test_gamecraft_dry_run_completes_public_entry_point(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bench = root / "bench"
            task = bench / "tasks" / "demo"
            task.mkdir(parents=True)
            (task / "instruction.md").write_text("Build a simple game.\n")
            run_dir = root / "runs" / "demo"
            with patch.object(runner, "RUNS_ROOT", root / "runs"):
                result = runner.main([
                    "--bench", str(bench), "--task", "tasks/demo",
                    "--jobs-dir", str(root / "jobs"), "--run-id", "demo",
                    "--dry-run", "--planner-mode", "template",
                    "--no-external-verifier",
                ])
            self.assertEqual(result, 0)
            receipt = json.loads((run_dir / "runtime_receipt.json").read_text())
            self.assertIsNone(receipt["active_loop"])
            self.assertEqual(
                [event["role"] for event in receipt["events"]],
                ["planner", "developer", "tester"],
            )
            self.assertTrue((run_dir / "summary.json").is_file())
            self.assertTrue((run_dir / "reproducibility.json").is_file())

    def test_reproducibility_manifest_excludes_environment_secrets(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = build_reproducibility_manifest(
                source=root,
                benchmark=root,
                roles=default_role_bindings(),
                environment={"PATH": "", "API_KEY": "private-value"},
                config=None,
                paper_harness_version="0.142.5",
            )
            self.assertNotIn("private-value", json.dumps(manifest))
            self.assertEqual(manifest["paper_harness_version"], "0.142.5")

    def test_cli_dispatches_registered_benchmark(self) -> None:
        class Adapter:
            benchmark_id = "example"

            def run_cli(self, argv: list[str]) -> int:
                self.argv = argv
                return 7

        adapter = Adapter()
        registry = BenchmarkRegistry((adapter,))
        with patch.object(cli, "default_benchmark_registry", return_value=registry):
            result = cli.main(["--benchmark", "example", "--task", "demo"])
        self.assertEqual(result, 7)
        self.assertEqual(adapter.argv, ["--task", "demo"])

    def test_gamecraft_cli_keeps_its_default_backend(self) -> None:
        with patch(
            "gameloop.adapters.gamecraft_bench.runner.main", return_value=0
        ) as gamecraft_main:
            self.assertEqual(GameCraftBenchAdapter().run_cli(["--task", "demo"]), 0)
        gamecraft_main.assert_called_once_with(
            ["--task", "demo", "--developer-backend", "harness"]
        )

    def test_planner_retries_invalid_overlay(self) -> None:
        headings = planner._REQUIRED_DOCUMENT_HEADINGS
        scaffold = (
            "# GameCraft development document v001\n"
            + "\n".join(headings)
            + "\n"
            + "A" * 2700
        )
        overlay = (
            "## Project Planner Priorities\n"
            "### Priority Order\n"
            "1. Build one verifiable capability.\n"
            "### Preservation Gate\n"
            "Keep existing behavior working.\n"
            "### Acceptance Gate\n"
            "Verify the new behavior with an observable result.\n"
            + "Provide concrete steps and evidence. " * 7
        )
        process = SimpleNamespace(
            returncode=0,
            timed_out=False,
            idle_timed_out=False,
            wall_timed_out=False,
        )
        with TemporaryDirectory() as directory:
            with (
                patch.object(planner, "_planner_command", return_value=(["stub"], "stub")),
                patch.object(planner, "run_command_with_idle_timeout", return_value=process),
                patch.object(
                    planner,
                    "parse_harness_output",
                    side_effect=[("invalid", None), (overlay, None)],
                ) as parse_output,
            ):
                result = planner.run_project_planner(
                    attempt_dir=Path(directory),
                    loop_index=1,
                    prompt="Write a plan.",
                    scaffold_document=scaffold,
                    experiment_id="codex-gpt-5.5",
                    environment={},
                    reasoning_effort="high",
                    wall_timeout_seconds=0,
                    idle_timeout_seconds=30,
                    dry_run=False,
                )
            self.assertEqual(parse_output.call_count, 2)
            self.assertEqual(result.status["attempts"], 2)
            self.assertFalse(result.status["used_fallback"])
            self.assertIn(overlay.rstrip(), result.document)
            retry_prompt = (Path(directory) / "planner" / "planner_prompt.md").read_text()
            self.assertIn("failed validation", retry_prompt)
            self.assertTrue(
                (Path(directory) / "planner" / "planner_prompt.attempt-01.md").is_file()
            )


if __name__ == "__main__":
    unittest.main()
