"""Public artifact readers for GameCraft-Bench trials and jobs."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from gameloop.core.documents import read_json
from gameloop.core.stages import loop_tag


IMAGE_MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_MEDIA_SUFFIXES = {".mp4", ".webm"}
GAME_SNAPSHOT_IGNORE_PATTERNS = (".godot", "*.import", "*.tmp")
SUPPORTED_DEMO_EVENT_TYPES = frozenset(
    {
        "mouse_click",
        "mouse_down",
        "mouse_up",
        "mouse_move",
        "key_press",
        "key_down",
        "key_up",
        "wait",
    }
)
MOUSE_DEMO_EVENT_TYPES = frozenset({"mouse_click", "mouse_down", "mouse_up", "mouse_move"})
KEY_DEMO_EVENT_TYPES = frozenset({"key_press", "key_down", "key_up"})
SUPPORTED_DEMO_KEYCODES = frozenset(
    {
        "ESCAPE", "ENTER", "SPACE", "TAB", "BACKSPACE", "DELETE",
        "UP", "DOWN", "LEFT", "RIGHT", "SHIFT", "CTRL", "ALT",
        *"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    }
)
DEMO_EVIDENCE_RELATIVE_PATHS = [
    Path("sandbox/workspace/game/reports/playtest/demo_evidence_matrix.json"),
    Path("sandbox/workspace/game/reports/test/demo_evidence_matrix.json"),
    Path("sandbox/workspace/game/demo_evidence_matrix.json"),
]
VISUAL_TESTER_REPORT_RELATIVE_PATHS = [
    Path("visual_playtest_report.json"),
    Path("sandbox/workspace/game/reports/playtest/visual_playtest_report.json"),
]


def has_judge_infrastructure_failure(breakdown: dict[str, Any] | None) -> bool:
    """Return whether a verifier score is incomplete because its judge failed.

    Missing demos or replay frames are candidate failures and remain comparable
    zero scores. Other per-demo judge failures mean the recorded aggregate may be
    zero or only partially scored, so callers must rejudge it.
    """
    for value in (breakdown or {}).get("errors") or []:
        error = str(value)
        lowered = error.lower()
        if (
            error.startswith("judge failed on ")
            and "no sampled frames" not in error
        ):
            return True
        if "replay failed" in lowered and any(
            marker in lowered
            for marker in (
                "required tool not on path",
                "command not found",
                "no such file or directory",
                "ffmpeg",
                "ffprobe",
            )
        ):
            return True
        if any(
            marker in lowered
            for marker in (
                "responses api call failed",
                "server disconnected without sending a response",
                "score_formula evaluation failed",
                "judge returned non-numeric score",
                "no godot binary configured",
                "no free x display",
                "xvfb on :",
            )
        ):
            return True
    return False


def summarize_breakdown(breakdown: dict[str, Any] | None) -> dict[str, Any]:
    if not breakdown:
        return {}
    return {
        "reward": breakdown.get("reward"),
        "build_ok": breakdown.get("build_ok"),
        "judge": breakdown.get("judge"),
        "errors": breakdown.get("errors") or [],
        "num_demos": len(breakdown.get("demos") or []),
    }


def validate_demo_trace_schema(trial_dir: Path) -> list[str]:
    """Validate the public event contract before a trial seeds another loop."""

    demo_dir = trial_dir / "sandbox" / "workspace" / "game" / "demo_outputs"
    project_file = trial_dir / "sandbox" / "workspace" / "game" / "project.godot"
    traces = sorted(demo_dir.glob("*.json"))[:10]
    errors: list[str] = []
    if not traces:
        # Lightweight unit-test fixtures and dry-run records may not contain a
        # materialized Godot workspace. Only enforce the benchmark contract on
        # a real candidate project.
        return ["demo_outputs contains no JSON traces"] if project_file.is_file() else []

    for path in traces:
        try:
            trace = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: invalid JSON ({exc})")
            continue
        if not isinstance(trace, dict):
            errors.append(f"{path.name}: trace root must be an object")
            continue
        # Upstream replay defaults an omitted duration to zero and extends the
        # recording through the final event frame. Do not reject a trace that
        # the unmodified benchmark can replay.
        try:
            int(trace.get("duration_frames", 0))
        except (TypeError, ValueError, OverflowError):
            errors.append(f"{path.name}: duration_frames must be integer-convertible")
        events = trace.get("events", [])
        if not isinstance(events, list):
            errors.append(f"{path.name}: events must be a list")
            continue
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                errors.append(f"{path.name}: event {index} must be an object")
                continue
            try:
                int(event["frame"])
            except (KeyError, TypeError, ValueError, OverflowError):
                errors.append(f"{path.name}: event {index} needs an integer-convertible frame")
            event_type = event.get("type")
            if event_type not in SUPPORTED_DEMO_EVENT_TYPES:
                errors.append(
                    f"{path.name}: event {index} uses unsupported type "
                    f"{event_type!r}"
                )
            if event_type in MOUSE_DEMO_EVENT_TYPES:
                # Upstream replay reads x/y directly; a position array is not
                # an accepted substitute and otherwise crashes with KeyError.
                for axis in ("x", "y"):
                    try:
                        int(event[axis])
                    except (KeyError, TypeError, ValueError, OverflowError):
                        errors.append(
                            f"{path.name}: event {index} needs an integer-convertible {axis}"
                        )
                button = str(event.get("button", "left")).strip().lower()
                if event_type != "mouse_move" and button not in {"left", "right"}:
                    errors.append(f"{path.name}: event {index} has unsupported mouse button")
            if event_type in KEY_DEMO_EVENT_TYPES:
                keycode = str(event.get("keycode", "")).strip().upper()
                if keycode not in SUPPORTED_DEMO_KEYCODES:
                    errors.append(
                        f"{path.name}: event {index} needs a supported keycode"
                    )
    return errors


def deterministic_directory_sha256(
    directory: Path,
    *,
    ignore_names: set[str] | None = None,
) -> str:
    """Hash a directory by relative path, node type, symlink target, and bytes."""

    root = directory.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Directory does not exist: {root}")
    ignored = (
        tuple(ignore_names) if ignore_names is not None else GAME_SNAPSHOT_IGNORE_PATTERNS
    )
    digest = hashlib.sha256()
    for path in sorted(
        root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()
    ):
        relative_path = path.relative_to(root)
        if any(
            fnmatch.fnmatch(part, pattern)
            for part in relative_path.parts
            for pattern in ignored
        ):
            continue
        digest.update(
            relative_path.as_posix().encode("utf-8", errors="surrogateescape")
        )
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            digest.update(b"F")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        elif path.is_dir():
            digest.update(b"D")
        digest.update(b"\0")
    return digest.hexdigest()


def copy_game_snapshot(source_game_dir: Path, destination_game_dir: Path) -> str:
    """Copy one immutable game snapshot and return its deterministic SHA-256."""

    source = source_game_dir.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Game directory does not exist: {source}")
    if destination_game_dir.exists():
        raise FileExistsError(
            f"Refusing to overwrite game snapshot: {destination_game_dir}"
        )
    destination_game_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination_game_dir,
        ignore=shutil.ignore_patterns(*GAME_SNAPSHOT_IGNORE_PATTERNS),
    )
    # The Runtime injects this addon only to provide role-scoped MCP control.
    # A warm-start/public snapshot must contain candidate-authored game bytes,
    # not the orchestration bridge or its temporary project settings.
    runtime_addon = destination_game_dir / "addons" / "godot_mcp"
    if runtime_addon.exists():
        shutil.rmtree(runtime_addon)
        try:
            runtime_addon.parent.rmdir()
        except OSError:
            pass
    project_file = destination_game_dir / "project.godot"
    if project_file.is_file():
        from gameloop.tools.godot_mcp import remove_mcp_project_config

        project_file.write_text(
            remove_mcp_project_config(
                project_file.read_text(encoding="utf-8", errors="ignore")
            ),
            encoding="utf-8",
        )
    return deterministic_directory_sha256(destination_game_dir)


def build_screenshot_manifest(trial_dir: Path) -> dict[str, Any]:
    media: list[dict[str, Any]] = []
    seen: set[Path] = set()

    def append(path: Path, kind: str) -> None:
        if path in seen or not path.is_file() or len(media) >= 60:
            return
        seen.add(path)
        try:
            relative = path.relative_to(trial_dir).as_posix()
        except ValueError:
            relative = str(path)
        media.append({"kind": kind, "path": relative})

    def representative_frames(paths: list[Path]) -> list[Path]:
        if len(paths) <= 3:
            return paths
        return [paths[0], paths[len(paths) // 2], paths[-1]]

    if trial_dir.exists():
        game_dir = trial_dir / "sandbox" / "workspace" / "game"
        for path in sorted((game_dir / "demo_outputs").glob("*.json"))[:10]:
            append(path, "demo_trace")

        demos_dir = trial_dir / "verifier" / "demos"
        for path in sorted(demos_dir.glob("**/*")):
            if path.suffix.lower() in VIDEO_MEDIA_SUFFIXES:
                append(path, "video")
        for frames_dir in sorted(demos_dir.glob("*/frames")):
            frames = [
                path
                for path in sorted(frames_dir.iterdir())
                if path.suffix.lower() in IMAGE_MEDIA_SUFFIXES
            ]
            for path in representative_frames(frames):
                append(path, "screenshot")

        report_roots = (
            game_dir / "reports" / "screens",
            game_dir / "reports" / "playtest",
        )
        for root in report_roots:
            for path in sorted(root.glob("**/*")):
                if path.suffix.lower() in IMAGE_MEDIA_SUFFIXES:
                    append(path, "screenshot")
    return {
        "schema_version": 1,
        "source": "public_visual_evidence_manifest",
        "trial_dir": str(trial_dir),
        "media": media,
    }


def empty_screenshot_manifest(trial_dir: Path | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "public_visual_evidence_manifest",
        "trial_dir": "" if trial_dir is None else str(trial_dir),
        "media": [],
    }


def find_demo_evidence_matrix(trial_dir: Path) -> Path | None:
    for relative_path in DEMO_EVIDENCE_RELATIVE_PATHS:
        candidate = trial_dir / relative_path
        if candidate.is_file():
            return candidate
    return None


def load_demo_evidence_from_trial(trial: dict[str, Any] | None) -> dict[str, Any] | None:
    if not trial:
        return None

    configured_path = trial.get("demo_evidence_matrix_path")
    path = Path(configured_path) if configured_path else None
    if path is None and trial.get("trial_dir"):
        path = find_demo_evidence_matrix(Path(str(trial["trial_dir"])))
    if path is None or not path.is_file():
        return None
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_next_loop_evidence_from_trial(
    trial: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Load independent Tester evidence; never promote Developer self-reports as QA."""
    if not trial or not trial.get("trial_dir"):
        return None

    trial_dir = Path(str(trial["trial_dir"]))
    for relative_path in VISUAL_TESTER_REPORT_RELATIVE_PATHS:
        data = load_next_loop_evidence_report(trial_dir / relative_path)
        if data is not None:
            return data
    return None


