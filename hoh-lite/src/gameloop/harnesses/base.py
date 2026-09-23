"""Harness-neutral role invocation contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol

from gameloop.core.roles import RoleBinding


@dataclass(frozen=True)
class HarnessRequest:
    binding: RoleBinding
    workspace: Path
    prompt_path: Path
    output_path: Path
    environment: Mapping[str, str]
    json_stream: bool = False
    ephemeral: bool = True
    sandbox_mode: str | None = None
    extra_config: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedHarness:
    command: tuple[str, ...]
    environment: Mapping[str, str]
    stdin_path: Path | None
    output_mode: str
    preserved_paths: tuple[Path, ...] = field(default_factory=tuple)
    readonly_files: tuple[tuple[Path, Path], ...] = field(default_factory=tuple)


class HarnessAdapter(Protocol):
    harness_id: str

    def prepare(self, request: HarnessRequest) -> PreparedHarness:
        """Prepare a role process without starting it."""
