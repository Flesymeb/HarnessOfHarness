"""Benchmark backend process supervision.

Adapters build their own benchmark command, but process groups, output capture,
and timeout cleanup remain owned by the Runtime support layer. This keeps an
external evaluator from implementing its own lifecycle semantics.
"""

from __future__ import annotations

from pathlib import Path

from gameloop.core.execution import run_captured_command


def run_benchmark_command(
    command: list[str] | tuple[str, ...],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int | None,
) -> tuple[int, str, str, bool]:
    if timeout_seconds is not None and timeout_seconds < 1:
        raise ValueError("timeout_seconds must be >= 1 when provided")
    result = run_captured_command(
        list(command),
        cwd=cwd,
        env=environment,
        timeout_seconds=timeout_seconds,
    )
    return result.returncode, result.stdout, result.stderr, result.timed_out
