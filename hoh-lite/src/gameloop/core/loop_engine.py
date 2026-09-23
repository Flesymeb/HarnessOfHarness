"""Benchmark-neutral Planner → Developer → Tester orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from gameloop.benchmarks.base import (
    BenchmarkAdapter,
    BenchmarkContext,
    CandidateRef,
    EvaluationResult,
    TaskSpec,
)
from gameloop.core.roles import RoleName
from gameloop.core.runtime import GameLoopRuntime


@dataclass(frozen=True)
class LoopInputs:
    task: TaskSpec
    context: BenchmarkContext
    parent: CandidateRef | None


@dataclass(frozen=True)
class LoopResult:
    plan: Any
    candidate: CandidateRef
    tester_report: Any
    evaluation: EvaluationResult


PlannerFn = Callable[[LoopInputs], Any]
DeveloperFn = Callable[[LoopInputs, Any], CandidateRef]
TesterFn = Callable[[LoopInputs, Any, CandidateRef], Any]


class LoopEngine:
    """Run one generic loop while keeping benchmark and harness code outside Core."""

    def __init__(self, *, runtime: GameLoopRuntime, benchmark: BenchmarkAdapter) -> None:
        self.runtime = runtime
        self.benchmark = benchmark

    def run(
        self,
        *,
        run_dir: Path,
        task_id: str,
        loop_index: int,
        planner: PlannerFn,
        developer: DeveloperFn,
        tester: TesterFn,
        parent: CandidateRef | None = None,
    ) -> LoopResult:
        task = self.benchmark.load_task(task_id)
        context = self.benchmark.create_context(
            run_dir=run_dir,
            task=task,
            loop_index=loop_index,
            parent=parent,
        )
        inputs = LoopInputs(task=task, context=context, parent=parent)
        self.runtime.begin_loop(loop_index)
        plan = self.runtime.invoke(RoleName.PLANNER, lambda: planner(inputs))
        candidate = self.runtime.invoke(
            RoleName.DEVELOPER,
            lambda: developer(inputs, plan),
        )
        tester_report = self.runtime.invoke(
            RoleName.TESTER,
            lambda: tester(inputs, plan, candidate),
        )
        evaluation = self.benchmark.evaluate(context=context, candidate=candidate)
        self.runtime.finish_loop()
        return LoopResult(
            plan=plan,
            candidate=candidate,
            tester_report=tester_report,
            evaluation=evaluation,
        )
