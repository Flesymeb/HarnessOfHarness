#!/usr/bin/env python3
"""GameCraft-Bench adapter command for iterative development and evaluation.

The adapter does not patch GameCraft-Bench. It runs the configured harness in a
run-owned workspace, collects the benchmark's public evaluation artifacts, and
feeds concise observable feedback into the next attempt.
"""

from __future__ import annotations

import argparse
import datetime as dt
from functools import partial
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable

from gameloop.adapters.gamecraft_bench.artifacts import (
    archive_seed_game,
    build_screenshot_manifest,
    collect_job_results,
    empty_screenshot_manifest,
    find_demo_evidence_matrix,
    has_judge_infrastructure_failure,
    latest_trial,
    load_next_loop_evidence_report,
    load_next_loop_evidence_from_trial,
    parse_trial_result,
    summarize_breakdown,
    trial_seed_from_dir,
    validate_demo_trace_schema,
)
from gameloop.adapters.gamecraft_bench.adapter import inspect_data_contract
from gameloop.adapters.gamecraft_bench.experiments import (
    EXPERIMENT_SPECS,
    apply_experiment_environment,
)
from gameloop.adapters.gamecraft_bench.compat import inspect_bench_compatibility
from gameloop.adapters.gamecraft_bench.paths import (
    DEFAULT_BENCH,
    PROJECT_ROOT,
    RUNS_ROOT,
    TASK_WORKDIRS,
    copy_task_for_attempt,
    default_jobs_dir,
    ignore_generated_and_symlinks,
    normalize_task_arg,
    prepend_default_tool_paths,
    resolve_path,
    run_directory,
    slugify,
    validate_run_id,
)
from gameloop.adapters.gamecraft_bench.planner import (
    run_project_planner,
)
from gameloop.adapters.gamecraft_bench.prompts import (
    BASE_TEMPLATE,
    build_extra_instruction,
    build_visual_tester_prompt,
)
from gameloop.core.documents import (
    load_public_task_instruction,
    read_json,
    trim_public_task_instruction,
    write_json,
)
from gameloop.core.domain_policy import (
    domain_policy_manifest,
    render_domain_policy_guidance,
    select_domain_policies,
)
from gameloop.core.evidence import (
    build_demo_evidence_gap_issues,
    build_demo_evidence_matrix,
    build_loop_issues,
    build_loop_memory,
    build_public_execution_snapshot,
    build_verified_demo_claims,
    feedback_text,
)
from gameloop.core.benchmark_runner import run_benchmark_command
from gameloop.core.harness_runner import run_role_command as run_command_with_idle_timeout
from gameloop.core.integrity import candidate_source_sha256
from gameloop.core.mcp_evidence import (
    mcp_coverage_gaps,
    mcp_process_warnings,
    mcp_runtime_source_freshness_gaps,
    summarize_godot_mcp_evidence,
)
from gameloop.core.roles import (
    GodotMCPAccess,
    RoleBinding,
    RoleName,
    WorkspaceAccess,
    role_bindings_from_config,
)
from gameloop.core.runtime import GameLoopRuntime
from gameloop.core.prompts import (
    build_development_brief,
    build_development_doc_delta,
    build_development_document,
    build_loop_artifacts as _build_loop_artifacts,
    build_project_planner_evidence_packet,
    build_project_planner_prompt,
    write_loop_artifacts,
)
from gameloop.core.stages import loop_tag
from gameloop.env import load_runtime_env, project_env_defaults
from gameloop.harnesses import HarnessRuntime, default_harness_registry
from gameloop.harnesses.output import parse_harness_output
from gameloop.locations import PACKAGE_ROOT
from gameloop.tools.godot_docs import role_guidance as godot_docs_role_guidance
from gameloop.tools.godot_mcp import (
    cleanup_lifecycle_processes,
    doctor_payload as godot_mcp_doctor_payload,
    role_guidance as godot_mcp_role_guidance,
)
from gameloop.tools.godot_mcp_vendor import VENDOR_ROOT


build_loop_artifacts = partial(
    _build_loop_artifacts,
    method_name="GameCraft",
    task_source_name="GameCraft",
)

# A direct Harness runs on the host, where this global alias may have been
# left by an unrelated benchmark trial. Never let it redirect an agent to a
# different project.
HOST_GAME_ALIAS = Path("/workspace/game")


VISUAL_TESTER_REVIEW_STATUSES = {"pass", "partial", "fail", "blocked"}
VISUAL_TESTER_ENV_ALLOWLIST = {
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "DISPLAY",
    "GODOT_BIN",
    "GAMELOOP_GODOT_EDITOR_BIN",
    "GAMELOOP_TESTER_CONCURRENCY",
    "GAMELOOP_TESTER_LOCK_DIR",
    "GAMELOOP_GODOT_MCP_COMMAND",
    "GAMELOOP_GODOT_MCP_STARTUP_TIMEOUT_SECONDS",
    "GAMELOOP_GODOT_MAX_CPUS",
    "GAMELOOP_GODOT_MCP_STATE",
    "GAMELOOP_GODOT_DOCS_ROOT",
    "GAMELOOP_MCP_EVIDENCE_DIR",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "NODE_EXTRA_CA_CERTS",
    "NO_PROXY",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TERM",
    "TMPDIR",
    "TZ",
    "USER",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
}
VISUAL_TESTER_TOOL_ENV_ALLOWLIST = sorted(
    {
        "CODEX_HOME",
        "DISPLAY",
        "GODOT_BIN",
        "GAMELOOP_GODOT_EDITOR_BIN",
        "GAMELOOP_GODOT_MCP_STARTUP_TIMEOUT_SECONDS",
        "GAMELOOP_GODOT_MAX_CPUS",
        "GAMELOOP_GODOT_DOCS_ROOT",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "SHELL",
        "TERM",
        "TMPDIR",
        "TZ",
        "USER",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
    }
)


def subprocess_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


PACKAGED_BENCH_WRAPPER = (
    PACKAGE_ROOT / "resources" / "run_gamecraft_codex_bench.sh"
)


def _packaged_bench_wrapper() -> Path:
    source_entry = PROJECT_ROOT / "scripts" / "run_gamecraft_codex_bench.sh"
    if source_entry.is_file():
        return source_entry
    return PACKAGED_BENCH_WRAPPER


def _experiment_bench_wrapper(experiment_id: str) -> Path:
    spec = EXPERIMENT_SPECS[experiment_id]
    source = PROJECT_ROOT / "scripts" / spec.wrapper_name
    if source.is_file():
        return source
    packaged = PACKAGE_ROOT / "resources" / spec.wrapper_name
    if packaged.is_file():
        return packaged
    raise RuntimeError(
        f"benchmark wrapper for {experiment_id!r} is unavailable: {spec.wrapper_name}"
    )


def _runtime_command(
    name: str,
    *,
    environment: dict[str, str],
    source_name: str | None = None,
) -> Path:
    configured = environment.get(
        "GAMELOOP_GODOT_MCP_COMMAND" if name == "gameloop-godot-mcp" else ""
    )
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    discovered = shutil.which(name, path=environment.get("PATH"))
    if discovered:
        return Path(discovered).resolve()
    fallback = PROJECT_ROOT / "scripts" / (source_name or name)
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return fallback.resolve()
    # A wheel's console scripts live beside its Python executable.  Support
    # direct `/path/to/venv/bin/gameloop` invocation even when that venv has
    # not been activated and therefore is not yet present on PATH.
    # Do not resolve the interpreter symlink: venv/bin/python normally points
    # at the base interpreter, while its console scripts remain in venv/bin.
    sibling = Path(sys.executable).expanduser().absolute().parent / name
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling.resolve()
    raise RuntimeError(f"{name} executable is unavailable")


CODEX_INFRASTRUCTURE_MARKERS = (
    "invalid_refresh_token",
    "token_expired",
    "access token could not be refreshed",
    "failed to refresh token",
    "you've hit your usage limit",
    "usage limit",
    "model_not_found",
    "401 unauthorized",
)


def codex_infrastructure_failure(text: str) -> str | None:
    """Classify account/provider failures that product-loop fallback cannot fix."""

    lowered = text.lower()
    return next((marker for marker in CODEX_INFRASTRUCTURE_MARKERS if marker in lowered), None)


def trial_execution_error(trial: dict[str, Any] | None) -> dict[str, Any] | None:
    """Describe why a newly generated Harbor trial cannot seed another loop."""

    if trial is None:
        return {"type": "missing_trial", "message": "Harbor produced no trial result."}
    parse_error = trial.get("parse_error")
    if parse_error:
        return {
            "type": "invalid_trial_result",
            "message": str(parse_error),
        }
    exception_info = trial.get("exception_info")
    if exception_info is not None:
        return {
            "type": "trial_exception",
            "exception_info": exception_info,
        }
    trial_dir = Path(str(trial.get("trial_dir") or ""))
    trace_errors = validate_demo_trace_schema(trial_dir)
    if trace_errors:
        return {
            "type": "invalid_demo_trace_schema",
            "message": "Replay trace preflight failed.",
            "errors": trace_errors,
        }
    return None


def load_config_defaults(config_path: str | None) -> dict[str, Any]:
    if not config_path:
        return {}
    path = resolve_path(config_path, Path.cwd())
    data = read_json(path)
    data["_config_base"] = str(path.parent)
    return data


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def extract_visual_review_status(
    attempt_dir: Path,
    report_path: Path,
    trial_dir: Path | None = None,
) -> str | None:
    json_paths = [
        attempt_dir / "visual_playtest_report.json",
        report_path.with_suffix(".json"),
    ]
    if trial_dir is not None:
        trial_reports = trial_dir / "reports"
        game_dir = trial_dir / "sandbox" / "workspace" / "game"
        game_reports = game_dir / "reports"
        json_paths.extend(
            [
                trial_dir / "visual_playtest_report.json",
                trial_reports / "visual_playtest_report.json",
                trial_reports / "playtest" / "visual_playtest_report.json",
                game_dir / "visual_playtest_report.json",
                game_reports / "visual_playtest_report.json",
                game_reports / "playtest" / "visual_playtest_report.json",
            ]
        )

    for json_path in _dedupe_paths(json_paths):
        if not json_path.is_file():
            continue
        try:
            data = read_json(json_path)
        except Exception:
            data = {}
        if isinstance(data, dict):
            status = str(data.get("status") or data.get("review_status") or "").strip().lower()
            if status:
                return status
            if data.get("repair_required") is False:
                return "pass"

    markdown_paths = [report_path]
    if trial_dir is not None:
        markdown_paths.extend(
            [
                trial_dir / "visual_playtest_report.md",
                trial_reports / "visual_playtest_report.md",
                trial_reports / "playtest" / "visual_playtest_report.md",
                game_dir / "visual_playtest_report.md",
                game_reports / "visual_playtest_report.md",
                game_reports / "playtest" / "visual_playtest_report.md",
            ]
        )
    for markdown_path in _dedupe_paths(markdown_paths):
        if not markdown_path.is_file():
            continue
        status = _markdown_review_status(
            markdown_path.read_text(encoding="utf-8", errors="ignore")
        )
        if status is not None:
            return status
    return None


def _markdown_review_status(text: str) -> str | None:
    """Parse ordinary Markdown status labels without requiring one style."""

    match = re.search(
        r"(?i)(?:`?status`?|acceptance\s+result)\s*:\s*"
        r"[`\"']?(pass|partial|fail|blocked)\b",
        text,
    )
    return match.group(1).lower() if match else None