def load_next_loop_evidence_report(path: Path) -> dict[str, Any] | None:
    """Load one public outer-tester report when it targets the next loop."""
    if not path.is_file():
        return None
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and data.get("phase") == "next_loop":
        return data
    return None


def parse_trial_result(result_path: Path) -> dict[str, Any]:
    result = read_json(result_path)
    trial_dir = result_path.parent
    breakdown_path = trial_dir / "verifier" / "breakdown.json"
    breakdown = None
    if breakdown_path.exists():
        try:
            breakdown = read_json(breakdown_path)
        except json.JSONDecodeError:
            breakdown = None

    reward = None
    try:
        reward = float(((result.get("verifier_result") or {}).get("rewards") or {}).get("reward"))
    except (TypeError, ValueError):
        pass
    if reward is None and breakdown is not None:
        try:
            reward = float(breakdown.get("reward"))
        except (TypeError, ValueError):
            reward = None
    demo_evidence_path = find_demo_evidence_matrix(trial_dir)

    return {
        "trial_name": result.get("trial_name") or trial_dir.name,
        "task_name": result.get("task_name"),
        "trial_dir": str(trial_dir),
        "reward": reward,
        "exception_info": result.get("exception_info"),
        "agent_result": result.get("agent_result"),
        "breakdown_path": str(breakdown_path) if breakdown_path.exists() else None,
        "breakdown_summary": summarize_breakdown(breakdown),
        "demo_evidence_matrix_path": str(demo_evidence_path) if demo_evidence_path else None,
    }


