"""Path helpers for the GameCraft-Bench adapter."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import shutil

from gameloop.locations import (
    PACKAGE_ROOT,
    PROJECT_ROOT,
    discover_project_root as _discover_project_root,
)


SCRIPT_DIR = Path(__file__).resolve().parent


def discover_project_root(
    *,
    script_dir: Path = SCRIPT_DIR,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> Path:
    """Choose a writable runtime root without assuming a ``src/`` install.

    A source checkout is recognized by its own package and ``pyproject.toml``.
    A regular wheel/site-packages installation instead writes relative to the
    caller's working directory.  ``GAMELOOP_HOME`` is the explicit override.
    """

    return _discover_project_root(
        package_root=script_dir.parents[1],
        cwd=cwd,
        environment=environment,
    )


REPO_ROOT = PROJECT_ROOT
SRC_ROOT = PACKAGE_ROOT.parent

RUNS_ROOT = PROJECT_ROOT / "runs"
TASK_WORKDIRS = PROJECT_ROOT / "workdirs" / "task_workdirs"


def installed_bench_root() -> Path | None:
    """Return the checkout that provides the importable upstream package.

    Discovery deliberately follows Python's import resolution instead of
    guessing machine-specific sibling directories.  An explicit ``--bench``
    or ``GAMELOOP_BENCH`` still takes precedence in the CLI.
    """

    try:
        spec = importlib.util.find_spec("gamecraft_bench")
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    package_dir = Path(spec.origin).expanduser().resolve().parent
    candidate = package_dir.parent
    if not (candidate / "gamecraft_bench" / "__init__.py").is_file():
        return None
    return candidate


DEFAULT_BENCH = installed_bench_root()

_RUN_ID_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def validate_run_id(value: str) -> str:
    """Reject run identifiers that can escape or alias a writable root."""

    if not isinstance(value, str) or not _RUN_ID_COMPONENT.fullmatch(value):
        raise ValueError(
            "run id must be 1-128 ASCII letters, digits, '_' or '-', "
            "and must start with a letter or digit"
        )
    return value


def run_directory(root: Path, run_id: str) -> Path:
    """Resolve a single-component run directory below ``root``."""

    root = root.expanduser().resolve()
    candidate = (root / validate_run_id(run_id)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("run directory escapes its writable root") from error
    return candidate


def _nested_run_directory(root: Path, value: str) -> Path:
    raw = Path(value)
    if raw.is_absolute() or not raw.parts:
        raise ValueError("workdir run path must be relative")
    for component in raw.parts:
        validate_run_id(component)
    root = root.expanduser().resolve()
    candidate = root.joinpath(*raw.parts).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("workdir run path escapes its writable root") from error
    return candidate


def slugify(value: str) -> str:
    clean = []
    for char in value:
        if char.isalnum() or char in {"-", "_"}:
            clean.append(char)
        elif char in {"/", "\\", ".", " "}:
            clean.append("-")
    slug = "".join(clean).strip("-")
    return slug or "gamecraft-run"


def normalize_task_arg(task: str) -> str:
    path = Path(task)
    if path.is_absolute() or task.startswith("tasks/"):
        return task
    return f"tasks/{task}"


def resolve_path(value: str | Path, base: Path = REPO_ROOT) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def copy_public_task(source: Path, dest: Path) -> None:
    """Materialize only the task inputs needed by an agent workspace.

    The benchmark's tests, reference solution, and annotations stay at the
    original task path, which is read by the host-side evaluator only.
    """

    dest.mkdir(parents=True, exist_ok=True)
    for name in ("instruction.md", "README.md", "task.toml"):
        item = source / name
        if item.is_file() and not item.is_symlink():
            shutil.copy2(item, dest / name)

    for name in ("environment", "workspace"):
        item = source / name
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, dest / name, ignore=ignore_symlinks)


def ignore_symlinks(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if (Path(directory) / name).is_symlink()}


def ignore_generated_and_symlinks(directory: str, names: list[str]) -> set[str]:
    return set(shutil.ignore_patterns(".godot", "*.tmp")(directory, names)) | ignore_symlinks(
        directory, names
    )


def default_jobs_dir(runtime_root: Path = PROJECT_ROOT) -> Path:
    """Keep mutable Harbor output under the Lite runtime root by default."""

    return (runtime_root.expanduser().resolve() / "jobs" / "gameloop").resolve()


def prepend_default_tool_paths(
    env: dict[str, str],
    *,
    bench: Path | None = None,
) -> list[Path]:
    """Expose tools from the selected Bench virtualenv, if it has ffmpeg.

    No user-home or repository-layout guesses are made.  System tools already
    present on ``PATH`` remain untouched.
    """

    path_parts = [part for part in env.get("PATH", "").split(os.pathsep) if part]
    added: list[Path] = []
    candidates = ((bench / ".venv" / "bin"),) if bench is not None else ()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        candidate_text = str(candidate)
        if candidate_text in path_parts:
            continue
        if not (candidate / "ffmpeg").exists():
            continue
        added.append(candidate)
    if added:
        env["PATH"] = os.pathsep.join([*(str(path) for path in added), *path_parts])
    return added


def copy_task_for_attempt(
    *,
    bench: Path,
    task_arg: str,
    run_id: str,
    attempt: int,
    previous_best: dict[str, object] | None,
    task_workdirs: Path | None = None,
) -> Path:
    source = Path(task_arg)
    if not source.is_absolute():
        source = bench / task_arg
    dest_root = TASK_WORKDIRS if task_workdirs is None else task_workdirs
    run_root = _nested_run_directory(dest_root, run_id)
    dest_root_resolved = dest_root.expanduser().resolve()
    dest = (run_root / f"attempt-{attempt:02d}" / source.name).resolve(
        strict=False
    )
    try:
        dest.relative_to(dest_root_resolved)
    except ValueError as error:
        raise ValueError("task workdir escapes its writable root") from error
    if source.resolve() == dest:
        raise ValueError("task source and workdir destination must differ")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy_public_task(source, dest)

    game_source = None
    if previous_best:
        trial_dir = previous_best.get("trial_dir")
        if trial_dir:
            candidate = Path(str(trial_dir)) / "sandbox" / "workspace" / "game"
            if candidate.exists():
                game_source = candidate
    if game_source:
        workspace_game = dest / "workspace" / "game"
        if workspace_game.exists():
            shutil.rmtree(workspace_game)
        workspace_game.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(game_source, workspace_game, ignore=ignore_generated_and_symlinks)
    return dest
