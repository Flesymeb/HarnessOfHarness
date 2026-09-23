"""GameCraft-Bench plugin boundary.

Only this module knows how a GameCraft task is materialized.  Core Runtime,
role Harnesses, and the generic loop engine do not import GameCraft or Harbor.
The compatibility runner can continue to live beside this adapter while it is
migrated incrementally; it remains benchmark-owned and is never imported by
the generic Core Runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Callable

from gameloop.adapters.gamecraft_bench.paths import (
    DEFAULT_BENCH,
    copy_public_task,
    ignore_generated_and_symlinks,
    resolve_path,
)
from gameloop.benchmarks.base import (
    BenchmarkContext,
    CandidateRef,
    EvaluationResult,
    TaskSpec,
)
from gameloop.core.documents import load_public_task_instruction


EvaluationFn = Callable[[BenchmarkContext, CandidateRef], EvaluationResult]


def inspect_data_contract(bench: Path) -> dict[str, object]:
    """Check only the files required by the direct Harness adapter.

    Harbor agents, container backends, namespaces, and bubblewrap are not part
    of this contract.  The official evaluator performs its own dependency
    validation when scoring starts.
    """

    root = bench.expanduser().resolve()
    required = (
        root / "tasks",
        root / "gamecraft_bench" / "__init__.py",
    )
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    return {
        "schema_version": 1,
        "benchmark": "gamecraft-bench",
        "bench": str(root),
        "developer_backend": "gameloop-harness-runtime",
        "required_paths_missing": missing,
        "status": "ready" if not missing else "incompatible",
        "error": None if not missing else "required benchmark data is missing",
    }


@dataclass
class GameCraftBenchAdapter:
    """Resolve GameCraft tasks and expose them through the generic adapter API."""

    bench: Path | None = None
    evaluator: EvaluationFn | None = None
    benchmark_id: str = "gamecraft-bench"

    def _bench_root(self) -> Path:
        root = self.bench or DEFAULT_BENCH
        if root is None:
            raise RuntimeError(
                "GameCraft-Bench is not installed; pass an explicit bench root"
            )
        return resolve_path(root)

    def _task_path(self, task_id: str) -> Path:
        root = self._bench_root()
        tasks_root = (root / "tasks").resolve()
        candidate = Path(task_id).expanduser()
        if not candidate.is_absolute():
            relative = (
                candidate
                if str(candidate).startswith("tasks/")
                else Path("tasks") / candidate
            )
            candidate = root / relative
        candidate = candidate.resolve()
        try:
            candidate.relative_to(tasks_root)
        except ValueError as exc:
            raise ValueError(
                "GameCraft task must resolve under the benchmark tasks directory"
            ) from exc
        if not candidate.is_dir():
            raise FileNotFoundError(f"GameCraft task does not exist: {candidate}")
        return candidate

    def load_task(self, task_id: str) -> TaskSpec:
        path = self._task_path(task_id)
        return TaskSpec(
            benchmark_id=self.benchmark_id,
            task_id=path.name,
            instruction=load_public_task_instruction(path),
            metadata={"source_path": str(path)},
        )

    def create_context(
        self,
        *,
        run_dir: Path,
        task: TaskSpec,
        loop_index: int,
        parent: CandidateRef | None = None,
    ) -> BenchmarkContext:
        source = Path(str(task.metadata.get("source_path") or self._task_path(task.task_id)))
        workspace = run_dir / "benchmark" / f"loop-{loop_index:02d}" / "task"
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        copy_public_task(source, workspace)
        if parent is not None and parent.path.is_dir():
            game_dir = workspace / "workspace" / "game"
            if game_dir.exists():
                shutil.rmtree(game_dir)
            game_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                parent.path,
                game_dir,
                ignore=ignore_generated_and_symlinks,
            )
        return BenchmarkContext(
            run_dir=run_dir,
            workspace=workspace,
            task=task,
            loop_index=loop_index,
            metadata={"bench_root": str(self._bench_root())},
        )

    def evaluate(
        self,
        *,
        context: BenchmarkContext,
        candidate: CandidateRef,
    ) -> EvaluationResult:
        if self.evaluator is None:
            raise RuntimeError(
                "GameCraft evaluation is adapter-owned; configure an evaluator "
                "or use the legacy compatibility runner"
            )
        return self.evaluator(context, candidate)
