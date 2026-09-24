"""Public contracts that need no benchmark checkout or provider credentials."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gameloop import cli
from gameloop.adapters.gamecraft_bench import planner
from gameloop.adapters.gamecraft_bench.adapter import GameCraftBenchAdapter
from gameloop.benchmarks.registry import BenchmarkRegistry
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
