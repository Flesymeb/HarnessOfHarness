"""Compatibility checks for external, unmodified GameCraft-Bench checkouts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from .paths import PROJECT_ROOT, SRC_ROOT


_REQUIRED_PATHS = (
    "gamecraft_bench/__init__.py",
    "gamecraft_bench/local_env.py",
    "gamecraft_bench/verifier/score.py",
    "tasks",
)

_RUNTIME_RELEVANT_GIT_PATHS = (
    "gamecraft_bench",
    "tasks",
    "scripts",
    "tools",
    "pyproject.toml",
    "sitecustomize.py",
    "usercustomize.py",
)


def _git_metadata(bench: Path) -> dict[str, Any]:
    if not (bench / ".git").exists():
        return {"is_git_checkout": False, "commit": None, "dirty": None}
    commit = subprocess.run(
        ["git", "-C", str(bench), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "-C", str(bench), "status", "--porcelain", "--untracked-files=no"],
        text=True,
        capture_output=True,
        check=False,
    )
    runtime_status = subprocess.run(
        [
            "git",
            "-C",
            str(bench),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *_RUNTIME_RELEVANT_GIT_PATHS,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    changed = sorted(
        line[3:] for line in status.stdout.splitlines() if len(line) > 3
    )
    untracked_runtime = sorted(
        line[3:]
        for line in runtime_status.stdout.splitlines()
        if line.startswith("?? ") and len(line) > 3
    )
    core_changed = sorted(
        path
        for path in changed
        if path.startswith("gamecraft_bench/") or path == "pyproject.toml"
    )
    return {
        "is_git_checkout": True,
        "commit": commit.stdout.strip() or None,
        "dirty": bool(changed or untracked_runtime),
        "tracked_change_count": len(changed),
        "changed_paths": changed,
        "changed_core_paths": core_changed,
        "untracked_runtime_path_count": len(untracked_runtime),
        "untracked_runtime_paths": untracked_runtime,
    }


def inspect_bench_compatibility(
    bench: Path,
    *,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Probe imports and filesystem backends in the selected Bench checkout."""

    bench = bench.expanduser().resolve()
    missing = [relative for relative in _REQUIRED_PATHS if not (bench / relative).exists()]
    source = _git_metadata(bench)
    env = dict(environment or os.environ)
    dirty_bench_allowed = (
        env.get("GAMELOOP_ALLOW_DIRTY_BENCH") == "1"
        or env.get("GAMELOOP_ALLOW_DIRTY_BENCH_CORE") == "1"
    )
    report: dict[str, Any] = {
        "schema_version": 2,
        "bench": str(bench),
        "required_paths_missing": missing,
        "source": source,
        "dirty_bench_allowed": dirty_bench_allowed,
    }
    if missing:
        report.update({"status": "incompatible", "error": "required paths are missing"})
        return report

    python_bin = bench / ".venv" / "bin" / "python3"
    if not python_bin.is_file():
        python_bin = Path(sys.executable)
    probe = r'''
import inspect
import json
import os
import platform
from gamecraft_bench import config as bench_config
from gamecraft_bench.local_env import LocalSubprocessEnvironment
from gamecraft_bench.verifier.judges.base import (
    JudgeRequest,
    JudgeResponse,
    MultimodalJudge,
    RequirementSpec,
)
from gamecraft_bench.verifier.score import ScoreResult, score_project
from gameloop.adapters.gamecraft_bench.local_agent import GameLoopCodex
from gameloop.adapters.gamecraft_bench.local_env import StableLocalSubprocessEnvironment
from gameloop.adapters.gamecraft_bench.judges.codex_cli import CodexCliJudge

def attempt(fn):
    try:
        fn()
        return {"available": True, "error": None}
    except Exception as error:
        return {"available": False, "error": f"{type(error).__name__}: {error}"}

def read_host_policy(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None

def require_parameters(label, callable_value, expected):
    try:
        actual = set(inspect.signature(callable_value).parameters)
    except (TypeError, ValueError) as error:
        contract_errors.append(f"{label}: cannot inspect signature ({error})")
        return
    missing = sorted(set(expected) - actual)
    if missing:
        contract_errors.append(f"{label}: missing parameters {missing}")

contract_errors = []
for attribute in (
    "_build_ns_command",
    "_host_path_for_prefix",
    "_populate_workspace_template",
    "_preflight_unshare",
    "_short",
    "_stuck_godot_watchdog",
    "_terminate_process_group",
    "_to_host",
):
    if not callable(getattr(LocalSubprocessEnvironment, attribute, None)):
        contract_errors.append(
            f"LocalSubprocessEnvironment.{attribute}: required callable is missing"
        )
for attribute in ("_BIND_PLAN", "STUCK_GODOT_KILL_SEC"):
    if not hasattr(LocalSubprocessEnvironment, attribute):
        contract_errors.append(
            f"LocalSubprocessEnvironment.{attribute}: required attribute is missing"
        )
require_parameters(
    "LocalSubprocessEnvironment.__init__",
    LocalSubprocessEnvironment.__init__,
    ("environment_dir", "environment_name", "session_id", "trial_paths", "task_env_config"),
)
require_parameters(
    "LocalSubprocessEnvironment.start",
    LocalSubprocessEnvironment.start,
    ("force_build",),
)
require_parameters(
    "LocalSubprocessEnvironment.exec",
    LocalSubprocessEnvironment.exec,
    ("command", "cwd", "env", "timeout_sec", "user"),
)
require_parameters(
    "score_project",
    score_project,
    (
        "project_dir", "rubric_path", "output_dir", "judge", "fps", "viewport",
        "record_size", "frame_interval_seconds", "max_demo_seconds", "max_demos",
    ),
)
for attribute in (
    "ASSET_LIBRARY",
    "ASSET_LIBRARY_MOUNTPOINT",
    "GAME_PROJECT_PATH",
    "JUDGE_BACKEND",
    "JUDGE_MODEL",
    "OGA_LIBRARY",
    "OGA_LIBRARY_MOUNTPOINT",
    "PATH_REWRITE_PATTERNS",
    "TOOLS_DIR",
    "TOOLS_MOUNTPOINT",
):
    if not hasattr(bench_config, attribute):
        contract_errors.append(f"gamecraft_bench.config.{attribute}: missing")
if not callable(getattr(bench_config, "env_for_subprocess", None)):
    contract_errors.append("gamecraft_bench.config.env_for_subprocess: missing")
for result_attribute in ("reward", "build_ok", "requirements", "errors"):
    if result_attribute not in getattr(ScoreResult, "__dataclass_fields__", {}):
        contract_errors.append(f"ScoreResult.{result_attribute}: missing dataclass field")

namespace = attempt(LocalSubprocessEnvironment._preflight_unshare)
bwrap = attempt(StableLocalSubprocessEnvironment._preflight_bwrap)
configured = StableLocalSubprocessEnvironment._configured_backend()
direct_allowed = os.environ.get(StableLocalSubprocessEnvironment.DIRECT_BACKEND_ENV) == "1"
if configured == "namespace":
    selected = "namespace" if namespace["available"] else None
elif configured == "bwrap":
    selected = "bwrap" if bwrap["available"] else None
elif configured == "direct":
    selected = "direct" if direct_allowed else None
else:
    selected = (
        "namespace" if namespace["available"] else
        "bwrap" if bwrap["available"] else
        "direct" if direct_allowed else None
    )
print(json.dumps({
    "python_version": platform.python_version(),
    "gamecraft_module": __import__("gamecraft_bench").__file__,
    "environment_adapter": f"{StableLocalSubprocessEnvironment.__module__}:{StableLocalSubprocessEnvironment.__name__}",
    "agent_adapter": f"{GameLoopCodex.__module__}:{GameLoopCodex.__name__}",
    "judge_adapter": f"{CodexCliJudge.__module__}:{CodexCliJudge.__name__}",
    "configured_backend": configured,
    "namespace": namespace,
    "bwrap": bwrap,
    "direct_allowed": direct_allowed,
    "selected_backend": selected,
    "host_policy": {
        "kernel.unprivileged_userns_clone": read_host_policy(
            "/proc/sys/kernel/unprivileged_userns_clone"
        ),
        "user.max_user_namespaces": read_host_policy(
            "/proc/sys/user/max_user_namespaces"
        ),
        "kernel.apparmor_restrict_unprivileged_userns": read_host_policy(
            "/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
        ),
    },
    "contract_errors": contract_errors,
}))
'''
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(bench), str(SRC_ROOT), existing) if item
    )
    try:
        completed = subprocess.run(
            [str(python_bin), "-c", probe],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        report.update({"status": "incompatible", "error": str(error)})
        return report
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        missing_dependency = re.search(
            r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]",
            detail,
        )
        if missing_dependency:
            module = missing_dependency.group(1)
            report.update(
                {
                    "status": "incompatible",
                    "missing_python_dependency": module,
                    "error": (
                        f"GameCraft-Bench dependency {module!r} is unavailable to "
                        f"{python_bin}. Install the unmodified Bench checkout into "
                        "the same Python environment as HoH-lite before running."
                    ),
                }
            )
            return report
        report.update(
            {
                "status": "incompatible",
                "error": detail,
            }
        )
        return report
    try:
        runtime = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        report.update({"status": "incompatible", "error": f"invalid probe output: {error}"})
        return report
    report["runtime"] = runtime
    changed_paths = source.get("changed_paths")
    if changed_paths is None:
        # Compatibility with callers/tests providing the schema-v2 metadata.
        changed_paths = source.get("changed_core_paths") or []
    untracked_runtime_paths = source.get("untracked_runtime_paths") or []
    dirty_runtime_blocked = bool(
        changed_paths or untracked_runtime_paths
    ) and not dirty_bench_allowed
    report["status"] = (
        "ready"
        if (
            runtime.get("selected_backend")
            and not runtime.get("contract_errors")
            and not dirty_runtime_blocked
        )
        else "incompatible"
    )
    if report["status"] != "ready":
        if dirty_runtime_blocked:
            report["error"] = (
                "GameCraft-Bench has tracked modifications or untracked files "
                "under runtime-relevant source/task/tool paths; use a clean "
                "checkout for reproducible runs. Set "
                "GAMELOOP_ALLOW_DIRTY_BENCH=1 only for local adapter "
                "development."
            )
        elif runtime.get("contract_errors"):
            report["error"] = "GameCraft-Bench API contract is incompatible"
        else:
            report["error"] = (
                "no usable filesystem backend; enable direct mode only on a trusted host"
            )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gameloop-gamecraft-doctor")
    parser.add_argument("--bench", type=Path, required=True)
    args = parser.parse_args(argv)
    report = inspect_bench_compatibility(args.bench)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
