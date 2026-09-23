"""Shared runtime for Planner, Developer, and Tester harness processes."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from gameloop.core.execution import CommandRunResult
from gameloop.core.harness_runner import run_prepared_harness
from gameloop.core.roles import RoleBinding
from gameloop.harnesses.base import HarnessRequest, PreparedHarness
from gameloop.harnesses.output import parse_harness_output
from gameloop.harnesses.registry import HarnessRegistry, default_harness_registry


class HarnessExecution:
    """One completed role process and its normalized model output."""

    def __init__(
        self,
        *,
        prepared: PreparedHarness,
        process: CommandRunResult,
        text: str,
        usage: dict | None,
    ) -> None:
        self.prepared = prepared
        self.process = process
        self.text = text
        self.usage = usage


class HarnessRuntime:
    """Resolve one role binding without knowing the active benchmark."""

    def __init__(self, registry: HarnessRegistry | None = None) -> None:
        self.registry = registry or default_harness_registry()

    def prepare_role(
        self,
        *,
        binding: RoleBinding,
        workspace: Path,
        prompt_path: Path,
        output_path: Path,
        environment: Mapping[str, str],
        json_stream: bool = False,
        ephemeral: bool = True,
        sandbox_mode: str | None = None,
        extra_config: tuple[str, ...] = (),
    ) -> PreparedHarness:
        return self.registry.get(binding.harness).prepare(
            HarnessRequest(
                binding=binding,
                workspace=workspace,
                prompt_path=prompt_path,
                output_path=output_path,
                environment=environment,
                json_stream=json_stream,
                ephemeral=ephemeral,
                sandbox_mode=sandbox_mode,
                extra_config=extra_config,
            )
        )

    def execute_role(
        self,
        *,
        prepared: PreparedHarness,
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        output_path: Path,
        wall_timeout_seconds: float | None,
        idle_timeout_seconds: float,
    ) -> HarnessExecution:
        process = run_prepared_harness(
            prepared,
            cwd=cwd,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            wall_timeout_seconds=wall_timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        text, usage = parse_harness_output(
            prepared.output_mode,
            stdout_path=stdout_path,
            output_path=output_path,
        )
        return HarnessExecution(
            prepared=prepared,
            process=process,
            text=text,
            usage=usage,
        )
