"""Record public software identity for a run without copying credentials."""

from __future__ import annotations

import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any, Mapping

from gameloop.core.roles import RoleBinding, RoleName


def _command_output(command: list[str], *, path: str | None = None) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": path} if path is not None else None,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).strip() or None


def _git_revision(path: Path) -> str | None:
    return _command_output(["git", "-C", str(path), "rev-parse", "HEAD"])


def _git_dirty(path: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return bool(result.stdout.strip()) if result.returncode == 0 else None


def build_reproducibility_manifest(
    *,
    source: Path,
    benchmark: Path,
    roles: Mapping[RoleName, RoleBinding],
    environment: Mapping[str, str],
    config: Path | None,
    paper_harness_version: str | None,
) -> dict[str, Any]:
    search_path = environment.get("PATH")
    versions: dict[str, str | None] = {}
    for harness in sorted({binding.harness for binding in roles.values()}):
        executable = shutil.which(harness, path=search_path)
        versions[harness] = (
            _command_output([executable, "--version"], path=search_path)
            if executable else None
        )
    godot = environment.get("GAMECRAFT_BENCH_GODOT_BIN", "godot")
    godot_executable = shutil.which(godot, path=search_path)
    config_hash = (
        hashlib.sha256(config.read_bytes()).hexdigest()
        if config is not None and config.is_file() else None
    )
    return {
        "schema_version": 1,
        "python": platform.python_version(),
        "system": platform.system(),
        "source_revision": _git_revision(source),
        "source_dirty": _git_dirty(source),
        "benchmark_revision": _git_revision(benchmark),
        "benchmark_dirty": _git_dirty(benchmark),
        "config_sha256": config_hash,
        "roles": {role.value: roles[role].to_dict() for role in RoleName},
        "harness_versions": versions,
        "godot_version": (
            _command_output([godot_executable, "--version"], path=search_path)
            if godot_executable else None
        ),
        "paper_harness_version": paper_harness_version,
    }
