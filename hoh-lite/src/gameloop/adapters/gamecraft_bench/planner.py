"""Project Planner harness invocation for GameCraft loop stages."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from gameloop.adapters.gamecraft_bench.experiments import EXPERIMENT_SPECS
from gameloop.adapters.gamecraft_bench.paths import SRC_ROOT
from gameloop.core.documents import write_json
from gameloop.core.harness_runner import run_role_command as run_command_with_idle_timeout
from gameloop.core.roles import (
    GodotMCPAccess,
    RoleBinding,
    RoleName,
    WorkspaceAccess,
)
from gameloop.harnesses import HarnessRuntime
from gameloop.harnesses.output import parse_harness_output


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OVERLAY_HEADING = "## Project Planner Priorities"
_OVERLAY_SUBHEADINGS = (
    "### Priority Order",
    "### Preservation Gate",
    "### Acceptance Gate",
)
_MIN_TEMPLATE_SIMILARITY = 0.90
_MAX_PLANNER_ATTEMPTS = 2
_REQUIRED_DOCUMENT_HEADINGS = (
    "## Public Task Brief",
    "## Development Focus For This Loop",
    "## Mechanics Requirements",
    "## Content And Progression Requirements",
    "## Difficulty Requirements",
    "## Visual And Feedback Requirements",
    "## Demo Trace Requirements",
)


@dataclass(frozen=True)
class PlannerRun:
    document: str
    status: dict[str, Any]


def _clean_overlay(text: str) -> str:
    cleaned = _ANSI_RE.sub("", text).strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]).strip()
    heading_position = cleaned.find(_OVERLAY_HEADING)
    if heading_position >= 0:
        cleaned = cleaned[heading_position:]
    return cleaned.rstrip() + "\n" if cleaned else ""


def _validate_overlay(overlay: str, *, scaffold_document: str) -> list[str]:
    errors: list[str] = []
    if not overlay.startswith(_OVERLAY_HEADING + "\n"):
        errors.append(f"overlay must start with {_OVERLAY_HEADING!r}")
    for heading in _OVERLAY_SUBHEADINGS:
        if heading not in overlay:
            errors.append(f"missing required overlay heading {heading!r}")
    priority_count = len(re.findall(r"(?m)^\d+\.\s+", overlay))
    if not 1 <= priority_count <= 3:
        errors.append("overlay must contain between one and three priorities")
    if len(overlay) < 300:
        errors.append("overlay is too short to contain actionable priorities")
    if len(overlay) > max(300, len(scaffold_document) // 5):
        errors.append("overlay exceeds the template-constrained size limit")
    return errors


def _compose_constrained_document(
    scaffold_document: str,
    overlay: str,
) -> str:
    marker = "## Development Focus For This Loop\n"
    if marker not in scaffold_document:
        raise ValueError("scaffold is missing the development-focus section")
    return scaffold_document.replace(
        marker,
        marker + "\n" + overlay.rstrip() + "\n\n",
        1,
    )


def _template_similarity(scaffold_document: str, document: str) -> float:
    if not scaffold_document or not document:
        return 0.0
    # The composed document preserves every scaffold byte and only inserts the
    # bounded Planner overlay. This symmetric length score is therefore the
    # exact Dice similarity for the retained scaffold content.
    return (2.0 * len(scaffold_document)) / (
        len(scaffold_document) + len(document)
    )


def _validate_document(document: str, *, expected_title: str) -> list[str]:
    errors: list[str] = []
    if not document.startswith(expected_title + "\n"):
        errors.append(f"document must start with {expected_title!r}")
    for heading in _REQUIRED_DOCUMENT_HEADINGS:
        if heading not in document:
            errors.append(f"missing required heading {heading!r}")
    if len(document) < 1200:
        errors.append("document is too short to be a usable development plan")
    return errors


def _json_lines(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _codex_usage(stdout_path: Path) -> dict[str, Any] | None:
    usage = None
    for event in _json_lines(stdout_path):
        if event.get("type") == "turn.completed" and isinstance(
            event.get("usage"), dict
        ):
            usage = event["usage"]
    return usage


def _planner_command(
    *,
    experiment_id: str,
    workspace: Path,
    prompt: str,
    raw_output_path: Path,
    env: dict[str, str],
    reasoning_effort: str | None,
    role_binding: RoleBinding | None = None,
) -> tuple[list[str], str]:
    spec = EXPERIMENT_SPECS[experiment_id]
    binding = role_binding or RoleBinding(
        role=RoleName.PLANNER,
        harness=spec.harness,
        model=spec.model,
        reasoning_effort=reasoning_effort or spec.reasoning_effort,
        workspace_access=WorkspaceAccess.READ_ONLY,
        godot_mcp=GodotMCPAccess.DISABLED,
    )
    if binding.role is not RoleName.PLANNER:
        raise ValueError("Project Planner requires a planner role binding")
    prepared = HarnessRuntime().prepare_role(
        binding=binding,
        workspace=workspace,
        prompt_path=workspace.parent / "planner_prompt.md",
        output_path=raw_output_path,
        environment=env,
        json_stream=True,
    )
    env.clear()
    env.update(prepared.environment)
    return list(prepared.command), (
        "stdin" if prepared.output_mode == "codex" else prepared.output_mode
    )


def run_project_planner(
    *,
    attempt_dir: Path,
    loop_index: int,
    prompt: str,
    scaffold_document: str,
    experiment_id: str,
    environment: dict[str, str],
    reasoning_effort: str | None,
    wall_timeout_seconds: int,
    idle_timeout_seconds: int,
    dry_run: bool,
    role_binding: RoleBinding | None = None,
) -> PlannerRun:
    planner_dir = attempt_dir / "planner"
    workspace = planner_dir / "workspace"
    planner_dir.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    prompt_path = planner_dir / "planner_prompt.md"
    raw_output_path = planner_dir / "planner_raw_output.md"
    composed_output_path = planner_dir / "planner_composed_document.md"
    stdout_path = planner_dir / "planner.stdout.log"
    stderr_path = planner_dir / "planner.stderr.log"
    status_path = planner_dir / "planner_status.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    (planner_dir / "scaffold_development_document.md").write_text(
        scaffold_document, encoding="utf-8"
    )

    spec = EXPERIMENT_SPECS[experiment_id]
    binding = role_binding or RoleBinding(
        role=RoleName.PLANNER,
        harness=spec.harness,
        model=spec.model,
        reasoning_effort=reasoning_effort or spec.reasoning_effort,
        workspace_access=WorkspaceAccess.READ_ONLY,
        godot_mcp=GodotMCPAccess.DISABLED,
    )
    if binding.role is not RoleName.PLANNER:
        raise ValueError("Project Planner requires a planner role binding")

    expected_title = f"# GameCraft development document v{loop_index:03d}"
    if dry_run:
        status = {
            "status": "dry_run",
            "used_fallback": True,
            "document_source": "deterministic_template",
            "planner_strategy": "template_constrained_overlay",
            "template_similarity": 1.0,
            "scaffold_retention": 1.0,
            "attempts": 0,
            "fallback_reason": "dry_run",
            "experiment_id": experiment_id,
            "harness": binding.harness,
            "model": binding.model,
            "loop_index": loop_index,
            "prompt": str(prompt_path),
        }
        write_json(status_path, status)
        return PlannerRun(scaffold_document, status)

    planner_env = dict(environment)
    pythonpath = planner_env.get("PYTHONPATH", "")
    planner_env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(SRC_ROOT), pythonpath) if part
    )

    started = time.monotonic()
    document = ""
    overlay = ""
    template_similarity = 1.0
    usage = None
    error = None
    result = None
    output_mode = ""
    attempts = 0
    usage_by_attempt: list[dict[str, Any] | None] = []
    for attempt in range(1, _MAX_PLANNER_ATTEMPTS + 1):
        attempts = attempt
        result = None
        usage = None
        overlay = ""
        try:
            command, output_mode = _planner_command(
                experiment_id=experiment_id,
                workspace=workspace,
                prompt=prompt_path.read_text(encoding="utf-8"),
                raw_output_path=raw_output_path,
                env=planner_env,
                reasoning_effort=reasoning_effort,
                role_binding=binding,
            )
            stdin_path = prompt_path if output_mode == "stdin" else None
            result = run_command_with_idle_timeout(
                command,
                cwd=workspace,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                wall_timeout_seconds=(
                    None if wall_timeout_seconds <= 0 else wall_timeout_seconds
                ),
                idle_timeout_seconds=idle_timeout_seconds,
                env=planner_env,
                stdin_path=stdin_path,
            )
            if output_mode == "stdin":
                raw_text = (
                    raw_output_path.read_text(encoding="utf-8", errors="ignore")
                    if raw_output_path.is_file()
                    else ""
                )
                usage = _codex_usage(stdout_path)
            else:
                raw_text, usage = parse_harness_output(
                    output_mode,
                    stdout_path=stdout_path,
                    output_path=raw_output_path,
                )
                if output_mode != "dsh":
                    raw_output_path.write_text(raw_text, encoding="utf-8")
            usage_by_attempt.append(usage)
            overlay = _clean_overlay(raw_text)
            validation_errors = _validate_overlay(
                overlay,
                scaffold_document=scaffold_document,
            )
            if not validation_errors:
                document = _compose_constrained_document(
                    scaffold_document,
                    overlay,
                )
                template_similarity = _template_similarity(
                    scaffold_document,
                    document,
                )
                validation_errors.extend(
                    _validate_document(document, expected_title=expected_title)
                )
                if template_similarity < _MIN_TEMPLATE_SIMILARITY:
                    validation_errors.append(
                        "composed document is below the minimum template similarity "
                        f"of {_MIN_TEMPLATE_SIMILARITY:.2f}"
                    )
            process_failed = result.returncode != 0 or result.timed_out
            if result.idle_timed_out:
                validation_errors.insert(0, "planner harness hit idle timeout")
            elif result.wall_timed_out:
                validation_errors.insert(0, "planner harness hit wall timeout")
            elif result.timed_out:
                validation_errors.insert(0, "planner harness timed out")
            if result.returncode != 0:
                validation_errors.insert(
                    0, f"planner harness exited with status {result.returncode}"
                )
            if not validation_errors:
                error = None
                break
            error = "; ".join(validation_errors)
            document = scaffold_document
            template_similarity = 1.0
            if process_failed or attempt == _MAX_PLANNER_ATTEMPTS:
                break
            for path in (prompt_path, raw_output_path, stdout_path, stderr_path):
                if path.exists():
                    path.replace(path.with_name(f"{path.stem}.attempt-{attempt:02d}{path.suffix}"))
            prompt_path.write_text(
                prompt.rstrip()
                + "\n\nYour previous response failed validation:\n"
                + "\n".join(f"- {item}" for item in validation_errors)
                + "\nReturn a complete corrected Project Planner Priorities overlay.\n",
                encoding="utf-8",
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            document = scaffold_document
            template_similarity = 1.0
            break

    composed_output_path.write_text(document, encoding="utf-8")

    status = {
        "status": "completed" if error is None else "fallback",
        "used_fallback": error is not None,
        "document_source": (
            "planner_harness" if error is None else "deterministic_template"
        ),
        "planner_strategy": "template_constrained_overlay",
        "template_similarity": round(template_similarity, 6),
        "scaffold_retention": 1.0,
        "overlay_chars": len(overlay),
        "attempts": attempts,
        "fallback_reason": error,
        "error": error,
        "experiment_id": experiment_id,
        "harness": binding.harness,
        "model": binding.model,
        "loop_index": loop_index,
        "duration_seconds": round(time.monotonic() - started, 3),
        "returncode": None if result is None else result.returncode,
        "timed_out": False if result is None else result.timed_out,
        "idle_timed_out": False if result is None else result.idle_timed_out,
        "wall_timed_out": False if result is None else result.wall_timed_out,
        "usage": usage,
        "usage_by_attempt": usage_by_attempt,
        "prompt": str(prompt_path),
        "raw_output": str(raw_output_path),
        "composed_output": str(composed_output_path),
    }
    write_json(status_path, status)
    return PlannerRun(document, status)