def tester_acceptance_passed(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    review_status = str(status.get("review_status") or "").strip().lower()
    if review_status:
        return review_status == "pass"
    if status.get("status") in {"dry_run", "skipped_no_trial"}:
        return True
    return False


def tester_failure_is_repairable(status: dict[str, Any] | None) -> bool:
    """Return whether another Developer pass can plausibly fix Tester output."""

    if not isinstance(status, dict):
        return False
    return status.get("status") not in {
        "infrastructure_failed",
        "invalid_candidate_mutation",
    } and not bool(
        status.get("timed_out")
    )


def tester_protocol_error(status: dict[str, Any] | None) -> dict[str, Any]:
    """Keep an authoritative candidate mutation distinct from transport failure."""

    state = status.get("status") if isinstance(status, dict) else None
    if state == "invalid_candidate_mutation":
        return {
            "type": "candidate_mutated_during_tester",
            "message": "Authoritative candidate source changed during QA Tester review.",
            "status": state,
        }
    return {
        "type": "tester_infrastructure_failure",
        "message": "QA Tester did not complete the required public runtime review.",
        "status": state,
        "infrastructure_error": (
            status.get("infrastructure_error") if isinstance(status, dict) else None
        ),
    }


def _visual_report_snapshot(
    attempt_dir: Path, report_path: Path, trial_dir: Path
) -> dict[Path, tuple[int, int]]:
    trial_reports = trial_dir / "reports"
    game_dir = trial_dir / "sandbox" / "workspace" / "game"
    game_reports = game_dir / "reports"
    paths = [
        report_path,
        attempt_dir / "visual_playtest_report.json",
        report_path.with_suffix(".json"),
        trial_dir / "visual_playtest_report.json",
        trial_dir / "visual_playtest_report.md",
        trial_reports / "visual_playtest_report.json",
        trial_reports / "visual_playtest_report.md",
        trial_reports / "playtest" / "visual_playtest_report.json",
        trial_reports / "playtest" / "visual_playtest_report.md",
        game_dir / "visual_playtest_report.json",
        game_dir / "visual_playtest_report.md",
        game_reports / "visual_playtest_report.json",
        game_reports / "visual_playtest_report.md",
        game_reports / "playtest" / "visual_playtest_report.json",
        game_reports / "playtest" / "visual_playtest_report.md",
    ]
    snapshot: dict[Path, tuple[int, int]] = {}
    for path in _dedupe_paths(paths):
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[path] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _fresh_visual_review_status(
    before: dict[Path, tuple[int, int]],
    attempt_dir: Path,
    report_path: Path,
    trial_dir: Path,
) -> str | None:
    after = _visual_report_snapshot(attempt_dir, report_path, trial_dir)
    changed = [path for path, state in after.items() if before.get(path) != state]
    for path in changed:
        if path.suffix.lower() == ".json":
            try:
                data = read_json(path)
            except Exception:
                continue
            status = str(
                data.get("status") or data.get("review_status") or ""
            ).strip().lower()
            if status in VISUAL_TESTER_REVIEW_STATUSES:
                return status
            if data.get("repair_required") is False:
                return "pass"
            continue
        status = _markdown_review_status(
            path.read_text(encoding="utf-8", errors="ignore")
        )
        if status is not None:
            return status
    return None


def _prepare_visual_tester_workspace(
    *,
    attempt_dir: Path,
    task_dir: Path,
    trial: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    """Copy only public tester inputs away from the scored trial."""

    source_trial_dir = Path(str(trial.get("trial_dir") or "")).resolve()
    source_game = source_trial_dir / "sandbox" / "workspace" / "game"
    if not source_game.is_dir():
        raise FileNotFoundError(f"tester game artifact missing: {source_game}")

    workspace = attempt_dir / "tester_workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    isolated_trial = workspace / "trial"
    isolated_game = isolated_trial / "sandbox" / "workspace" / "game"
    isolated_game.parent.mkdir(parents=True, exist_ok=True)

    def ignore_private_links(directory: str, names: list[str]) -> set[str]:
        ignored = set(
            shutil.ignore_patterns(".godot", "__pycache__", "*.tmp")(
                directory,
                names,
            )
        )
        ignored.update(
            name for name in names if (Path(directory) / name).is_symlink()
        )
        return ignored

    shutil.copytree(
        source_game,
        isolated_game,
        ignore=ignore_private_links,
    )

    source_demos = source_trial_dir / "verifier" / "demos"
    if source_demos.is_dir():
        shutil.copytree(
            source_demos,
            isolated_trial / "verifier" / "demos",
            ignore=ignore_private_links,
        )

    public_task_dir = workspace / "public-task"
    public_task_dir.mkdir(parents=True, exist_ok=True)
    public_instruction = load_public_task_instruction(task_dir).strip()
    (public_task_dir / "description.md").write_text(
        (public_instruction or "No additional public task text was available.") + "\n",
        encoding="utf-8",
    )

    isolated_trial_record = dict(trial)
    isolated_trial_record["trial_dir"] = str(isolated_trial)
    isolated_trial_record["trial_name"] = str(
        trial.get("trial_name") or source_trial_dir.name
    )
    manifest = build_screenshot_manifest(isolated_trial)
    return public_task_dir, isolated_trial, isolated_trial_record, manifest


def _reset_visual_tester_artifacts(attempt_dir: Path) -> None:
    for path in (
        attempt_dir / "local-fallback",
        attempt_dir / "tester_workspace",
        attempt_dir / "tester-mcp-evidence",
        attempt_dir / ".codex-tester-home",
        attempt_dir / ".opencode-tester-home",
        attempt_dir / ".pi-tester-home",
    ):
        if path.is_dir():
            shutil.rmtree(path)
    for path in (
        attempt_dir / "visual_playtest_report.json",
        attempt_dir / "visual_playtest_report.md",
        attempt_dir / "visual_tester_report.json",
        attempt_dir / "visual_tester_report.md",
        attempt_dir / "visual_playtest_status.json",
        attempt_dir / "visual_tester_prompt.md",
        attempt_dir / "visual_tester.stdout.log",
        attempt_dir / "visual_tester.stderr.log",
    ):
        path.unlink(missing_ok=True)
    for pattern in ("visual_tester.retry-*.stdout.log", "visual_tester.retry-*.stderr.log"):
        for path in attempt_dir.glob(pattern):
            path.unlink(missing_ok=True)


def _copy_visual_tester_reports(attempt_dir: Path, trial_dir: Path) -> None:
    """Promote tester reports from the disposable workspace into run evidence."""

    game_dir = trial_dir / "sandbox" / "workspace" / "game"
    candidates = {
        ".json": [
            trial_dir / "visual_playtest_report.json",
            trial_dir / "reports" / "visual_playtest_report.json",
            trial_dir / "reports" / "playtest" / "visual_playtest_report.json",
            game_dir / "visual_playtest_report.json",
            game_dir / "reports" / "visual_playtest_report.json",
            game_dir / "reports" / "playtest" / "visual_playtest_report.json",
        ],
        ".md": [
            trial_dir / "visual_playtest_report.md",
            trial_dir / "reports" / "visual_playtest_report.md",
            trial_dir / "reports" / "playtest" / "visual_playtest_report.md",
            game_dir / "visual_playtest_report.md",
            game_dir / "reports" / "visual_playtest_report.md",
            game_dir / "reports" / "playtest" / "visual_playtest_report.md",
        ],
    }
    for suffix, paths in candidates.items():
        existing = [path for path in paths if path.is_file()]
        if not existing:
            continue
        source = max(existing, key=lambda path: path.stat().st_mtime_ns)
        shutil.copy2(source, attempt_dir / f"visual_playtest_report{suffix}")


def _visual_tester_bwrap_prefix(
    *,
    attempt_dir: Path,
    source_task_dir: Path,
    source_trial_dir: Path,
    private_paths: Iterable[Path] = (),
    preserve_paths: Iterable[Path] = (),
    readonly_files: Iterable[tuple[Path, Path]] = (),
    allow_unisolated: bool | None = None,
) -> list[str]:
    """Hide private benchmark inputs while keeping the isolated copy writable."""

    readonly_files = tuple(readonly_files)
    if allow_unisolated is None:
        allow_unisolated = (
            os.environ.get("GAMELOOP_TESTER_ALLOW_UNISOLATED") == "1"
        )
    if allow_unisolated:
        attempt_resolved = attempt_dir.resolve()
        for source, destination in readonly_files:
            source = source.resolve()
            destination = destination.resolve()
            if not destination.is_relative_to(attempt_resolved):
                raise RuntimeError(
                    "unisolated Tester credential target must stay inside its attempt"
                )
            if not source.is_file():
                raise RuntimeError(f"Tester credential source is missing: {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            destination.chmod(0o600)
        return []

    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError(
            "bwrap is required for the isolated visual tester; "
            "refusing to expose the original benchmark task or trial"
        )
    prefix = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
    ]
    attempt_resolved = attempt_dir.resolve()
    hidden_paths = [
        source_task_dir,
        source_trial_dir,
        *private_paths,
        Path.home() / ".codex",
        Path.home() / ".agents",
        Path.home() / ".ssh",
        Path.home() / ".aws",
        Path.home() / ".config",
    ]
    hidden_dirs: list[Path] = []
    hidden_files: list[Path] = []
    for path in sorted(
        {candidate.resolve() for candidate in hidden_paths if candidate.exists()},
        key=lambda candidate: (len(candidate.parts), str(candidate)),
    ):
        if path == Path("/"):
            raise RuntimeError("refusing to mask the filesystem root")
        if any(path.is_relative_to(root) for root in hidden_dirs):
            continue
        if path.is_dir():
            hidden_dirs.append(path)
        else:
            hidden_files.append(path)

    for path in hidden_dirs:
        prefix.extend(["--tmpfs", str(path)])
    for path in hidden_files:
        prefix.extend(["--ro-bind", "/dev/null", str(path)])

    overlays: list[tuple[str, Path, Path]] = [
        ("--bind", attempt_resolved, attempt_resolved)
    ]
    for path in preserve_paths:
        resolved = path.resolve()
        if resolved.exists():
            overlays.append(("--ro-bind", resolved, resolved))
    for source, destination in readonly_files:
        overlays.append(("--ro-bind", source.resolve(), destination.resolve()))

    masked_roots = [Path("/tmp"), *hidden_dirs]
    created_dirs: set[Path] = set()
    for _, source, destination in overlays:
        target = destination if source.is_dir() else destination.parent
        containing_roots = [
            root for root in masked_roots if target.is_relative_to(root)
        ]
        if not containing_roots:
            continue
        root = max(containing_roots, key=lambda candidate: len(candidate.parts))
        relative = target.relative_to(root)
        current = root
        for part in relative.parts:
            current /= part
            if current not in created_dirs:
                prefix.extend(["--dir", str(current)])
                created_dirs.add(current)

    for option, source, destination in overlays:
        prefix.extend([option, str(source), str(destination)])

    for env_file in (
        PROJECT_ROOT / ".env",
        source_task_dir.parents[1] / ".env"
        if len(source_task_dir.parents) > 1
        else source_task_dir / ".env",
    ):
        if env_file.is_file():
            prefix.extend(["--ro-bind", "/dev/null", str(env_file.resolve())])
    x11_socket = Path("/tmp/.X11-unix")
    if x11_socket.is_dir():
        prefix.extend(
            ["--dir", str(x11_socket), "--ro-bind", str(x11_socket), str(x11_socket)]
        )
    prefix.append("--")
    return prefix


def _cleanup_visual_tester_readonly_files(
    readonly_files: Iterable[tuple[Path, Path]],
) -> None:
    for _, destination in readonly_files:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass


def _preflight_visual_tester_isolation(
    environment: dict[str, str] | None = None,
) -> None:
    """Fail before Developer work when the Tester sandbox cannot start."""

    role_env = environment or os.environ
    if role_env.get("GAMELOOP_TESTER_ALLOW_UNISOLATED") == "1":
        return
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError(
            "bwrap is required for the isolated visual tester; set "
            "GAMELOOP_TESTER_ALLOW_UNISOLATED=1 only when the sanitized tester "
            "copy may run without host filesystem isolation"
        )
    command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "true",
    ]
    try:
        probe = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            "visual tester bwrap preflight could not start; set "
            "GAMELOOP_TESTER_ALLOW_UNISOLATED=1 only for an explicitly trusted "
            "host and sanitized tester copy"
        ) from error
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip()
        raise RuntimeError(
            "visual tester bwrap preflight failed before Developer execution: "
            f"{detail or f'exit {probe.returncode}'}. Set "
            "GAMELOOP_TESTER_ALLOW_UNISOLATED=1 only for an explicitly trusted "
            "host and sanitized tester copy"
        )


