"""Benchmark-neutral contracts used by the GameLoop control plane.

Benchmark implementations are plugins.  The core loop never imports a
benchmark package, task catalog, Harbor, or a model harness.
"""

from gameloop.benchmarks.base import (
    BenchmarkAdapter,
    BenchmarkContext,
    CandidateRef,
    EvaluationResult,
    TaskSpec,
)
from gameloop.benchmarks.registry import BenchmarkRegistry, default_benchmark_registry

__all__ = [
    "BenchmarkAdapter",
    "BenchmarkContext",
    "BenchmarkRegistry",
    "CandidateRef",
    "EvaluationResult",
    "TaskSpec",
    "default_benchmark_registry",
]
