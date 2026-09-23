"""Explicit benchmark plugin registry."""

from __future__ import annotations

from typing import Iterable

from gameloop.benchmarks.base import BenchmarkAdapter


class BenchmarkRegistry:
    def __init__(self, adapters: Iterable[BenchmarkAdapter] = ()) -> None:
        self._adapters: dict[str, BenchmarkAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: BenchmarkAdapter) -> None:
        benchmark_id = adapter.benchmark_id.strip()
        if not benchmark_id:
            raise ValueError("benchmark_id must not be empty")
        if benchmark_id in self._adapters:
            raise ValueError(f"benchmark already registered: {benchmark_id}")
        self._adapters[benchmark_id] = adapter

    def get(self, benchmark_id: str) -> BenchmarkAdapter:
        try:
            return self._adapters[benchmark_id]
        except KeyError as error:
            available = ", ".join(sorted(self._adapters)) or "none"
            raise ValueError(
                f"unknown benchmark {benchmark_id!r}; registered benchmarks: {available}"
            ) from error

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def default_benchmark_registry() -> BenchmarkRegistry:
    """Load optional adapters without making Core import them eagerly."""

    from gameloop.adapters.gamecraft_bench.adapter import GameCraftBenchAdapter

    return BenchmarkRegistry((GameCraftBenchAdapter(),))