def _transient_tester_transport_failure(stderr_path: Path) -> bool:
    try:
        text = stderr_path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return any(
        marker in text
        for marker in (
            "stream disconnected before completion",
            "error sending request for url",
            "connection reset by peer",
            "connection closed before message completed",
        )
    )


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    pre_args, _ = pre.parse_known_args(argv)
    env_defaults = project_env_defaults(PROJECT_ROOT)
    defaults = load_config_defaults(pre_args.config)
    wrapper_explicit = bool(defaults.get("wrapper")) or any(
        item == "--wrapper" or item.startswith("--wrapper=") for item in argv
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(**{k.replace("-", "_"): v for k, v in defaults.items()})
    parser.set_defaults(roles=defaults.get("roles"))
    parser.add_argument("--config", default=pre_args.config)
    bench_default = (
        defaults.get("bench")
        or env_defaults.get("GAMELOOP_BENCH")
        or DEFAULT_BENCH
    )
    parser.add_argument(
        "--bench",
        default=str(bench_default) if bench_default is not None else None,
        help=(
            "Path to an unmodified GameCraft-Bench checkout. Defaults to "
            "GAMELOOP_BENCH or the checkout providing the installed "
            "gamecraft_bench package."
        ),
    )
    parser.add_argument(
        "--jobs-dir",
        default=defaults.get("jobs_dir"),
    )
    parser.add_argument(
        "--task",
        default=defaults.get("task"),
        help="Task slug/path, e.g. tycoon-farm or tasks/tycoon-farm.",
    )
    parser.add_argument(
        "--wrapper",
        default=defaults.get("wrapper")
        or str(_packaged_bench_wrapper()),
    )
    parser.add_argument("--experiment-id", default=defaults.get("experiment_id"))
    parser.add_argument("--harness", default=defaults.get("harness"))
    parser.add_argument("--model", default=defaults.get("model"))
    parser.add_argument(
        "--developer-backend",
        choices=("harness", "harbor-legacy"),
        default=defaults.get("developer_backend", "harness"),
        help=(
            "Developer execution boundary. 'harness' runs the configured "
            "GameLoop Harness directly in a run-owned candidate workspace; "
            "'harbor-legacy' is retained only for compatibility."
        ),
    )
    parser.add_argument("--attempts", type=int, default=int(defaults.get("attempts", 1)))
    parser.add_argument(
        "--start-loop-index",
        type=int,
        default=int(defaults.get("start_loop_index", 1)),
        help="Document/job loop number for the first attempt. Use 2 to continue from an existing loop-1 trial.",
    )
    parser.add_argument(
        "--seed-trial-dir",
        default=defaults.get("seed_trial_dir"),
        help="Existing Harbor trial directory to copy as the warm-start baseline for the first loop.",
    )
    parser.add_argument("--mode", choices=["clean"], default="clean")
    parser.add_argument("--reasoning-effort", default=defaults.get("reasoning_effort"))
    parser.add_argument(
        "--planner-mode",
        choices=["harness", "template"],
        default=defaults.get("planner_mode", "harness"),
        help=(
            "Project Planner implementation. harness invokes the selected "
            "harness/model before every Developer pass; template preserves the "
            "legacy deterministic document generator."
        ),
    )
    parser.add_argument(
        "--planner-timeout-seconds",
        type=int,
        default=int(defaults.get("planner_timeout_seconds", 1200)),
        help="Project Planner wall timeout. Use 0 to disable the wall clock limit.",
    )
    parser.add_argument(
        "--planner-idle-timeout-seconds",
        type=int,
        default=int(defaults.get("planner_idle_timeout_seconds", 1800)),
        help="Kill Project Planner only after this many seconds without output.",
    )
    parser.add_argument(
        "--warm-start-best",
        action="store_true",
        default=bool(defaults.get("warm_start_best", False)),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--warm-start-latest",
        action="store_true",
        default=bool(defaults.get("warm_start_latest", False)),
    )
    parser.add_argument("--n-concurrent", type=int, default=defaults.get("n_concurrent"))
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Optional stable run identifier: 1-128 ASCII letters, digits, "
            "underscores, or hyphens; path separators are rejected."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--defer-verification",
        action=argparse.BooleanOptionalAction,
        default=bool(defaults.get("defer_verification", False)),
        help=(
            "Skip the benchmark verifier while developing loop stages. "
            "Archived trials can be scored asynchronously later."
        ),
    )
    parser.add_argument(
        "--external-verifier",
        action=argparse.BooleanOptionalAction,
        default=bool(defaults.get("external_verifier", True)),
        help=(
            "Run the GameLoop-owned verifier adapter after Harbor produces a "
            "candidate. This keeps optional judges out of GameCraft-Bench."
        ),
    )
    parser.add_argument(
        "--codex-login",
        action=argparse.BooleanOptionalAction,
        default=bool(defaults.get("codex_login", True)),
        help=(
            "Use the local ChatGPT/Codex login for agent calls and the codex-cli "
            "verifier judge. Use --no-codex-login to keep API-key/proxy mode."
        ),
    )
    parser.add_argument(
        "--llm-tester",
        action="store_true",
        default=bool(defaults.get("llm_tester", False)),
        help="Run a lightweight public-only LLM visual tester after each attempt.",
    )
    parser.add_argument(
        "--tester-policy",
        choices=["next-loop", "repair-then-next"],
        default=defaults.get("tester_policy", "next-loop"),
        help=(
            "Tester workflow. next-loop keeps the current behavior; "
            "repair-then-next runs bounded same-loop acceptance repair before "
            "the next-loop tester report."
        ),
    )
    parser.add_argument(
        "--max-inner-repairs",
        type=int,
        default=int(defaults.get("max_inner_repairs", 2)),
        help="Maximum same-loop developer repair passes for --tester-policy repair-then-next.",
    )
    parser.add_argument(
        "--require-developer-mcp-coverage",
        action=argparse.BooleanOptionalAction,
        default=bool(defaults.get("require_developer_mcp_coverage", False)),
        help=(
            "Reject candidates without complete Runtime-owned Developer Godot MCP "
            "receipts. Warm-started candidates require baseline and retest cycles."
        ),
    )
    parser.add_argument(
        "--tester-timeout-seconds",
        type=int,
        default=int(defaults.get("tester_timeout_seconds", 0)),
        help="LLM tester wall timeout. Use 0 to disable the wall clock limit.",
    )
    parser.add_argument(
        "--tester-idle-timeout-seconds",
        type=int,
        default=int(defaults.get("tester_idle_timeout_seconds", 1800)),
        help="Kill the LLM tester only after this many seconds without stdout/stderr activity.",
    )
    parser.add_argument("--stop-reward", type=float, default=None)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=(
            None
            if defaults.get("timeout_seconds") is None
            else int(defaults["timeout_seconds"])
        ),
        help=(
            "Wall timeout for each Developer Harness attempt. The example "
            "configuration uses one hour; omit it in a custom config only "
            "when an unbounded run is intentional."
        ),
    )
    parser.add_argument(
        "--developer-idle-timeout-seconds",
        type=int,
        default=int(defaults.get("developer_idle_timeout_seconds", 900)),
        help="Kill Developer only after this many seconds without output.",
    )
    args, passthrough = parser.parse_known_args(argv)

    configured_extra = defaults.get("extra_harbor_args") or []
    if not isinstance(configured_extra, list):
        parser.error("config extra_harbor_args must be a list")
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    passthrough = [str(item) for item in configured_extra] + passthrough
    if not args.bench:
        parser.error(
            "GameCraft-Bench was not found; pass --bench, set GAMELOOP_BENCH, "
            "or install gamecraft_bench from its checkout"
        )
    if not args.jobs_dir:
        args.jobs_dir = env_defaults.get("GAMELOOP_JOBS_DIR")
    if not args.jobs_dir:
        args.jobs_dir = str(default_jobs_dir(PROJECT_ROOT))

    if args.task is None:
        parser.error("--task is required unless provided by --config")
    identity = (args.experiment_id, args.harness, args.model)
    if any(identity) and not all(identity):
        parser.error(
            "--experiment-id, --harness, and --model must be provided together"
        )
    if all(identity):
        spec = EXPERIMENT_SPECS.get(args.experiment_id)
        if spec is None:
            parser.error(f"unknown --experiment-id: {args.experiment_id}")
        if spec.harness != args.harness or spec.model != args.model:
            parser.error(
                "experiment identity mismatch: "
                f"{args.experiment_id} requires harness={spec.harness} "
                f"and model={spec.model}"
            )
        if args.reasoning_effort is None:
            args.reasoning_effort = spec.reasoning_effort
    base_spec = EXPERIMENT_SPECS.get(args.experiment_id or "codex-gpt-5.5")
    if base_spec is None:
        parser.error(f"unknown --experiment-id: {args.experiment_id}")
    if not wrapper_explicit:
        args.wrapper = str(
            _experiment_bench_wrapper(args.experiment_id or "codex-gpt-5.5")
        )
    try:
        args.role_bindings = role_bindings_from_config(
            getattr(args, "roles", None),
            fallback_harness=args.harness or base_spec.harness,
            fallback_model=args.model or base_spec.model,
            fallback_reasoning_effort=args.reasoning_effort or base_spec.reasoning_effort,
        )
    except ValueError as error:
        parser.error(str(error))
    if args.experiment_id:
        mismatched_roles = [
            role.value
            for role, binding in args.role_bindings.items()
            if (binding.harness, binding.model)
            != (base_spec.harness, base_spec.model)
        ]
        if mismatched_roles:
            parser.error(
                "named experiment roles must use the same harness and model as "
                f"{args.experiment_id}: {', '.join(mismatched_roles)}"
            )
    registered_harnesses = set(default_harness_registry().ids())
    unsupported_harnesses = [
        f"{role.value}={binding.harness}"
        for role, binding in args.role_bindings.items()
        if binding.harness not in registered_harnesses
    ]
    if unsupported_harnesses:
        parser.error(
            "role harness is not registered in this installation: "
            + ", ".join(unsupported_harnesses)
            + "; available: "
            + (", ".join(sorted(registered_harnesses)) or "none")
        )
    if args.mode != "clean":
        parser.error("--mode must be clean; rubric-aware optimization is not supported")
    if args.attempts < 1:
        parser.error("--attempts must be >= 1")
    if args.start_loop_index < 1:
        parser.error("--start-loop-index must be >= 1")
    if args.n_concurrent is not None and args.n_concurrent < 1:
        parser.error("--n-concurrent must be >= 1")
    if args.timeout_seconds is not None and args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be >= 1")
    if args.developer_idle_timeout_seconds < 1:
        parser.error("--developer-idle-timeout-seconds must be >= 1")
    if args.tester_timeout_seconds < 0:
        parser.error("--tester-timeout-seconds must be >= 0; use 0 to disable wall timeout")
    if args.tester_idle_timeout_seconds < 1:
        parser.error("--tester-idle-timeout-seconds must be >= 1")
    if args.planner_timeout_seconds < 0:
        parser.error("--planner-timeout-seconds must be >= 0; use 0 to disable wall timeout")
    if args.planner_idle_timeout_seconds < 1:
        parser.error("--planner-idle-timeout-seconds must be >= 1")
    if args.max_inner_repairs < 0:
        parser.error("--max-inner-repairs must be >= 0")
    if args.warm_start_best:
        parser.error(
            "--warm-start-best is not supported by the comparable-score protocol; "
            "use --warm-start-latest for sequential iteration."
        )
    if args.tester_policy == "repair-then-next":
        args.llm_tester = True
    return args, passthrough


def _visual_tester_harness_command(
    *,
    experiment_id: str,
    attempt_dir: Path,
    trial_dir: Path,
    prompt: str,
    report_path: Path,
    parent_env: dict[str, str],
    reasoning_effort: str | None,
    role_binding: RoleBinding | None = None,
) -> tuple[
    list[str],
    str,
    dict[str, str],
    list[Path],
    list[tuple[Path, Path]],
]:
    """Build a QA Tester command from the run's harness--model identity."""

    try:
        spec = EXPERIMENT_SPECS[experiment_id]
    except KeyError as error:
        raise ValueError(f"unknown visual tester experiment: {experiment_id}") from error

    binding = role_binding or RoleBinding(
        role=RoleName.TESTER,
        harness=spec.harness,
        model=spec.model,
        reasoning_effort=reasoning_effort or spec.reasoning_effort or "high",
        workspace_access=WorkspaceAccess.READ_ONLY,
        godot_mcp=GodotMCPAccess.READ_ONLY_RUNTIME,
    )
    if binding.role is not RoleName.TESTER:
        raise ValueError("QA Tester requires a tester role binding")

    role_env = dict(parent_env)
    tester_env = {
        key: value
        for key, value in role_env.items()
        if key in VISUAL_TESTER_ENV_ALLOWLIST
    }
    preserved_paths: list[Path] = []
    readonly_files: list[tuple[Path, Path]] = []
    effort = binding.reasoning_effort or reasoning_effort or spec.reasoning_effort or "high"

    # PROJECT_ROOT is masked from the isolated tester. Re-expose only the
    # public, read-only tool bundle required by this role, never the complete
    # repository, run history, or local configuration.
    if binding.godot_docs:
        docs_command = _runtime_command(
            "gameloop-godot-docs", environment=role_env
        )
        preserved_paths.extend(
            (
                docs_command,
                PACKAGE_ROOT,
            )
        )
    if binding.godot_mcp is not GodotMCPAccess.DISABLED:
        mcp_command = _runtime_command(
            "gameloop-godot-mcp", environment=role_env
        )
        role_env["GAMELOOP_GODOT_MCP_COMMAND"] = str(mcp_command)
        tester_env["GAMELOOP_GODOT_MCP_COMMAND"] = str(mcp_command)
        preserved_paths.extend(
            (
                mcp_command,
                PACKAGE_ROOT,
                VENDOR_ROOT,
            )
        )

    if binding.harness == "codex":
        explicit_codex = role_env.get("GAMELOOP_CODEX_REAL_BIN")
        if explicit_codex:
            explicit_path = Path(explicit_codex).expanduser().resolve()
            if not explicit_path.is_file() or not os.access(explicit_path, os.X_OK):
                raise RuntimeError(
                    "GAMELOOP_CODEX_REAL_BIN must name an executable Codex binary"
                )
            tester_env["PATH"] = os.pathsep.join(
                (str(explicit_path.parent), tester_env.get("PATH", ""))
            ).rstrip(os.pathsep)
        executable = shutil.which("codex", path=tester_env.get("PATH"))
        if not executable:
            raise RuntimeError("codex CLI is required for the Codex QA Tester")
        preserved_paths.append(Path(executable))
        extra_config: list[str] = []
        tester_base_url = role_env.get("GAMELOOP_TESTER_BASE_URL", "").rstrip("/")
        if tester_base_url:
            tester_api_key_env = role_env.get(
                "GAMELOOP_TESTER_API_KEY_ENV", "GAMELOOP_TESTER_API_KEY"
            )
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tester_api_key_env):
                raise ValueError(
                    "GAMELOOP_TESTER_API_KEY_ENV must name an environment variable"
                )
            tester_api_key = role_env.get(tester_api_key_env)
            if not tester_api_key:
                raise ValueError(
                    f"{tester_api_key_env} is required for the visual tester"
                )
            tester_home = attempt_dir / ".codex-tester-home"
            tester_home.mkdir(parents=True, exist_ok=True)
            tester_env.update(
                {
                    "CODEX_HOME": str(tester_home),
                    "HOME": str(tester_home),
                    "XDG_CONFIG_HOME": str(tester_home / ".config"),
                    "XDG_DATA_HOME": str(tester_home / ".local" / "share"),
                    tester_api_key_env: tester_api_key,
                }
            )
            extra_config.extend(
                [
                    'model_provider="gameloop_tester"',
                    'model_providers.gameloop_tester.name="GameLoop Tester"',
                    (
                        "model_providers.gameloop_tester.base_url="
                        f"{json.dumps(tester_base_url)}"
                    ),
                    (
                        "model_providers.gameloop_tester.env_key="
                        f"{json.dumps(tester_api_key_env)}"
                    ),
                    'model_providers.gameloop_tester.wire_api="responses"',
                    "model_providers.gameloop_tester.requires_openai_auth=false",
                ]
            )
        else:
            auth_root = Path(
                role_env.get("CODEX_HOME") or (Path.home() / ".codex")
            ).expanduser()
            auth_source = auth_root / "auth.json"
            if not auth_source.is_file():
                raise RuntimeError(
                    "official Codex login fallback requires a local auth.json"
                )
            tester_home = attempt_dir / ".codex-tester-home"
            tester_home.mkdir(parents=True, exist_ok=True)
            auth_target = tester_home / "auth.json"
            auth_target.touch(mode=0o600, exist_ok=True)
            tester_env.update(
                {
                    "CODEX_HOME": str(tester_home),
                    "HOME": str(tester_home),
                    "XDG_CONFIG_HOME": str(tester_home / ".config"),
                    "XDG_DATA_HOME": str(tester_home / ".local" / "share"),
                }
            )
            readonly_files.append((auth_source, auth_target))
        extra_config.extend(
            [
                'shell_environment_policy.inherit="core"',
                (
                    "shell_environment_policy.include_only="
                    f"{json.dumps(VISUAL_TESTER_TOOL_ENV_ALLOWLIST)}"
                ),
                "allow_login_shell=false",
            ]
        )
        prepared = HarnessRuntime().prepare_role(
            binding=RoleBinding(
                role=binding.role,
                harness=binding.harness,
                model=binding.model,
                reasoning_effort=effort,
                workspace_access=binding.workspace_access,
                godot_mcp=binding.godot_mcp,
                godot_docs=binding.godot_docs,
            ),
            workspace=trial_dir,
            prompt_path=attempt_dir / "visual_tester_prompt.md",
            output_path=report_path,
            environment=tester_env,
            json_stream=True,
            # The authoritative candidate is copied into a disposable,
            # bubblewrap-isolated QA workspace. Codex may write reports in
            # that copy while the source candidate remains read-only.
            sandbox_mode="danger-full-access",
            extra_config=tuple(extra_config),
        )
        preserved_paths.extend(prepared.preserved_paths)
        return (
            list(prepared.command),
            "codex",
            dict(prepared.environment),
            _dedupe_paths(preserved_paths),
            readonly_files,
        )

    credential_names = {
        "opencode": ("BAILIAN_API_KEY", "BAILIAN_BASE_URL"),
        "pi": (
            "PJLAB_API_KEY",
            "PJLAB_API_KEY_FILE",
            "PJLAB_BASE_URL",
            "GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS",
        ),
        "deepseek-harness": (
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY_FILE",
            "DEEPSEEK_BASE_URL",
            "GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS",
            "DSH_AGENT_PRESET",
            "DSH_MAX_TOKENS",
            "DSH_REASONING_EFFORT",
            "DSH_TURN_RETRY_LIMIT",
            "GAMELOOP_DSH_STANDARD_RUNTIME",
        ),
    }
    for name in credential_names.get(binding.harness, ()):
        if role_env.get(name):
            tester_env[name] = role_env[name]
    tester_env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(SRC_ROOT), role_env.get("PYTHONPATH", "")) if part
    )
    prepared = HarnessRuntime().prepare_role(
        binding=RoleBinding(
            role=binding.role,
            harness=binding.harness,
            model=binding.model,
            reasoning_effort=effort,
            workspace_access=binding.workspace_access,
            godot_mcp=binding.godot_mcp,
            godot_docs=binding.godot_docs,
        ),
        workspace=trial_dir,
        prompt_path=attempt_dir / "visual_tester_prompt.md",
        output_path=report_path,
        environment=tester_env,
        json_stream=True,
    )
    preserved_paths.extend(prepared.preserved_paths)
    if binding.harness in {"pi", "deepseek-harness"}:
        preserved_paths.append(SRC_ROOT)
    return (
        list(prepared.command),
        prepared.output_mode,
        dict(prepared.environment),
        _dedupe_paths(preserved_paths),
        readonly_files,
    )


