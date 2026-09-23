"""Small, serializable boundary between GameLoop and any benchmark."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class TaskSpec:
    """A benchmark task after the adapter has resolved it.

    The Runtime receives only this public description; task catalogs and
    benchmark-specific files remain inside the adapter.
    """

    benchmark_id: str
    task_id: str
    instruction: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkContext:
    """One run-owned benchmark workspace."""

    run_dir: Path
    workspace: Path
    task: TaskSpec
    loop_index: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateRef:
    """Opaque candidate identity passed between roles and an adapter."""

    path: Path
    candidate_id: str
    parent_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationResult:
    """Benchmark-owned evaluation, normalized for Runtime receipts."""

    status: str
    score: float | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    artifacts: Mapping[str, Path] = field(default_factory=dict)


class BenchmarkAdapter(Protocol):
    """Adapter contract; no role or harness implementation belongs here."""

    benchmark_id: str

    def load_task(self, task_id: str) -> TaskSpec:
        """Resolve one public task without exposing the catalog to Core."""

    def create_context(
        self,
        *,
        run_dir: Path,
        task: TaskSpec,
        loop_index: int,
        parent: CandidateRef | None = None,
    ) -> BenchmarkContext:
        """Create an isolated, run-owned workspace for one loop."""

    def evaluate(
        self,
        *,
        context: BenchmarkContext,
        candidate: CandidateRef,
    ) -> EvaluationResult:
        """Evaluate a candidate using benchmark-owned tooling."""
