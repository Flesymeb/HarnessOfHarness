"""Validate and summarize Runtime-owned Godot MCP call receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


MAX_RECEIPTS = 5_000
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
RUNTIME_SOURCE_SUFFIXES = {
    ".cfg",
    ".cs",
    ".gd",
    ".gdshader",
    ".glb",
    ".gltf",
    ".jpeg",
    ".jpg",
    ".json",
    ".mp3",
    ".obj",
    ".ogg",
    ".png",
    ".shader",
    ".svg",
    ".tres",
    ".tscn",
    ".wav",
    ".webp",
}
RUNTIME_SOURCE_IGNORED_DIRS = {".godot", ".import", "demo_outputs", "reports"}


def summarize_godot_mcp_evidence(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=False)
    tools: set[str] = set()
    actions: set[str] = set()
    categories: set[str] = set()
    projects: set[str] = set()
    call_count = 0
    image_count = 0
    invalid_receipts = 0
    invalid_images = 0
    category_counts: dict[str, int] = {}
    active_cycle: set[str] | None = None
    active_cycle_stop_at_ms: int | None = None
    debug_cycle_count = 0
    run_count = 0
    abandoned_debug_cycle_count = 0
    last_completed_debug_cycle_at_ms: int | None = None

    receipts = list(sorted(root.glob("call-*.json"))) if root.is_dir() else []
    if len(receipts) > MAX_RECEIPTS:
        invalid_receipts += len(receipts) - MAX_RECEIPTS
        receipts = receipts[:MAX_RECEIPTS]
    for path in receipts:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_RECEIPT_BYTES:
                raise ValueError("unsafe receipt")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not _valid_receipt(payload):
                raise ValueError("invalid receipt schema")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            invalid_receipts += 1
            continue

        call_count += 1
        tool = str(payload["tool"])
        arguments = payload.get("arguments")
        action = (
            str(arguments.get("action"))
            if isinstance(arguments, Mapping) and arguments.get("action")
            else ""
        )
        tools.add(tool)
        if action:
            actions.add(f"{tool}.{action}")
        images = payload.get("images")
        assert isinstance(images, list)
        valid_call_images = 0
        for image in images:
            if _valid_image(root, image):
                image_count += 1
                valid_call_images += 1
            else:
                invalid_images += 1

        call_categories = _call_categories(
            tool,
            action,
            arguments,
            has_valid_image=valid_call_images > 0,
        )
        categories.update(call_categories)
        for category in call_categories:
            category_counts[category] = category_counts.get(category, 0) + 1
        if tool == "godot_editor_edit" and action == "run":
            run_count += 1
            if active_cycle is not None:
                abandoned_debug_cycle_count += 1
            active_cycle = set()
            active_cycle_stop_at_ms = None
        elif active_cycle is not None:
            if active_cycle_stop_at_ms is None:
                active_cycle.update(call_categories)
                if tool == "godot_editor_edit" and action == "stop":
                    active_cycle_stop_at_ms = _mtime_ms(path)
            else:
                # Godot retains the just-ended run/editor log after stop.  Let
                # a Developer inspect that log immediately after teardown,
                # but do not let post-stop state/input/image calls manufacture
                # a playtest that did not happen while the run was live.
                active_cycle.update(call_categories & {"runtime_log"})
            if active_cycle_stop_at_ms is not None and {
                "runtime_state",
                "runtime_log",
                "interactive_input",
                "screenshot",
            }.issubset(active_cycle):
                debug_cycle_count += 1
                last_completed_debug_cycle_at_ms = max(
                    last_completed_debug_cycle_at_ms or 0,
                    active_cycle_stop_at_ms,
                )
                active_cycle = None
                active_cycle_stop_at_ms = None
        project = payload.get("expected_project")
        if isinstance(project, str) and project:
            projects.add(project)

    return {
        "schema_version": 1,
        "root": str(root),
        "status": (
            "observed"
            if call_count > 0 and invalid_receipts == 0 and invalid_images == 0
            else "invalid"
            if invalid_receipts or invalid_images
            else "missing"
        ),
        "call_count": call_count,
        "image_count": image_count,
        "tools": sorted(tools),
        "actions": sorted(actions),
        "categories": sorted(categories),
        "category_counts": dict(sorted(category_counts.items())),
        "run_count": run_count,
        "debug_cycle_count": debug_cycle_count,
        "incomplete_debug_cycle_count": abandoned_debug_cycle_count
        + int(active_cycle is not None),
        "last_completed_debug_cycle_at_ms": last_completed_debug_cycle_at_ms,
        "projects": sorted(projects),
        "invalid_receipts": invalid_receipts,
        "invalid_images": invalid_images,
    }


def mcp_coverage_gaps(
    summary: Mapping[str, Any],
    *,
    role: str,
    minimum_debug_cycles: int | None = None,
    minimum_run_count: int | None = None,
) -> list[str]:
    required = {
        "developer": {
            "project",
            "lifecycle",
            "runtime_state",
            "runtime_log",
            "interactive_input",
            "screenshot",
        },
        "tester": {
            "project",
            "lifecycle",
            "runtime_state",
            "runtime_log",
            "interactive_input",
            "screenshot",
        },
    }.get(role, set())
    observed = {
        str(item) for item in summary.get("categories", []) if isinstance(item, str)
    }
    gaps = sorted(required - observed)
    if int(summary.get("call_count", 0) or 0) <= 0:
        return ["no_successful_godot_mcp_calls", *gaps]
    if minimum_debug_cycles is None:
        # A Developer cycle must close with stop so edits are checked against
        # a fresh lifecycle.  A read-only Tester is an observer: once it has
        # covered project, run, logs, state, real input, and screenshots, the
        # Runtime-owned teardown is a sufficient close.  Requiring Tester to
        # spend its final tool call on stop caused rich real-play sessions to
        # be mislabeled as missing MCP coverage.
        minimum_debug_cycles = 1 if role == "developer" else 0
    debug_cycles = int(summary.get("debug_cycle_count", 0) or 0)
    if minimum_debug_cycles > debug_cycles:
        gaps.append(f"debug_cycles:{debug_cycles}/{minimum_debug_cycles}")
    if minimum_run_count is not None:
        run_count = int(summary.get("run_count", 0) or 0)
        if minimum_run_count > run_count:
            gaps.append(f"run_count:{run_count}/{minimum_run_count}")
    return gaps


def mcp_process_warnings(
    summary: Mapping[str, Any],
    *,
    warm_start: bool,
    coverage_gaps: list[str],
) -> list[str]:
    """Report non-fatal process misses without weakening final-cycle gates."""

    if (
        warm_start
        and not coverage_gaps
        and int(summary.get("debug_cycle_count", 0) or 0) < 2
    ):
        return ["warm_start_baseline_cycle_incomplete"]
    return []


def mcp_runtime_source_freshness_gaps(
    summary: Mapping[str, Any],
    project_dir: Path,
    *,
    grace_ms: int = 1_000,
) -> list[str]:
    """Require runtime-affecting edits to precede the last complete MCP cycle.

    Reports, deterministic replay traces, Godot import metadata, and the vendored
    MCP addon are validated or managed elsewhere and do not invalidate a runtime
    playtest.  ``project.godot`` is also ignored because MCP lifecycle cleanup
    restores it after stopping the editor.
    """

    completed_at = summary.get("last_completed_debug_cycle_at_ms")
    if not isinstance(completed_at, (int, float)):
        return []
    project_dir = project_dir.expanduser().resolve(strict=False)
    if not project_dir.is_dir():
        return ["runtime_source_root_missing"]

    latest: tuple[int, Path] | None = None
    for path in project_dir.rglob("*"):
        try:
            relative = path.relative_to(project_dir)
        except ValueError:
            continue
        if any(part in RUNTIME_SOURCE_IGNORED_DIRS for part in relative.parts):
            continue
        if relative.parts[:2] == ("addons", "godot_mcp"):
            continue
        if path.name == "project.godot" or path.suffix.lower() in {".import", ".uid"}:
            continue
        if path.suffix.lower() not in RUNTIME_SOURCE_SUFFIXES:
            continue
        try:
            if not path.is_file() or path.is_symlink():
                continue
            modified_at_ms = path.stat().st_mtime_ns // 1_000_000
        except OSError:
            continue
        if latest is None or modified_at_ms > latest[0]:
            latest = (modified_at_ms, relative)

    if latest is None or latest[0] <= int(completed_at) + max(0, grace_ms):
        return []
    return [f"runtime_source_changed_after_last_debug_cycle:{latest[1].as_posix()}"]


def _valid_receipt(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("schema_version") == 1
        and value.get("source") == "gameloop.godot-mcp-evidence"
        and value.get("completed") is True
        and isinstance(value.get("tool"), str)
        and bool(str(value.get("tool")).strip())
        and isinstance(value.get("images"), list)
    )


def _mtime_ms(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns // 1_000_000
    except OSError:
        return None


def _call_categories(
    tool: str,
    action: str,
    arguments: Mapping[str, Any] | Any,
    *,
    has_valid_image: bool,
) -> set[str]:
    categories: set[str] = set()
    if tool == "godot_project" and action == "get_info":
        categories.add("project")
    if tool == "godot_editor_edit" and action in {"run", "stop"}:
        categories.add("lifecycle")
    if tool in {"godot_runtime_state", "godot_node_read", "godot_project"}:
        categories.add("state")
    if tool == "godot_runtime_state" and action == "digest":
        categories.add("runtime_state")
    if tool == "godot_editor_read" and action in {
        "get_state",
        "get_log_messages",
        "get_runtime_log_messages",
    }:
        categories.add("state")
    if tool == "godot_editor_read" and action in {
        "get_log_messages",
        "get_runtime_log_messages",
    }:
        categories.add("runtime_log")
    if (
        tool == "godot_input"
        and isinstance(arguments, Mapping)
        and (
            (
                action == "sequence"
                and isinstance(arguments.get("inputs"), list)
                and arguments["inputs"]
            )
            or (action == "type_text" and bool(arguments.get("text")))
        )
    ):
        categories.add("input")
        categories.add("interactive_input")
    if (
        tool == "godot_game_time"
        and isinstance(arguments, Mapping)
        and isinstance(arguments.get("inputs"), list)
        and arguments["inputs"]
    ):
        categories.add("input")
        categories.add("interactive_input")
    if has_valid_image and tool == "godot_editor_read" and action in {
        "screenshot_game",
        "screenshot_editor",
    }:
        categories.add("screenshot")
    if (
        tool == "godot_input"
        and isinstance(arguments, Mapping)
        and isinstance(arguments.get("screenshot_at_ms"), list)
        and arguments["screenshot_at_ms"]
        and has_valid_image
    ):
        categories.add("screenshot")
    return categories


def _valid_image(root: Path, value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    relative = value.get("path")
    expected = value.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        return False
    raw = Path(relative)
    if raw.is_absolute():
        return False
    path = (root / raw).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return False
    if path.is_symlink() or not path.is_file():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == expected