def run_visual_tester(
    *,
    attempt_dir: Path,
    loop_index: int,
    task_dir: Path,
    trial: dict[str, Any] | None,
    development_document: str,
    tester_timeout_seconds: int,
    tester_idle_timeout_seconds: int,
    dry_run: bool,
    model: str | None,
    tester_phase: str = "next_loop",
    final_iteration: bool = False,
    private_paths: Iterable[Path] = (),
    environment: dict[str, str] | None = None,
    experiment_id: str = "codex-gpt-5.5",
    reasoning_effort: str | None = None,
    role_binding: RoleBinding | None = None,
    domain_policy_guidance: str = "",
) -> dict[str, Any]:
    attempt_dir = attempt_dir.expanduser().resolve()
    task_dir = task_dir.expanduser().resolve()
    try:
        spec = EXPERIMENT_SPECS[experiment_id]
    except KeyError as error:
        raise ValueError(f"unknown visual tester experiment: {experiment_id}") from error
    mcp_coverage_required = (
        role_binding is not None
        and role_binding.godot_mcp is not GodotMCPAccess.DISABLED
    )
    binding = role_binding or RoleBinding(
        role=RoleName.TESTER,
        harness=spec.harness,
        model=spec.model,
        reasoning_effort=reasoning_effort or spec.reasoning_effort or "high",
        workspace_access=WorkspaceAccess.READ_ONLY,
        godot_mcp=GodotMCPAccess.READ_ONLY_RUNTIME,
    )
    if binding.role is not RoleName.TESTER:
        raise ValueError("QA Tester requires a tester role binding")
    attempt_dir.mkdir(parents=True, exist_ok=True)
    _reset_visual_tester_artifacts(attempt_dir)
    source_trial_dir = Path(str((trial or {}).get("trial_dir") or ""))
    source_task_dir = task_dir
    tester_trial = trial
    if not trial or not source_trial_dir.exists():
        trial_dir = source_trial_dir
        manifest = empty_screenshot_manifest(trial_dir)
    else:
        task_dir, trial_dir, tester_trial, manifest = _prepare_visual_tester_workspace(
            attempt_dir=attempt_dir,
            task_dir=task_dir,
            trial=trial,
        )

    write_json(attempt_dir / "screenshot_manifest.json", manifest)
    prompt = build_visual_tester_prompt(
        loop_index=loop_index,
        task_dir=task_dir,
        trial=tester_trial,
        development_document=development_document,
        screenshot_manifest=manifest,
        tester_phase=tester_phase,
        final_iteration=final_iteration,
    )
    if domain_policy_guidance:
        prompt = prompt.rstrip() + "\n\n" + domain_policy_guidance.strip() + "\n"
    prompt_path = attempt_dir / "visual_tester_prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    report_path = attempt_dir / "visual_playtest_report.md"
    stdout_path = attempt_dir / "visual_tester.stdout.log"
    stderr_path = attempt_dir / "visual_tester.stderr.log"
    status_path = attempt_dir / "visual_playtest_status.json"

    if dry_run:
        report_path.write_text(
            "Dry run only. The QA Tester prompt was written but the harness was not invoked.\n",
            encoding="utf-8",
        )
        status = {
            "status": "dry_run",
            "tester_phase": tester_phase,
            "final_iteration": final_iteration,
            "experiment_id": experiment_id,
            "harness": binding.harness,
            "model": binding.model,
            "review_status": "pass",
            "returncode": 0,
            "timed_out": False,
            "idle_timed_out": False,
            "wall_timed_out": False,
            "prompt": str(prompt_path),
            "report": str(report_path),
        }
        write_json(status_path, status)
        return status

    if not trial or not trial_dir.exists():
        report_path.write_text(
            "No completed trial directory was available for LLM visual testing.\n",
            encoding="utf-8",
        )
        status = {
            "status": "skipped_no_trial",
            "tester_phase": tester_phase,
            "final_iteration": final_iteration,
            "experiment_id": experiment_id,
            "harness": binding.harness,
            "model": binding.model,
            "review_status": "blocked",
            "returncode": 0,
            "timed_out": False,
            "idle_timed_out": False,
            "wall_timed_out": False,
            "prompt": str(prompt_path),
            "report": str(report_path),
        }
        write_json(status_path, status)
        return status

    parent_env = dict(environment or os.environ)
    if "GAMELOOP_GODOT_MCP_COMMAND" not in parent_env:
        parent_env["GAMELOOP_GODOT_MCP_COMMAND"] = str(
            _runtime_command("gameloop-godot-mcp", environment=parent_env)
        )
    tester_mcp_evidence_dir = (
        attempt_dir / "tester-mcp-evidence"
    ).resolve()
    parent_env["GAMELOOP_MCP_EVIDENCE_DIR"] = str(tester_mcp_evidence_dir)
    if model is not None and model != binding.model:
        raise ValueError(
            "QA Tester model must match the run configuration: "
            f"expected {binding.model!r}, received {model!r}"
        )
    (
        harness_cmd,
        output_mode,
        tester_env,
        preserved_paths,
        readonly_files,
    ) = _visual_tester_harness_command(
        experiment_id=experiment_id,
        attempt_dir=attempt_dir,
        trial_dir=trial_dir,
        prompt=prompt,
        report_path=report_path,
        parent_env=parent_env,
        reasoning_effort=reasoning_effort,
        role_binding=binding,
    )
    cmd = [
        *_visual_tester_bwrap_prefix(
            attempt_dir=attempt_dir,
            source_task_dir=source_task_dir,
            source_trial_dir=source_trial_dir,
            private_paths=private_paths,
            preserve_paths=preserved_paths,
            readonly_files=readonly_files,
            allow_unisolated=(
                parent_env.get("GAMELOOP_TESTER_ALLOW_UNISOLATED") == "1"
            ),
        ),
        *harness_cmd,
    ]

    # Integrity protects the authoritative Developer candidate.  The Tester runs
    # against a disposable copy where GameLoop itself vendors the MCP addon,
    # enables the plugin, and lets Godot refresh import metadata; hashing that
    # managed copy would misclassify normal runtime setup as Tester mutation.
    authoritative_candidate_game_dir = (
        source_trial_dir / "sandbox" / "workspace" / "game"
    )
    candidate_hash_before = candidate_source_sha256(authoritative_candidate_game_dir)
    try:
        max_attempts = int(parent_env.get("GAMELOOP_TESTER_MAX_ATTEMPTS", "2"))
    except ValueError:
        max_attempts = 2
    max_attempts = max(1, min(max_attempts, 5))
    command_attempts: list[dict[str, Any]] = []
    mcp_cleanup: list[dict[str, Any]] = []
    result = None
    review_status = None
    recovered_transport_error = False
    final_stdout_path = stdout_path
    final_stderr_path = stderr_path

    for command_attempt in range(1, max_attempts + 1):
        final_stdout_path = (
            stdout_path
            if command_attempt == 1
            else attempt_dir / f"visual_tester.retry-{command_attempt:02d}.stdout.log"
        )
        final_stderr_path = (
            stderr_path
            if command_attempt == 1
            else attempt_dir / f"visual_tester.retry-{command_attempt:02d}.stderr.log"
        )
        before = _visual_report_snapshot(attempt_dir, report_path, trial_dir)
        try:
            result = run_command_with_idle_timeout(
                cmd,
                cwd=trial_dir,
                stdout_path=final_stdout_path,
                stderr_path=final_stderr_path,
                wall_timeout_seconds=None
                if tester_timeout_seconds <= 0
                else float(tester_timeout_seconds),
                idle_timeout_seconds=tester_idle_timeout_seconds,
                env=tester_env,
                stdin_path=prompt_path if output_mode == "codex" else None,
            )
        except Exception:
            _cleanup_visual_tester_readonly_files(readonly_files)
            raise
        finally:
            mcp_cleanup.append(
                cleanup_lifecycle_processes(tester_mcp_evidence_dir)
            )
        usage = None
        if output_mode != "codex":
            output_text, usage = parse_harness_output(
                output_mode,
                stdout_path=final_stdout_path,
                output_path=report_path,
            )
            if output_mode != "dsh" and output_text.strip():
                report_path.write_text(
                    output_text.strip() + "\n", encoding="utf-8"
                )
        review_status = extract_visual_review_status(
            attempt_dir, report_path, trial_dir
        )
        fresh_review_status = _fresh_visual_review_status(
            before, attempt_dir, report_path, trial_dir
        )
        fresh_report = fresh_review_status in VISUAL_TESTER_REVIEW_STATUSES
        if fresh_report:
            review_status = fresh_review_status
        command_attempts.append(
            {
                "attempt": command_attempt,
                "returncode": result.returncode,
                "timed_out": result.timed_out,
                "fresh_report": fresh_report,
                "usage": usage,
                "stdout_log": str(final_stdout_path),
                "stderr_log": str(final_stderr_path),
                "mcp_cleanup": mcp_cleanup[-1],
            }
        )
        if result.returncode == 0:
            break
        if review_status in VISUAL_TESTER_REVIEW_STATUSES and fresh_report:
            recovered_transport_error = True
            break
        if (
            command_attempt >= max_attempts
            or result.timed_out
            or not _transient_tester_transport_failure(final_stderr_path)
        ):
            break
        time.sleep(min(5 * command_attempt, 15))

    assert result is not None
    # The isolated path uses a read-only bind over an empty placeholder. The
    # explicitly trusted direct fallback must stage a private copy instead;
    # remove either form as soon as Codex exits so run artifacts never retain
    # a reusable login credential.
    _cleanup_visual_tester_readonly_files(readonly_files)
    _copy_visual_tester_reports(attempt_dir, trial_dir)
    mcp_observation = summarize_godot_mcp_evidence(tester_mcp_evidence_dir)
    mcp_gaps = (
        mcp_coverage_gaps(mcp_observation, role="tester")
        if mcp_coverage_required
        else []
    )
    candidate_hash_after = candidate_source_sha256(authoritative_candidate_game_dir)
    candidate_unchanged = candidate_hash_before == candidate_hash_after
    review_status = extract_visual_review_status(
        attempt_dir, report_path, trial_dir
    ) or review_status
    effective_returncode = 0 if recovered_transport_error else result.returncode
    infrastructure_marker = codex_infrastructure_failure(
        "\n".join(
            (
                subprocess_text(final_stdout_path.read_text(encoding="utf-8", errors="ignore"))
                if final_stdout_path.is_file()
                else "",
                subprocess_text(final_stderr_path.read_text(encoding="utf-8", errors="ignore"))
                if final_stderr_path.is_file()
                else "",
            )
        )
    )
    if infrastructure_marker:
        tester_status = "infrastructure_failed"
        effective_returncode = effective_returncode or 1
    elif not candidate_unchanged:
        tester_status = "invalid_candidate_mutation"
        effective_returncode = effective_returncode or 1
    elif effective_returncode == 0 and mcp_gaps:
        tester_status = "invalid_mcp_coverage"
        effective_returncode = 1
    elif effective_returncode != 0:
        tester_status = "failed"
    elif review_status not in VISUAL_TESTER_REVIEW_STATUSES:
        tester_status = "invalid_report"
    else:
        tester_status = "completed"
    status = {
        "status": tester_status,
        "tester_phase": tester_phase,
        "final_iteration": final_iteration,
        "experiment_id": experiment_id,
        "harness": binding.harness,
        "model": binding.model,
        "review_status": review_status,
        "returncode": effective_returncode,
        "process_returncode": result.returncode,
        "transport_recovered": recovered_transport_error,
        "infrastructure_error": infrastructure_marker,
        "command_attempts": command_attempts,
        "timed_out": result.timed_out,
        "idle_timed_out": result.idle_timed_out,
        "wall_timed_out": result.wall_timed_out,
        "prompt": str(prompt_path),
        "report": str(report_path),
        "stdout_log": str(final_stdout_path),
        "stderr_log": str(final_stderr_path),
        "tester_workspace": str(trial_dir.parent),
        "candidate_source_sha256_before": candidate_hash_before,
        "candidate_source_sha256_after": candidate_hash_after,
        "candidate_source_unchanged": candidate_unchanged,
        "mcp_observation": mcp_observation,
        "mcp_coverage_gaps": mcp_gaps,
        "mcp_cleanup": mcp_cleanup,
        "filesystem_isolation": (
            "bwrap-isolated-copy" if cmd and Path(cmd[0]).name == "bwrap" else "isolated-copy"
        ),
    }
    write_json(status_path, status)
    return status


def command_has_reasoning_effort(args: list[str]) -> bool:
    for index, item in enumerate(args):
        if item.startswith("reasoning_effort="):
            return True
        if item == "--ak" and index + 1 < len(args) and args[index + 1].startswith("reasoning_effort="):
            return True
        if item.startswith("--ak=reasoning_effort="):
            return True
    return False


def build_command(
    *,
    bench: Path,
    wrapper: str,
    task_arg: str,
    job_name: str,
    extra_instruction: Path,
    reasoning_effort: str | None,
    n_concurrent: int | None,
    passthrough: list[str],
    disable_verification: bool = False,
    mcp_config: Path | None = None,
) -> list[str]:
    wrapper_path = Path(wrapper)
    if not wrapper_path.is_absolute():
        project_wrapper = PROJECT_ROOT / wrapper_path
        wrapper_path = project_wrapper if project_wrapper.is_file() else bench / wrapper_path
    # Wheel archives do not preserve the executable bit of package-data
    # resources.  Invoke only our packaged shell resource through bash;
    # external wrappers retain their normal executable contract.
    packaged_resources = PACKAGE_ROOT / "resources"
    cmd = (
        ["bash", str(wrapper_path)]
        if wrapper_path.parent == packaged_resources
        else [str(wrapper_path)]
    )
    cmd.extend([
        "--job-name",
        job_name,
        "-p",
        task_arg,
        "--extra-instruction-path",
        str(extra_instruction),
    ])
    if disable_verification:
        cmd.append("--disable-verification")
    if mcp_config is not None:
        cmd.extend(["--mcp-config", str(mcp_config)])
    if n_concurrent is not None:
        cmd.extend(["-n", str(n_concurrent)])
    if reasoning_effort and not command_has_reasoning_effort(passthrough):
        cmd.append(f"--ak=reasoning_effort={reasoning_effort}")
    cmd.extend(passthrough)
    return cmd