def trial_seed_from_dir(trial_dir: Path) -> dict[str, Any]:
    trial_dir = trial_dir.expanduser().resolve()
    game_dir = trial_dir / "sandbox" / "workspace" / "game"
    if not game_dir.is_dir():
        raise SystemExit(f"Seed trial has no game directory: {game_dir}")
    trace_errors = validate_demo_trace_schema(trial_dir)
    if trace_errors:
        details = "; ".join(trace_errors[:8])
        suffix = " ..." if len(trace_errors) > 8 else ""
        raise SystemExit(
            "Seed trial has invalid public demo traces; refusing to continue: "
            f"{details}{suffix}"
        )
    demo_count = len(list((game_dir / "demo_outputs").glob("*.json")))
    return {
        "trial_name": trial_dir.name,
        "trial_dir": str(trial_dir),
        "reward": None,
        "evaluated": True,
        "breakdown_summary": {
            "reward": None,
            "build_ok": (game_dir / "project.godot").is_file(),
            "judge": None,
            "errors": [],
            "num_demos": demo_count,
        },
        "demo_evidence_matrix_path": str(find_demo_evidence_matrix(trial_dir) or ""),
    }


def select_resume_trial(run_dir: Path) -> tuple[Path, int, str]:
    """Select the latest completed, valid loop without using partial work."""

    run_dir = run_dir.expanduser().resolve()
    try:
        summary = read_json(run_dir / "summary.json")
        receipt = read_json(run_dir / "runtime_receipt.json")
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read completed run records in {run_dir}") from error
    if summary.get("run_id") != run_dir.name:
        raise ValueError("run summary does not match its directory")
    if receipt.get("schema_version") != 1:
        raise ValueError("runtime receipt has an unsupported schema")
    attempts = summary.get("attempts")
    events = receipt.get("events")
    if not isinstance(attempts, list) or not isinstance(events, list):
        raise ValueError("run summary or runtime receipt has invalid structure")
    tested_loops = {
        event.get("loop_index")
        for event in events
        if isinstance(event, dict) and event.get("role") == "tester"
    }
    active_loop = receipt.get("active_loop")
    if active_loop is not None and (not isinstance(active_loop, int) or active_loop < 1):
        raise ValueError("runtime receipt has an invalid active loop")
    for attempt in reversed(attempts):
        if not isinstance(attempt, dict):
            continue
        loop_index = attempt.get("attempt")
        trial = attempt.get("reported_trial")
        if (
            not isinstance(loop_index, int)
            or loop_index not in tested_loops
            or (isinstance(active_loop, int) and loop_index >= active_loop)
            or attempt.get("returncode") != 0
            or not attempt.get("trial_valid")
            or not isinstance(trial, dict)
        ):
            continue
        trial_path = trial.get("trial_dir")
        if isinstance(trial_path, str) and Path(trial_path).is_dir():
            task = summary.get("task")
            if not isinstance(task, str) or not task:
                raise ValueError("run summary has no task identity")
            return Path(trial_path), loop_index + 1, task
    raise ValueError("run has no completed valid trial to continue from")


def archive_seed_game(run_dir: Path, seed_trial: dict[str, Any], prior_loop_index: int) -> Path | None:
    trial_dir = Path(str(seed_trial.get("trial_dir") or ""))
    game_dir = trial_dir / "sandbox" / "workspace" / "game"
    if not game_dir.is_dir():
        return None
    archive_dir = run_dir / "seed_archive" / f"{loop_tag(max(prior_loop_index, 1))}-game"
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(game_dir, archive_dir, ignore=shutil.ignore_patterns(".godot", "*.tmp"))
    return archive_dir


def collect_job_results(jobs_dir: Path, job_name: str) -> list[dict[str, Any]]:
    job_dir = jobs_dir / job_name
    if not job_dir.exists():
        return []
    trials = []
    for result_path in sorted(job_dir.glob("*/result.json")):
        try:
            trials.append(parse_trial_result(result_path))
        except (OSError, json.JSONDecodeError) as exc:
            trials.append(
                {
                    "trial_name": result_path.parent.name,
                    "trial_dir": str(result_path.parent),
                    "reward": None,
                    "parse_error": str(exc),
                }
            )
    return trials


def latest_trial(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    return items[-1]
