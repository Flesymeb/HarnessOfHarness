"""Harness execution owned by Core, independent of any benchmark adapter."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from gameloop.core.execution import CommandRunResult, run_command_with_idle_timeout

if TYPE_CHECKING:
    from gameloop.harnesses.base import PreparedHarness


def run_role_command(
    command: list[str] | tuple[str, ...],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    wall_timeout_seconds: float | None,
    idle_timeout_seconds: float,
    env: dict[str, str] | None = None,
    stdin_path: Path | None = None,
) -> CommandRunResult:
    """Run a role process through the Core lifecycle supervisor.

    The signature intentionally matches ``run_command_with_idle_timeout`` so
    adapters can migrate without duplicating timeout/cleanup code.
    """

    return run_command_with_idle_timeout(
        list(command),
        cwd=cwd,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        wall_timeout_seconds=wall_timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        env=env,
        stdin_path=stdin_path,
    )


def run_prepared_harness(
    prepared: PreparedHarness,
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    wall_timeout_seconds: float | None,
    idle_timeout_seconds: float,
) -> CommandRunResult:
    """Execute any prepared role process with the same timeout semantics.

    This is deliberately the only process runner used by role adapters.  A
    benchmark may prepare a workspace, but it cannot decide how Codex,
    OpenCode, Pi, or another Harness is launched.
    """

    return run_command_with_idle_timeout(
        list(prepared.command),
        cwd=cwd,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        wall_timeout_seconds=wall_timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        env=dict(prepared.environment),
        stdin_path=prepared.stdin_path,
    )