def write_developer_mcp_config(
    *,
    attempt_dir: Path,
    environment: dict[str, str],
    role_binding: RoleBinding,
) -> Path | None:
    if role_binding.godot_mcp is GodotMCPAccess.DISABLED:
        return None
    if role_binding.role is not RoleName.DEVELOPER:
        raise ValueError("developer MCP config requires a developer role binding")
    mcp_env = {
        "GAMELOOP_MCP_EVIDENCE_DIR": str((attempt_dir / "mcp-evidence").resolve()),
    }
    for name in (
        "DISPLAY",
        "GAMELOOP_GODOT_EDITOR_BIN",
        "GAMELOOP_GODOT_MCP_STARTUP_TIMEOUT_SECONDS",
        "GAMELOOP_GODOT_MAX_CPUS",
        "GAMELOOP_GODOT_DOCS_ROOT",
        "GODOT_BIN",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
    ):
        if environment.get(name):
            mcp_env[name] = environment[name]
    if not mcp_env.get("GAMELOOP_GODOT_EDITOR_BIN"):
        editor_bin = shutil.which("godot", path=environment.get("PATH"))
        if editor_bin:
            mcp_env["GAMELOOP_GODOT_EDITOR_BIN"] = str(Path(editor_bin).resolve())
    launcher = attempt_dir / "developer-godot-mcp"
    launcher_lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    launcher_lines.extend(
        f"export {name}={shlex.quote(value)}"
        for name, value in sorted(mcp_env.items())
    )
    launcher_lines.extend(
        [
            "",
            "exec "
            + shlex.quote(
                str(_runtime_command("gameloop-godot-mcp", environment=environment))
            )
            + " serve",
        ]
    )
    launcher.write_text("\n".join(launcher_lines) + "\n", encoding="utf-8")
    launcher.chmod(0o700)
    path = attempt_dir / "developer.mcp.json"
    write_json(
        path,
        {
            "mcpServers": {
                "godot_mcp": {
                    # Harbor 0.15 serializes stdio command + args as one
                    # executable string in Codex config. Use a no-argument
                    # wrapper so both Harbor and native MCP clients resolve a
                    # real executable path.
                    "command": str(launcher),
                    "args": [],
                    "env": mcp_env,
                }
            }
        },
    )
    return path


def run_harbor_attempt(
    *,
    cmd: list[str],
    bench: Path,
    env: dict[str, str],
    timeout_seconds: int | None,
) -> tuple[int, str, str, bool]:
    """Compatibility name for the adapter's benchmark backend invocation.

    The actual process-group supervision is benchmark-neutral and lives in
    ``gameloop.core.benchmark_runner``.  Existing tests and old scripts may
    still monkeypatch this compatibility seam while new adapters use the Core
    function directly.
    """

    returncode, stdout, stderr, timed_out = run_benchmark_command(
        cmd,
        cwd=bench,
        environment=env,
        timeout_seconds=timeout_seconds,
    )
    if timed_out:
        stderr = (
            stderr.rstrip()
            + "\n"
            + f"[gamecraft-loop] Timed out after {timeout_seconds} seconds while running Harbor attempt.\n"
        )
    return returncode, stdout, stderr, timed_out


def prepare_direct_candidate_trial(
    *,
    attempt_dir: Path,
    previous_candidate: dict[str, Any] | None,
) -> tuple[Path, Path]:
    """Create the run-owned workspace edited by the Developer Harness."""

    trial_dir = attempt_dir / "candidate-trial"
    game_dir = trial_dir / "sandbox" / "workspace" / "game"
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    game_dir.mkdir(parents=True, exist_ok=True)
    if previous_candidate is not None:
        previous_trial = Path(str(previous_candidate.get("trial_dir") or ""))
        previous_game = previous_trial / "sandbox" / "workspace" / "game"
        if previous_game.is_dir():
            shutil.rmtree(game_dir)
            shutil.copytree(
                previous_game,
                game_dir,
                ignore=ignore_generated_and_symlinks,
            )
    return trial_dir, game_dir


def direct_candidate_record(trial_dir: Path) -> dict[str, Any]:
    game_dir = trial_dir / "sandbox" / "workspace" / "game"
    demo_count = len(list((game_dir / "demo_outputs").glob("*.json")))
    return {
        "trial_name": trial_dir.name,
        "trial_dir": str(trial_dir),
        "reward": None,
        "evaluated": False,
        "breakdown_summary": {
            "reward": None,
            "build_ok": (game_dir / "project.godot").is_file(),
            "judge": None,
            "errors": [],
            "num_demos": demo_count,
        },
    }


def run_direct_developer_harness(
    *,
    attempt_dir: Path,
    game_dir: Path,
    prompt_path: Path,
    environment: dict[str, str],
    binding: RoleBinding,
    timeout_seconds: int | None,
    idle_timeout_seconds: int,
    dry_run: bool,
) -> tuple[int, str, str, bool]:
    """Invoke Developer through HarnessRuntime, never through GameCraft/Harbor."""

    stdout_path = attempt_dir / "developer.stdout.log"
    stderr_path = attempt_dir / "developer.stderr.log"
    output_path = attempt_dir / "developer.output.md"
    if dry_run:
        return 0, "[dry-run] Developer Harness not executed\n", "", False
    candidate_project = game_dir.resolve(strict=True)
    if HOST_GAME_ALIAS.exists() or HOST_GAME_ALIAS.is_symlink():
        alias_target = HOST_GAME_ALIAS.resolve()
        if alias_target != candidate_project:
            raise RuntimeError(
                f"Host alias {HOST_GAME_ALIAS} points to {alias_target}, "
                f"outside this run's candidate {candidate_project}. "
                "Remove the stale alias before starting the direct Developer."
            )
    # GameCraft's virtual /workspace/game belongs to its sandbox. A direct
    # Developer runs on the host, so bind every occurrence to this run's
    # candidate rather than allowing an unrelated host path to be read.
    bound_prompt_path = attempt_dir / "developer.bound-prompt.md"
    original_prompt = prompt_path.read_text(encoding="utf-8")
    bound_prompt_path.write_text(
        original_prompt.replace("/workspace/game", str(candidate_project)),
        encoding="utf-8",
    )
    role_env = dict(environment)
    # HarnessRuntime executes Codex with the candidate project itself as cwd.
    # The generic MCP launcher otherwise chooses ``cwd/game`` while waiting for
    # a cold project, which leaves a direct Developer run blocked at startup.
    role_env["GAMELOOP_GODOT_PROJECT"] = str(candidate_project)
    role_env["GAMELOOP_MCP_EVIDENCE_DIR"] = str(
        (attempt_dir / "mcp-evidence").resolve()
    )
    mcp_launcher = attempt_dir / "developer-godot-mcp"
    if mcp_launcher.is_file():
        role_env["GAMELOOP_GODOT_MCP_COMMAND"] = str(mcp_launcher.resolve())
    harness_runtime = HarnessRuntime()
    prepared = harness_runtime.prepare_role(
        binding=binding,
        workspace=game_dir,
        prompt_path=bound_prompt_path,
        output_path=output_path,
        environment=role_env,
        json_stream=True,
        sandbox_mode=(
            "danger-full-access"
            if role_env.get("GAMELOOP_ALLOW_UNISOLATED_DEVELOPER") == "1"
            else "workspace-write"
        ),
    )
    (attempt_dir / "command.txt").write_text(
        " ".join(shlex.quote(part) for part in prepared.command) + "\n",
        encoding="utf-8",
    )
    execution = harness_runtime.execute_role(
        prepared=prepared,
        cwd=game_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        output_path=output_path,
        wall_timeout_seconds=(
            None if timeout_seconds is None else float(timeout_seconds)
        ),
        idle_timeout_seconds=float(idle_timeout_seconds),
    )
    stdout = (
        stdout_path.read_text(encoding="utf-8", errors="replace")
        if stdout_path.is_file()
        else ""
    )
    stderr = (
        stderr_path.read_text(encoding="utf-8", errors="replace")
        if stderr_path.is_file()
        else ""
    )
    return (
        execution.process.returncode,
        stdout,
        stderr,
        execution.process.timed_out,
    )


def evaluate_candidate_with_verifier(
    *,
    eval_dir: Path,
    bench: Path,
    task_dir: Path,
    candidate_trial: dict[str, Any],
    env: dict[str, str],
    timeout_seconds: int | None,
) -> dict[str, Any]:
    """Run the official GameCraft verifier once on a repaired final candidate."""

    if eval_dir.exists():
        shutil.rmtree(eval_dir)
    eval_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = eval_dir / "verifier.stdout.log"
    stderr_path = eval_dir / "verifier.stderr.log"
    status_path = eval_dir / "final_evaluation.json"

    trial_dir = Path(str(candidate_trial.get("trial_dir") or ""))
    verifier_dir = eval_dir / "verifier"
    verifier_dir.mkdir(parents=True, exist_ok=True)
    project_dir = trial_dir / "sandbox" / "workspace" / "game"
    python_bin = bench / ".venv" / "bin" / "python3"
    if not python_bin.exists():
        python_bin = Path(sys.executable)
    eval_env = dict(env)
    existing_pythonpath = eval_env.get("PYTHONPATH", "")
    eval_env["PYTHONPATH"] = (
        str(bench) if not existing_pythonpath else str(bench) + os.pathsep + existing_pythonpath
    )

    # The host-only rewrite is needed during scoring, but must not remain in
    # run artifacts that a later Tester pass could inspect.
    with tempfile.TemporaryDirectory(prefix="gameloop-verifier-rubric-") as private_dir:
        rubric_path = write_host_verifier_rubric(
            source_rubric=task_dir / "tests" / "rubric.json",
            eval_dir=Path(private_dir),
            project_dir=project_dir,
        )
        cmd = [
            str(python_bin),
            "-m",
            "gameloop.adapters.gamecraft_bench.verifier",
            "--project",
            str(project_dir),
            "--rubric",
            str(rubric_path),
            "--output",
            str(verifier_dir),
            # Final-evaluation process status represents scoring transport, not
            # whether a candidate cleared an arbitrary product threshold.  Reward
            # remains the authoritative benchmark metric; breakdown validation
            # below still rejects incomplete judge/infrastructure output.
            "--pass-threshold",
            "0",
        ]
        returncode, stdout, stderr, timed_out = run_harbor_attempt(
            cmd=cmd,
            bench=bench,
            env=eval_env,
            timeout_seconds=timeout_seconds,
        )
    stdout_path.write_text(stdout or "", encoding="utf-8")
    stderr_path.write_text(stderr or "", encoding="utf-8")

    breakdown_path = verifier_dir / "breakdown.json"
    breakdown = None
    if breakdown_path.is_file():
        try:
            breakdown = read_json(breakdown_path)
        except Exception:
            breakdown = None

    reported_trial = dict(candidate_trial)
    reward = None
    if isinstance(breakdown, dict):
        try:
            reward = float(breakdown.get("reward"))
        except (TypeError, ValueError):
            reward = None
    reported_trial.update(
        {
            "reward": reward,
            "breakdown_path": str(breakdown_path) if breakdown_path.is_file() else None,
            "breakdown_summary": summarize_breakdown(breakdown),
            "final_evaluation_dir": str(eval_dir),
        }
    )
    score_complete = (
        isinstance(breakdown, dict)
        and reward is not None
        and not has_judge_infrastructure_failure(breakdown)
    )
    effective_returncode = 0 if score_complete else (returncode or 1)
    status = {
        "status": "completed" if score_complete else "failed",
        "returncode": effective_returncode,
        "verifier_returncode": returncode,
        "timed_out": timed_out,
        "command": cmd,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "verifier_dir": str(verifier_dir),
        "reported_trial": reported_trial,
    }
    write_json(status_path, status)
    return status


def final_evaluation_trial_error(
    status: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Translate an incomplete verifier result into protocol validity state."""

    if not isinstance(status, dict) or status.get("status") != "failed":
        return None
    reported_trial = status.get("reported_trial")
    if isinstance(reported_trial, dict):
        candidate_error = trial_execution_error(reported_trial)
        if candidate_error is not None:
            return candidate_error
    breakdown_summary = (
        reported_trial.get("breakdown_summary")
        if isinstance(reported_trial, dict)
        else None
    )
    return {
        "type": "verifier_infrastructure_failure",
        "message": (
            "Final verifier did not produce a complete comparable score; "
            "the candidate must be rejudged."
        ),
        "returncode": status.get("returncode"),
        "breakdown_summary": breakdown_summary,
    }


def write_host_verifier_rubric(*, source_rubric: Path, eval_dir: Path, project_dir: Path) -> Path:
    """Adapt Harbor's container-path build check for host-side final evaluation."""

    rubric = read_json(source_rubric)
    build_check = rubric.get("build_check")
    if isinstance(build_check, dict) and isinstance(build_check.get("cmd"), str):
        build_check["cmd"] = build_check["cmd"].replace("/workspace/game", str(project_dir))
    host_rubric = eval_dir / "rubric.host.json"
    write_json(host_rubric, rubric)
    return host_rubric


def select_chatgpt_codex_home(env: dict[str, str]) -> Path:
    """Select a local Codex home whose auth file uses ChatGPT login."""

    candidates: list[Path] = []
    for value in (
        env.get("GAMELOOP_LOCAL_CODEX_HOME"),
        env.get("CODEX_HOME"),
        str(Path.home() / ".codex"),
        str(Path.home() / ".codex-judge-login"),
    ):
        if not value:
            continue
        candidate = Path(value).expanduser().resolve()
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        auth_path = candidate / "auth.json"
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(auth, dict) and auth.get("auth_mode") == "chatgpt":
            env["CODEX_HOME"] = str(candidate)
            return candidate

    searched = ", ".join(str(path) for path in candidates)
    raise RuntimeError(
        "No ChatGPT-login Codex auth.json was found. "
        f"Checked: {searched or '<none>'}"
    )


def apply_codex_login_env(
    env: dict[str, str],
    *,
    require_chatgpt: bool = False,
) -> dict[str, str]:
    """Route Codex calls through local login, optionally preserving a proxy."""

    try:
        codex_home = select_chatgpt_codex_home(env)
    except RuntimeError:
        if require_chatgpt:
            raise
    else:
        env["CODEX_HOME"] = str(codex_home)
        env["CODEX_AUTH_JSON_PATH"] = str(codex_home / "auth.json")

    preserve_base_url = (
        env.get("GAMELOOP_CODEX_LOGIN_PRESERVE_BASE_URL") == "1"
    )
    updates = {
        "CODEX_FORCE_AUTH_JSON": "1",
        "GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL": (
            "1" if preserve_base_url else "0"
        ),
    }
    if env.get("GAMELOOP_CODEX_LOGIN_PRESERVE_JUDGE") != "1":
        updates.update(
            {
                "GAMECRAFT_BENCH_JUDGE": "codex-cli",
                "GAMECRAFT_BENCH_JUDGE_MODEL": env.get(
                    "GAMECRAFT_BENCH_JUDGE_MODEL", "gpt-5.5"
                ),
                "GAMECRAFT_BENCH_JUDGE_CODEX_CLEAR_OPENAI_ENV": "1",
            }
        )
    env.update(updates)
    if "CODEX_HOME" in env:
        auth_path = Path(env["CODEX_HOME"]).expanduser() / "auth.json"
        if auth_path.is_file():
            env["CODEX_AUTH_JSON_PATH"] = str(auth_path)
    if preserve_base_url:
        base_url = env.get("GAMELOOP_CODEX_LOGIN_BASE_URL")
        if not base_url:
            raise RuntimeError(
                "GAMELOOP_CODEX_LOGIN_BASE_URL is required when preserving "
                "a custom login endpoint"
            )
        env["OPENAI_BASE_URL"] = base_url
        env["GAMECRAFT_BENCH_JUDGE_CODEX_CLEAR_OPENAI_ENV"] = "0"
    else:
        # Local login may still use HTTP(S)_PROXY, but it must not silently
        # inherit an API-key or custom Responses endpoint from the parent.
        for key in (
            "OPENAI_API_KEY",
            "OPENAI_API_BASE",
            "OPENAI_BASE_URL",
            "GAMECRAFT_BENCH_JUDGE_OPENAI_API_KEY",
            "GAMECRAFT_BENCH_JUDGE_OPENAI_BASE_URL",
            "GAMELOOP_TESTER_API_KEY",
            "GAMELOOP_TESTER_BASE_URL",
        ):
            env.pop(key, None)
    return updates


def env_prefix(items: dict[str, str]) -> str:
    if not items:
        return ""
    return " ".join(f"{key}={shlex.quote(value)}" for key, value in sorted(items.items())) + " "


def build_inner_repair_instruction(
    *,
    loop_index: int,
    development_document: str,
    acceptance_status: dict[str, Any] | None,
) -> str:
    report_text = ""
    report_path = (acceptance_status or {}).get("report")
    if report_path and Path(str(report_path)).is_file():
        report_text = Path(str(report_path)).read_text(encoding="utf-8", errors="ignore")
    if not report_text.strip():
        report_text = "The inner acceptance tester did not provide a readable report. Re-check the current development document and repair visible mismatches."

    return "\n\n".join(
        [
            "# GameLoop inner repair pass",
            (
                f"This is a same-loop repair pass for loop {loop_index}. "
                "Do not redesign the game from scratch and do not start next-loop planning."
            ),
            "## Repair Scope",
            (
                "Repair only developer-owned issues where the current build does not satisfy "
                "the current development document or cannot provide visible replay evidence. "
                "Preserve working controls, content, visuals, and demo traces that already satisfy the document."
            ),
            "## Current Development Document",
            development_document.rstrip(),
            "## Inner Acceptance Tester Findings",
            report_text.strip(),
            "## Required Output",
            (
                "Return a launchable Godot game with updated replay/demo evidence. "
                "Keep the fix focused and make the acceptance tester's failed checks visibly pass."
            ),
        ]
    ).rstrip() + "\n"


def summarize_attempt_rewards(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose both final-loop validity and the latest comparable reward."""

    reported_rewards = [attempt.get("reported_reward") for attempt in attempts]
    valid_reported_rewards = [
        reward for reward in reported_rewards if reward is not None
    ]
    return {
        "reported_rewards": reported_rewards,
        "final_reward": reported_rewards[-1] if reported_rewards else None,
        "final_attempt_valid": (
            attempts[-1].get("trial_valid") if attempts else None
        ),
        "valid_reported_rewards": valid_reported_rewards,
        "latest_valid_reward": (
            valid_reported_rewards[-1] if valid_reported_rewards else None
        ),
        "valid_attempt_count": sum(
            attempt.get("trial_valid") is True for attempt in attempts
        ),
        "invalid_attempt_count": sum(
            attempt.get("trial_valid") is False for attempt in attempts
        ),
    }


def write_summary_markdown(run_dir: Path, summary: dict[str, Any]) -> None:
    identity_lines = []
    if summary.get("experiment_id"):
        identity_lines = [
            f"- Experiment ID: `{summary['experiment_id']}`",
            f"- Harness: `{summary['harness']}`",
            f"- Model: `{summary['model']}`",
        ]
    lines = [
        f"# GameCraft loop run: {summary['run_id']}",
        "",
        f"- Task: `{summary['task']}`",
        *identity_lines,
        f"- Mode: `{summary['mode']}`",
        f"- Tester policy: `{summary.get('tester_policy', 'next-loop')}`",
        f"- Warm start strategy: `{summary.get('warm_start_strategy', 'none')}`",
        f"- Reported rewards: `{summary.get('reported_rewards', [])}`",
        f"- Final reported reward: `{summary.get('final_reward')}`",
        f"- Final attempt valid: `{summary.get('final_attempt_valid')}`",
        f"- Latest valid reward: `{summary.get('latest_valid_reward')}`",
        f"- Valid/invalid attempts: `{summary.get('valid_attempt_count', 0)}` / `{summary.get('invalid_attempt_count', 0)}`",
    ]
    lines.extend(
        [
            "",
            "## Attempts",
            "",
            "| Attempt | Job | Exit | Loop reward | Repairs | Reported trial | Baseline trial |",
            "|---:|---|---:|---:|---:|---|---|",
        ]
    )
    for attempt in summary.get("attempts", []):
        reported = attempt.get("reported_trial") or {}
        baseline = attempt.get("baseline_trial") or {}
        repair_count = len(attempt.get("inner_repairs") or [])
        lines.append(
            "| {attempt} | `{job}` | {exit_code} | {loop_reward} | {repairs} | `{reported_trial}` | `{baseline_trial}` |".format(
                attempt=attempt.get("attempt"),
                job=attempt.get("job_name"),
                exit_code=attempt.get("returncode"),
                loop_reward=attempt.get("loop_reward"),
                repairs=repair_count,
                reported_trial=reported.get("trial_name"),
                baseline_trial=baseline.get("trial_name"),
            )
        )
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_public_evidence_history_entry(
    *,
    source_loop: int,
    trial: dict[str, Any],
    qa_tester_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "source_loop": source_loop,
        "public_execution_snapshot": build_public_execution_snapshot(trial),
        "qa_tester_evidence": qa_tester_evidence or {},
    }


def main(argv: list[str] | None = None) -> int:
    args, passthrough = parse_args(sys.argv[1:] if argv is None else argv)
    bench = resolve_path(args.bench, Path.cwd())
    if args.llm_tester and not args.dry_run:
        try:
            _preflight_visual_tester_isolation(
                load_runtime_env(project_root=PROJECT_ROOT, bench=bench)
            )
        except RuntimeError as error:
            raise SystemExit(str(error)) from error
    jobs_dir = resolve_path(args.jobs_dir, Path.cwd())
    task_arg = normalize_task_arg(args.task)
    task_dir = Path(task_arg) if Path(task_arg).is_absolute() else bench / task_arg
    if not task_dir.exists():
        raise SystemExit(f"Task directory not found: {task_dir}")
    public_task_instruction = load_public_task_instruction(task_dir)
    explicit_domain_policies = getattr(args, "domain_policies", None)
    if explicit_domain_policies is not None and not isinstance(
        explicit_domain_policies, list
    ):
        raise SystemExit("config domain_policies must be a list of strings")
    try:
        selected_domain_policies = select_domain_policies(
            task_id=Path(task_arg).name,
            public_task_text=public_task_instruction,
            explicit=explicit_domain_policies,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    planner_policy_guidance = render_domain_policy_guidance(
        "planner", selected_domain_policies
    )
    developer_policy_guidance = render_domain_policy_guidance(
        "developer", selected_domain_policies
    )
    tester_policy_guidance = render_domain_policy_guidance(
        "tester", selected_domain_policies
    )

    started = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or f"{slugify(Path(task_arg).name)}-{started}"
    try:
        run_id = validate_run_id(run_id)
        run_dir = run_directory(RUNS_ROOT, run_id)
    except ValueError as error:
        raise SystemExit(f"Invalid --run-id: {error}") from error
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise SystemExit(
            f"Run directory already exists: {run_dir}. Choose a new --run-id, "
            "or continue with --seed-trial-dir and --start-loop-index in a new run."
        ) from error
    jobs_dir.mkdir(parents=True, exist_ok=True)
    role_bindings: dict[RoleName, RoleBinding] = args.role_bindings
    if role_bindings[RoleName.PLANNER].godot_docs:
        planner_policy_guidance += "\n" + godot_docs_role_guidance("planner")
    if role_bindings[RoleName.DEVELOPER].godot_docs:
        developer_policy_guidance += "\n" + godot_docs_role_guidance("developer")
    if role_bindings[RoleName.TESTER].godot_docs:
        tester_policy_guidance += "\n" + godot_docs_role_guidance("tester")
    if role_bindings[RoleName.DEVELOPER].godot_mcp is not GodotMCPAccess.DISABLED:
        developer_policy_guidance += "\n" + godot_mcp_role_guidance(
            "developer", strict_coverage=args.require_developer_mcp_coverage
        )
    if role_bindings[RoleName.TESTER].godot_mcp is not GodotMCPAccess.DISABLED:
        tester_policy_guidance += "\n" + godot_mcp_role_guidance("tester")
    runtime = GameLoopRuntime(run_dir=run_dir, roles=role_bindings)
    if not args.dry_run:
        compatibility = (
            inspect_bench_compatibility(
                bench,
                environment=load_runtime_env(project_root=PROJECT_ROOT, bench=bench),
            )
            if args.developer_backend == "harbor-legacy"
            else inspect_data_contract(bench)
        )
        write_json(run_dir / "bench_compatibility.json", compatibility)
        if compatibility.get("status") != "ready":
            raise SystemExit(
                "GameCraft-Bench compatibility preflight failed: "
                + str(compatibility.get("error") or "unknown incompatibility")
                + f". See {run_dir / 'bench_compatibility.json'}"
            )
    mcp_roles = [
        role.value
        for role, binding in role_bindings.items()
        if binding.godot_mcp is not GodotMCPAccess.DISABLED
    ]
    if mcp_roles and not args.dry_run:
        mcp_readiness = godot_mcp_doctor_payload()
        write_json(run_dir / "godot_mcp_doctor.json", mcp_readiness)
        if mcp_readiness.get("status") != "ready":
            raise SystemExit(
                "Godot MCP is enabled for "
                + ", ".join(sorted(mcp_roles))
                + "; run `./scripts/gameloop-godot-mcp-vendor prepare` "
                "and `./scripts/gameloop-godot-mcp doctor` before the benchmark"
            )
    write_json(
        run_dir / "domain_policy_manifest.json",
        domain_policy_manifest(
            task_id=Path(task_arg).name,
            policies=selected_domain_policies,
            selection_source=(
                "explicit-config"
                if explicit_domain_policies is not None
                else "public-task-text"
            ),
        ),
    )

    seed_candidate = trial_seed_from_dir(Path(args.seed_trial_dir)) if args.seed_trial_dir else None
    seed_archive = None
    if seed_candidate:
        seed_archive = archive_seed_game(
            run_dir,
            seed_candidate,
            args.start_loop_index - 1,
        )

    all_attempts: list[dict[str, Any]] = []
    previous_candidate: dict[str, Any] | None = seed_candidate
    previous_demo_evidence: dict[str, Any] | None = load_next_loop_evidence_from_trial(
        seed_candidate
    )
    evidence_history: list[dict[str, Any]] = []
    if seed_candidate:
        evidence_history.append(
            build_public_evidence_history_entry(
                source_loop=args.start_loop_index - 1,
                trial=seed_candidate,
                qa_tester_evidence=previous_demo_evidence,
            )
        )
        write_json(run_dir / "evidence_history.json", evidence_history)
    warm_start_strategy = "latest" if args.warm_start_latest else "seed" if seed_candidate else "none"
    planner_experiment_id = args.experiment_id or "codex-gpt-5.5"

    for ordinal in range(1, args.attempts + 1):
        loop_index = args.start_loop_index + ordinal - 1
        runtime.begin_loop(loop_index)
        attempt_dir = run_dir / loop_tag(loop_index)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        baseline_candidate = previous_candidate
        env = load_runtime_env(project_root=PROJECT_ROOT, bench=bench)
        apply_experiment_environment(planner_experiment_id, env)
        project_scripts = str(PROJECT_ROOT / "scripts")
        current_path = env.get("PATH", "")
        if project_scripts not in current_path.split(os.pathsep):
            env["PATH"] = os.pathsep.join(
                part for part in (project_scripts, current_path) if part
            )
        added_path_dirs = prepend_default_tool_paths(env, bench=bench)
        codex_login_env = (
            apply_codex_login_env(env)
            if args.codex_login and not args.dry_run
            else {}
        )
        env["GAMECRAFT_BENCH_JOBS_ROOT"] = str(jobs_dir)
        env["GAMELOOP_DEVELOPER_MODEL"] = role_bindings[
            RoleName.DEVELOPER
        ].model
        loop_artifacts = build_loop_artifacts(
            loop_index=loop_index,
            previous_best=baseline_candidate,
            previous_demo_evidence=previous_demo_evidence,
            evidence_history=evidence_history,
            public_task_instruction=public_task_instruction,
        )
        if args.planner_mode == "harness":
            evidence_packet = None
            if loop_index > 1:
                evidence_packet = build_project_planner_evidence_packet(
                    public_execution_snapshot=loop_artifacts[
                        "public_execution_snapshot"
                    ],
                    issues=loop_artifacts["issues"],
                    qa_tester_evidence=previous_demo_evidence,
                    evidence_history=evidence_history,
                )
            planner_prompt = build_project_planner_prompt(
                loop_index=loop_index,
                public_task_instruction=public_task_instruction,
                evidence_packet=evidence_packet,
                scaffold_document=loop_artifacts["development_document"],
                final_iteration=ordinal == args.attempts,
            )
            planner_prompt = (
                planner_prompt.rstrip()
                + "\n\n"
                + planner_policy_guidance.strip()
                + "\n"
            )
            planner_run = runtime.invoke(
                RoleName.PLANNER,
                lambda: run_project_planner(
                    attempt_dir=attempt_dir,
                    loop_index=loop_index,
                    prompt=planner_prompt,
                    scaffold_document=loop_artifacts["development_document"],
                    experiment_id=planner_experiment_id,
                    environment=env,
                    reasoning_effort=role_bindings[RoleName.PLANNER].reasoning_effort,
                    wall_timeout_seconds=args.planner_timeout_seconds,
                    idle_timeout_seconds=args.planner_idle_timeout_seconds,
                    dry_run=args.dry_run,
                    role_binding=role_bindings[RoleName.PLANNER],
                ),
                summarize=lambda result: result.status,
            )
            loop_artifacts["development_document"] = planner_run.document
            planner_status = planner_run.status
            if planner_status.get("used_fallback"):
                planner_stderr = attempt_dir / "planner" / "planner.stderr.log"
                planner_stdout = attempt_dir / "planner" / "planner.stdout.log"
                diagnostic_text = "\n".join(
                    path.read_text(encoding="utf-8", errors="replace")
                    for path in (planner_stderr, planner_stdout)
                    if path.is_file()
                )
                marker = codex_infrastructure_failure(diagnostic_text)
                if marker:
                    raise SystemExit(
                        "Project Planner failed because Codex infrastructure is "
                        f"unavailable ({marker}). Fix CODEX_HOME/login/quota before "
                        "starting Developer; deterministic planning fallback is not "
                        "a valid recovery for an unavailable model."
                    )
        else:
            planner_status = {
                "status": "template",
                "used_fallback": False,
                "document_source": "deterministic_template",
                "fallback_reason": None,
                "experiment_id": planner_experiment_id,
                "loop_index": loop_index,
            }
            write_json(attempt_dir / "planner_status.json", planner_status)
            runtime.record_skipped_role(
                RoleName.PLANNER,
                status="template",
                details={"planner_mode": "template"},
            )
        write_loop_artifacts(attempt_dir, loop_artifacts)
        use_warm_start = bool(baseline_candidate and warm_start_strategy != "none")
        active_task_arg = task_arg
        active_task_dir = task_dir
        if args.developer_backend == "harbor-legacy" and use_warm_start:
            copied = copy_task_for_attempt(
                bench=bench,
                task_arg=task_arg,
                run_id=run_id,
                attempt=loop_index,
                previous_best=baseline_candidate,
                task_workdirs=TASK_WORKDIRS,
            )
            active_task_arg = str(copied)
            active_task_dir = copied

        extra_text = build_extra_instruction(
            mode=args.mode,
            attempt=loop_index,
            task_dir=active_task_dir,
            previous_best=baseline_candidate,
            warm_started=use_warm_start,
            previous_demo_evidence=previous_demo_evidence,
            development_document=loop_artifacts["development_document"],
            final_iteration=ordinal == args.attempts,
        )
        extra_text = (
            extra_text.rstrip()
            + "\n\n"
            + developer_policy_guidance.strip()
            + "\n"
        )
        extra_path = attempt_dir / "extra_instruction.md"
        extra_path.write_text(extra_text, encoding="utf-8")
        developer_mcp_config = write_developer_mcp_config(
            attempt_dir=attempt_dir,
            environment=env,
            role_binding=role_bindings[RoleName.DEVELOPER],
        )

        job_name = f"{run_id}-a{loop_index:02d}"
        run_inner_repair_policy = args.llm_tester and args.tester_policy == "repair-then-next"
        cmd: list[str] = []
        direct_trial_dir: Path | None = None
        direct_game_dir: Path | None = None
        if args.developer_backend == "harbor-legacy":
            cmd = build_command(
                bench=bench,
                wrapper=args.wrapper,
                task_arg=active_task_arg,
                job_name=job_name,
                extra_instruction=extra_path,
                reasoning_effort=role_bindings[RoleName.DEVELOPER].reasoning_effort,
                n_concurrent=args.n_concurrent,
                passthrough=passthrough,
                disable_verification=(
                    args.defer_verification
                    or args.external_verifier
                    or run_inner_repair_policy
                ),
                mcp_config=developer_mcp_config,
            )
        else:
            direct_trial_dir, direct_game_dir = prepare_direct_candidate_trial(
                attempt_dir=attempt_dir,
                previous_candidate=baseline_candidate if use_warm_start else None,
            )
        path_prefix = ""
        if added_path_dirs:
            joined_paths = os.pathsep.join(str(path) for path in added_path_dirs)
            path_prefix = f"PATH={joined_paths}:$PATH "
        if args.developer_backend == "harbor-legacy":
            (attempt_dir / "command.txt").write_text(
                f"{path_prefix}{env_prefix(codex_login_env)}"
                f"GAMECRAFT_BENCH_JOBS_ROOT={jobs_dir} "
                "GAMELOOP_DEVELOPER_MODEL="
                f"{shlex.quote(role_bindings[RoleName.DEVELOPER].model)} "
                + " ".join(cmd)
                + "\n",
                encoding="utf-8",
            )
        elif args.dry_run:
            (attempt_dir / "command.txt").write_text(
                "[dry-run] GameLoop HarnessRuntime Developer\n",
                encoding="utf-8",
            )

        developer_mcp_cleanup: dict[str, Any] = {"status": "not_run"}

        def invoke_primary_developer() -> tuple[int, str, str, bool]:
            nonlocal developer_mcp_cleanup
            try:
                if args.developer_backend == "harness":
                    assert direct_game_dir is not None
                    return run_direct_developer_harness(
                        attempt_dir=attempt_dir,
                        game_dir=direct_game_dir,
                        prompt_path=extra_path,
                        environment=env,
                        binding=role_bindings[RoleName.DEVELOPER],
                        timeout_seconds=args.timeout_seconds,
                        idle_timeout_seconds=args.developer_idle_timeout_seconds,
                        dry_run=args.dry_run,
                    )
                if args.dry_run:
                    return 0, "[dry-run] command not executed\n", "", False
                return run_harbor_attempt(
                    cmd=cmd,
                    bench=bench,
                    env=env,
                    timeout_seconds=args.timeout_seconds,
                )
            finally:
                developer_mcp_cleanup = cleanup_lifecycle_processes(
                    attempt_dir / "mcp-evidence"
                )

        returncode, stdout, stderr, timed_out = runtime.invoke(
            RoleName.DEVELOPER,
            invoke_primary_developer,
            summarize=lambda result: {
                "status": "dry_run" if args.dry_run else "completed",
                "returncode": result[0],
                "timed_out": result[3],
                "harness": role_bindings[RoleName.DEVELOPER].harness,
                "model": role_bindings[RoleName.DEVELOPER].model,
                "mcp_observation": summarize_godot_mcp_evidence(
                    attempt_dir / "mcp-evidence"
                ),
                "mcp_cleanup": developer_mcp_cleanup,
            },
        )

        developer_mcp_observation = summarize_godot_mcp_evidence(
            attempt_dir / "mcp-evidence"
        )
        developer_mcp_gaps = (
            mcp_coverage_gaps(
                developer_mcp_observation,
                role="developer",
                minimum_debug_cycles=1,
                minimum_run_count=2 if use_warm_start else 1,
            )
            if role_bindings[RoleName.DEVELOPER].godot_mcp
            is not GodotMCPAccess.DISABLED
            and not args.dry_run
            else []
        )
        if args.developer_backend == "harbor-legacy":
            (attempt_dir / "harbor.stdout.log").write_text(stdout or "", encoding="utf-8")
            (attempt_dir / "harbor.stderr.log").write_text(stderr or "", encoding="utf-8")

        if args.dry_run:
            trials = []
        elif args.developer_backend == "harness" and returncode == 0:
            assert direct_trial_dir is not None
            trials = [direct_candidate_record(direct_trial_dir)]
        else:
            trials = collect_job_results(jobs_dir, job_name)
        local_latest = latest_trial(trials)
        trial_error = None if args.dry_run else trial_execution_error(local_latest)
        if local_latest is not None and not args.dry_run and developer_mcp_gaps == []:
            trial_dir = Path(str(local_latest.get("trial_dir") or ""))
            developer_mcp_gaps.extend(
                mcp_runtime_source_freshness_gaps(
                    developer_mcp_observation,
                    trial_dir / "sandbox" / "workspace" / "game",
                )
            )
        developer_mcp_warnings = mcp_process_warnings(
            developer_mcp_observation,
            warm_start=use_warm_start,
            coverage_gaps=developer_mcp_gaps,
        )
        if (
            trial_error is None
            and args.require_developer_mcp_coverage
            and developer_mcp_gaps
        ):
            trial_error = {
                "type": "invalid_developer_mcp_coverage",
                "message": "Developer did not complete the required Godot MCP debug loop.",
                "gaps": developer_mcp_gaps,
            }
        if local_latest is not None and trial_error is None:
            previous_candidate = local_latest
        reported_trial = local_latest
        reported_reward = None if reported_trial is None else reported_trial.get("reward")
        if trial_error is not None and returncode == 0:
            returncode = 1
        if trial_error is not None:
            reported_reward = None
        inner_acceptance_status = None
        inner_repairs: list[dict[str, Any]] = []
        final_evaluation_status = None
        visual_tester_status = None
        if run_inner_repair_policy and trial_error is None:
            inner_acceptance_status = runtime.invoke(
                RoleName.TESTER,
                lambda: run_visual_tester(
                    attempt_dir=attempt_dir / "inner-acceptance-00",
                    loop_index=loop_index,
                    task_dir=active_task_dir,
                    trial=reported_trial,
                    development_document=loop_artifacts["development_document"],
                    tester_phase="acceptance",
                    final_iteration=ordinal == args.attempts,
                    tester_timeout_seconds=args.tester_timeout_seconds,
                    tester_idle_timeout_seconds=args.tester_idle_timeout_seconds,
                    dry_run=args.dry_run,
                    model=None,
                    experiment_id=planner_experiment_id,
                    reasoning_effort=role_bindings[RoleName.TESTER].reasoning_effort,
                    private_paths=(PROJECT_ROOT, bench),
                    environment=env,
                    role_binding=role_bindings[RoleName.TESTER],
                    domain_policy_guidance=tester_policy_guidance,
                ),
                summarize=lambda result: result,
            )
            repair_index = 0
            if (
                not tester_acceptance_passed(inner_acceptance_status)
                and not tester_failure_is_repairable(inner_acceptance_status)
            ):
                trial_error = tester_protocol_error(inner_acceptance_status)
                returncode = int(
                    inner_acceptance_status.get("returncode") or 1
                    if isinstance(inner_acceptance_status, dict)
                    else 1
                )
                timed_out = bool(
                    inner_acceptance_status.get("timed_out")
                    if isinstance(inner_acceptance_status, dict)
                    else False
                )
                reported_reward = None
            while (
                trial_error is None
                and tester_failure_is_repairable(inner_acceptance_status)
                and not tester_acceptance_passed(inner_acceptance_status)
                and repair_index < args.max_inner_repairs
                and reported_trial is not None
            ):
                repair_index += 1
                repair_dir = attempt_dir / f"inner-repair-{repair_index:02d}"
                repair_dir.mkdir(parents=True, exist_ok=True)
                repair_task_dir = task_dir
                if args.developer_backend == "harbor-legacy":
                    repair_task_dir = copy_task_for_attempt(
                        bench=bench,
                        task_arg=task_arg,
                        run_id=f"{run_id}/inner-repair-{loop_index:02d}-{repair_index:02d}",
                        attempt=loop_index,
                        previous_best=reported_trial,
                        task_workdirs=TASK_WORKDIRS,
                    )
                repair_extra_text = build_inner_repair_instruction(
                    loop_index=loop_index,
                    development_document=loop_artifacts["development_document"],
                    acceptance_status=inner_acceptance_status,
                )
                repair_extra_text = (
                    repair_extra_text.rstrip()
                    + "\n\n"
                    + developer_policy_guidance.strip()
                    + "\n"
                )
                repair_extra_path = repair_dir / "extra_instruction.md"
                repair_extra_path.write_text(repair_extra_text, encoding="utf-8")
                repair_mcp_config = write_developer_mcp_config(
                    attempt_dir=repair_dir,
                    environment=env,
                    role_binding=role_bindings[RoleName.DEVELOPER],
                )
                repair_job_name = f"{run_id}-a{loop_index:02d}-r{repair_index:02d}"
                repair_cmd: list[str] = []
                direct_repair_trial: Path | None = None
                direct_repair_game: Path | None = None
                if args.developer_backend == "harbor-legacy":
                    repair_cmd = build_command(
                        bench=bench,
                        wrapper=args.wrapper,
                        task_arg=str(repair_task_dir),
                        job_name=repair_job_name,
                        extra_instruction=repair_extra_path,
                        reasoning_effort=role_bindings[RoleName.DEVELOPER].reasoning_effort,
                        n_concurrent=args.n_concurrent,
                        passthrough=passthrough,
                        disable_verification=True,
                        mcp_config=repair_mcp_config,
                    )
                    (repair_dir / "command.txt").write_text(
                        f"{path_prefix}{env_prefix(codex_login_env)}"
                        f"GAMECRAFT_BENCH_JOBS_ROOT={jobs_dir} "
                        "GAMELOOP_DEVELOPER_MODEL="
                        f"{shlex.quote(role_bindings[RoleName.DEVELOPER].model)} "
                        + " ".join(repair_cmd)
                        + "\n",
                        encoding="utf-8",
                    )
                else:
                    direct_repair_trial, direct_repair_game = (
                        prepare_direct_candidate_trial(
                            attempt_dir=repair_dir,
                            previous_candidate=reported_trial,
                        )
                    )
                repair_mcp_cleanup: dict[str, Any] = {"status": "not_run"}

                def invoke_repair_developer() -> tuple[int, str, str, bool]:
                    nonlocal repair_mcp_cleanup
                    try:
                        if args.developer_backend == "harness":
                            assert direct_repair_game is not None
                            return run_direct_developer_harness(
                                attempt_dir=repair_dir,
                                game_dir=direct_repair_game,
                                prompt_path=repair_extra_path,
                                environment=env,
                                binding=role_bindings[RoleName.DEVELOPER],
                                timeout_seconds=args.timeout_seconds,
                                idle_timeout_seconds=args.developer_idle_timeout_seconds,
                                dry_run=args.dry_run,
                            )
                        if args.dry_run:
                            return 0, "[dry-run] command not executed\n", "", False
                        return run_harbor_attempt(
                            cmd=repair_cmd,
                            bench=bench,
                            env=env,
                            timeout_seconds=args.timeout_seconds,
                        )
                    finally:
                        repair_mcp_cleanup = cleanup_lifecycle_processes(
                            repair_dir / "mcp-evidence"
                        )
                (
                    repair_returncode,
                    repair_stdout,
                    repair_stderr,
                    repair_timed_out,
                ) = runtime.invoke(
                    RoleName.DEVELOPER,
                    invoke_repair_developer,
                    summarize=lambda result: {
                        "status": "dry_run" if args.dry_run else "completed",
                        "repair_index": repair_index,
                        "returncode": result[0],
                        "timed_out": result[3],
                        "harness": role_bindings[RoleName.DEVELOPER].harness,
                        "model": role_bindings[RoleName.DEVELOPER].model,
                        "mcp_observation": summarize_godot_mcp_evidence(
                            repair_dir / "mcp-evidence"
                        ),
                        "mcp_cleanup": repair_mcp_cleanup,
                    },
                )
                repair_mcp_observation = summarize_godot_mcp_evidence(
                    repair_dir / "mcp-evidence"
                )
                repair_mcp_gaps = (
                    mcp_coverage_gaps(
                        repair_mcp_observation,
                        role="developer",
                        minimum_debug_cycles=1,
                    )
                    if role_bindings[RoleName.DEVELOPER].godot_mcp
                    is not GodotMCPAccess.DISABLED
                    and not args.dry_run
                    else []
                )
                if args.developer_backend == "harbor-legacy":
                    (repair_dir / "harbor.stdout.log").write_text(repair_stdout or "", encoding="utf-8")
                    (repair_dir / "harbor.stderr.log").write_text(repair_stderr or "", encoding="utf-8")
                if args.dry_run:
                    repair_trials = []
                elif args.developer_backend == "harness":
                    if repair_returncode == 0:
                        assert direct_repair_trial is not None
                        repair_trials = [direct_candidate_record(direct_repair_trial)]
                    else:
                        repair_trials = []
                else:
                    repair_trials = collect_job_results(jobs_dir, repair_job_name)
                repair_latest = latest_trial(repair_trials)
                repair_error = (
                    None if args.dry_run else trial_execution_error(repair_latest)
                )
                if (
                    repair_latest is not None
                    and not args.dry_run
                    and repair_mcp_gaps == []
                ):
                    repair_trial_dir = Path(
                        str(repair_latest.get("trial_dir") or "")
                    )
                    repair_mcp_gaps.extend(
                        mcp_runtime_source_freshness_gaps(
                            repair_mcp_observation,
                            repair_trial_dir / "sandbox" / "workspace" / "game",
                        )
                    )
                if (
                    repair_error is None
                    and args.require_developer_mcp_coverage
                    and repair_mcp_gaps
                ):
                    repair_error = {
                        "type": "invalid_developer_mcp_coverage",
                        "message": "Repair Developer did not complete the required Godot MCP debug loop.",
                        "gaps": repair_mcp_gaps,
                    }
                if repair_error is not None and repair_returncode == 0:
                    repair_returncode = 1
                if repair_latest is not None and repair_error is None:
                    reported_trial = repair_latest
                    reported_reward = repair_latest.get("reward")
                    previous_candidate = repair_latest
                    if args.developer_backend == "harbor-legacy":
                        active_task_dir = repair_task_dir
                        active_task_arg = str(repair_task_dir)
                if repair_error is None:
                    repair_acceptance_status = runtime.invoke(
                        RoleName.TESTER,
                        lambda: run_visual_tester(
                            attempt_dir=repair_dir / "inner-acceptance",
                            loop_index=loop_index,
                            task_dir=active_task_dir,
                            trial=reported_trial,
                            development_document=loop_artifacts["development_document"],
                            tester_phase="acceptance",
                            final_iteration=ordinal == args.attempts,
                            tester_timeout_seconds=args.tester_timeout_seconds,
                            tester_idle_timeout_seconds=args.tester_idle_timeout_seconds,
                            dry_run=args.dry_run,
                            model=None,
                            experiment_id=planner_experiment_id,
                            reasoning_effort=role_bindings[RoleName.TESTER].reasoning_effort,
                            private_paths=(PROJECT_ROOT, bench),
                            environment=env,
                            role_binding=role_bindings[RoleName.TESTER],
                            domain_policy_guidance=tester_policy_guidance,
                        ),
                        summarize=lambda result: result,
                    )
                    inner_acceptance_status = repair_acceptance_status
                else:
                    repair_acceptance_status = {
                        "status": "skipped_invalid_trial",
                        "returncode": 1,
                        "review_status": "blocked",
                        "trial_error": repair_error,
                    }
                repair_record = {
                    "repair_index": repair_index,
                    "job_name": repair_job_name,
                    "task_arg": str(repair_task_dir),
                    "extra_instruction": str(repair_extra_path),
                    "command": repair_cmd,
                    "returncode": repair_returncode,
                    "timed_out": repair_timed_out,
                    "trials": repair_trials,
                    "latest_trial": repair_latest,
                    "trial_error": repair_error,
                    "reported_trial": reported_trial,
                    "reported_reward": reported_reward,
                    "inner_acceptance": repair_acceptance_status,
                    "developer_mcp": repair_mcp_observation,
                    "developer_mcp_coverage_gaps": repair_mcp_gaps,
                }
                inner_repairs.append(repair_record)
                write_json(repair_dir / "repair_attempt.json", repair_record)
                if repair_returncode != 0:
                    # Repairs run against a disposable copy. Preserve and score
                    # the last valid candidate when a repair process, MCP gate,
                    # or repair trial fails instead of replacing it with a
                    # broken copy and discarding completed Developer/Tester work.
                    break

            if returncode == 0 and reported_trial is not None:
                if args.dry_run:
                    final_evaluation_status = {
                        "status": "dry_run",
                        "returncode": 0,
                        "timed_out": False,
                        "command": [],
                        "reported_trial": reported_trial,
                    }
                elif args.defer_verification:
                    final_evaluation_status = {
                        "status": "deferred",
                        "returncode": 0,
                        "timed_out": False,
                        "command": [],
                        "reported_trial": reported_trial,
                    }
                else:
                    final_evaluation_status = evaluate_candidate_with_verifier(
                        eval_dir=attempt_dir / "final-evaluation",
                        bench=bench,
                        task_dir=task_dir,
                        candidate_trial=reported_trial,
                        env=env,
                        timeout_seconds=args.timeout_seconds,
                    )
                evaluated_trial = final_evaluation_status.get("reported_trial")
                if isinstance(evaluated_trial, dict):
                    reported_trial = evaluated_trial
                    reported_reward = evaluated_trial.get("reward")
                    previous_candidate = evaluated_trial
                evaluation_error = final_evaluation_trial_error(
                    final_evaluation_status
                )
                if evaluation_error is not None:
                    trial_error = evaluation_error
                    reported_reward = None
                if final_evaluation_status.get("returncode") != 0:
                    returncode = int(final_evaluation_status.get("returncode") or 1)
                    timed_out = bool(final_evaluation_status.get("timed_out"))
            elif returncode == 0:
                final_evaluation_status = {
                    "status": "skipped_no_trial",
                    "returncode": 0,
                    "timed_out": False,
                    "command": [],
                    "reported_trial": None,
                }

        if (
            not run_inner_repair_policy
            and args.external_verifier
            and trial_error is None
            and returncode == 0
            and (task_dir / "tests" / "rubric.json").is_file()
        ):
            if reported_trial is None:
                final_evaluation_status = {
                    "status": "skipped_no_trial",
                    "returncode": 0,
                    "timed_out": False,
                    "command": [],
                    "reported_trial": None,
                }
            elif args.dry_run:
                final_evaluation_status = {
                    "status": "dry_run",
                    "returncode": 0,
                    "timed_out": False,
                    "command": [],
                    "reported_trial": reported_trial,
                }
            elif args.defer_verification:
                final_evaluation_status = {
                    "status": "deferred",
                    "returncode": 0,
                    "timed_out": False,
                    "command": [],
                    "reported_trial": reported_trial,
                }
            else:
                final_evaluation_status = evaluate_candidate_with_verifier(
                    eval_dir=attempt_dir / "final-evaluation",
                    bench=bench,
                    task_dir=task_dir,
                    candidate_trial=reported_trial,
                    env=env,
                    timeout_seconds=args.timeout_seconds,
                )
            evaluated_trial = final_evaluation_status.get("reported_trial")
            if isinstance(evaluated_trial, dict):
                reported_trial = evaluated_trial
                reported_reward = evaluated_trial.get("reward")
                previous_candidate = evaluated_trial
            evaluation_error = final_evaluation_trial_error(final_evaluation_status)
            if evaluation_error is not None:
                trial_error = evaluation_error
                reported_reward = None
            if final_evaluation_status.get("returncode") != 0:
                returncode = int(final_evaluation_status.get("returncode") or 1)
                timed_out = bool(final_evaluation_status.get("timed_out"))

        if args.llm_tester and trial_error is None:
            visual_tester_status = runtime.invoke(
                RoleName.TESTER,
                lambda: run_visual_tester(
                    attempt_dir=attempt_dir,
                    loop_index=loop_index,
                    task_dir=active_task_dir,
                    trial=reported_trial,
                    development_document=loop_artifacts["development_document"],
                    tester_phase="next_loop",
                    tester_timeout_seconds=args.tester_timeout_seconds,
                    tester_idle_timeout_seconds=args.tester_idle_timeout_seconds,
                    dry_run=args.dry_run,
                    model=None,
                    experiment_id=planner_experiment_id,
                    reasoning_effort=role_bindings[RoleName.TESTER].reasoning_effort,
                    private_paths=(PROJECT_ROOT, bench),
                    environment=env,
                    role_binding=role_bindings[RoleName.TESTER],
                    domain_policy_guidance=tester_policy_guidance,
                ),
                summarize=lambda result: result,
            )
            loaded_demo_evidence = load_next_loop_evidence_report(
                attempt_dir / "visual_playtest_report.json"
            )
            if loaded_demo_evidence is None:
                loaded_demo_evidence = load_next_loop_evidence_from_trial(reported_trial)
            if loaded_demo_evidence is not None:
                previous_demo_evidence = loaded_demo_evidence
            if (
                not args.dry_run
                and returncode == 0
                and (
                    visual_tester_status.get("status") != "completed"
                    or visual_tester_status.get("returncode") != 0
                )
            ):
                tester_returncode = visual_tester_status.get("returncode")
                returncode = (
                    int(tester_returncode)
                    if isinstance(tester_returncode, int) and tester_returncode != 0
                    else 1
                )
                timed_out = timed_out or bool(visual_tester_status.get("timed_out"))
                trial_error = tester_protocol_error(visual_tester_status)
                reported_reward = None
        elif args.llm_tester:
            visual_tester_status = {
                "status": "skipped_invalid_trial",
                "returncode": 1,
                "review_status": "blocked",
                "trial_error": trial_error,
            }

        if reported_trial is not None and trial_error is None:
            history_entry = build_public_evidence_history_entry(
                source_loop=loop_index,
                trial=reported_trial,
                qa_tester_evidence=previous_demo_evidence,
            )
            if evidence_history and evidence_history[-1].get("source_loop") == loop_index:
                evidence_history[-1] = history_entry
            else:
                evidence_history.append(history_entry)
            write_json(run_dir / "evidence_history.json", evidence_history)

        attempt_record = {
            "attempt": loop_index,
            "ordinal": ordinal,
            "job_name": job_name,
            "task_arg": active_task_arg,
            "developer_backend": args.developer_backend,
            "jobs_dir": str(jobs_dir),
            "extra_instruction": str(extra_path),
            "command": cmd,
            "returncode": returncode,
            "timed_out": timed_out,
            "trials": trials,
            "latest_trial": local_latest,
            "reported_trial": reported_trial,
            "trial_valid": args.dry_run or trial_error is None,
            "trial_error": trial_error,
            "loop_reward": reported_reward,
            "reported_reward": reported_reward,
            "baseline_trial": baseline_candidate,
            "planner": planner_status,
            "planner_mode": args.planner_mode,
            "tester_policy": args.tester_policy,
            "verification_deferred": args.defer_verification,
            "external_verifier": args.external_verifier,
            "developer_mcp_coverage_required": args.require_developer_mcp_coverage,
            "inner_acceptance": inner_acceptance_status,
            "inner_repairs": inner_repairs,
            "final_evaluation": final_evaluation_status,
            "visual_tester": visual_tester_status,
            "developer_mcp": developer_mcp_observation,
            "developer_mcp_coverage_gaps": developer_mcp_gaps,
            "developer_mcp_warnings": developer_mcp_warnings,
        }
        all_attempts.append(attempt_record)
        write_json(attempt_dir / "attempt.json", attempt_record)
        summary = {
            "run_id": run_id,
            "task": task_arg,
            "experiment_id": args.experiment_id,
            "harness": args.harness,
            "model": args.model,
            "developer_backend": args.developer_backend,
            "jobs_dir": str(jobs_dir),
            "mode": args.mode,
            "start_loop_index": args.start_loop_index,
            "seed_trial": seed_candidate,
            "seed_archive": str(seed_archive) if seed_archive else None,
            "warm_start_latest": args.warm_start_latest,
            "warm_start_strategy": warm_start_strategy,
            "planner_mode": args.planner_mode,
            "planner_experiment_id": planner_experiment_id,
            "tester_policy": args.tester_policy,
            "verification_deferred": args.defer_verification,
            "external_verifier": args.external_verifier,
            "developer_mcp_coverage_required": args.require_developer_mcp_coverage,
            "attempts": all_attempts,
            **summarize_attempt_rewards(all_attempts),
        }
        write_json(run_dir / "summary.json", summary)
        write_summary_markdown(run_dir, summary)

        if not runtime.role_seen(loop_index, RoleName.TESTER):
            runtime.record_skipped_role(
                RoleName.TESTER,
                status=("disabled" if not args.llm_tester else "skipped_invalid_trial"),
                details={"trial_error": trial_error},
            )
        runtime.finish_loop()

        if returncode != 0:
            return returncode
        if args.stop_reward is not None and reported_reward is not None:
            if float(reported_reward) >= args.stop_reward:
                break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
