"""One-process-per-case DeepSeek Harness SDK worker."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
from typing import Any

from gameloop.harnesses.deepseek import (
    MINIMAL_CORDIS_SHA256,
    MINIMAL_PRESET_SHA256,
    MINIMAL_SYSTEM_PROMPT_SHA256,
    RUNTIME_VERSION,
    SDK_VERSION,
    STANDARD_CORDIS_SHA256,
    STANDARD_PRESET_SHA256,
    SOURCE_COMMIT,
    SOURCE_VERSION,
    sha256_file,
    validate_minimal_bundle,
    validate_standard_bundle,
)


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _write_jsonl(path: Path, values: list[Any]) -> None:
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(f"required Python package is not installed: {name}") from error


def _summary(events: list[dict[str, Any]], notifications: list[Any]) -> dict[str, Any]:
    event_types = Counter(str(event.get("type", "<missing>")) for event in events)
    notification_methods = Counter(item.method for item in notifications)
    tool_calls: list[str] = []
    call_names: dict[str, str] = {}
    tool_results: Counter[str] = Counter()
    tool_result_by_name: dict[str, Counter[str]] = {}
    usage_records: list[dict[str, Any]] = []
    request_header_tools: list[str] = []
    request_header_system: str | None = None
    for event in events:
        data = event.get("data")
        if isinstance(data, dict):
            usage = data.get("usage")
            if isinstance(usage, dict):
                usage_records.append(usage)
            event_type = str(event.get("type", ""))
            name = data.get("toolName") or data.get("name")
            if event_type == "tool/call" and isinstance(name, str):
                tool_calls.append(name)
                call_id = data.get("callId")
                if isinstance(call_id, str):
                    call_names[call_id] = name
            elif event_type == "tool/result":
                message = data.get("message")
                source = message.get("source") if isinstance(message, dict) else None
                call_id = source.get("callId") if isinstance(source, dict) else None
                result_name = call_names.get(str(call_id), "<unknown>")
                content = message.get("content") if isinstance(message, dict) else None
                is_error = bool(
                    isinstance(content, list)
                    and any(
                        isinstance(block, dict) and block.get("isError") is True
                        for block in content
                    )
                )
                outcome = "error" if is_error else "success"
                tool_results[outcome] += 1
                tool_result_by_name.setdefault(result_name, Counter())[outcome] += 1
            elif event_type == "request/header":
                header = data.get("header")
                if isinstance(header, dict):
                    tools = header.get("tools")
                    if isinstance(tools, list):
                        request_header_tools = [
                            str(tool["name"])
                            for tool in tools
                            if isinstance(tool, dict)
                            and isinstance(tool.get("name"), str)
                        ]
                    system = header.get("system")
                    if isinstance(system, str):
                        request_header_system = system
    return {
        "event_count": len(events),
        "event_type_counts": dict(event_types),
        "notification_count": len(notifications),
        "notification_method_counts": dict(notification_methods),
        "usage_records": usage_records,
        "usage_totals": {
            key: sum(
                value
                for record in usage_records
                for candidate, value in record.items()
                if candidate == key and isinstance(value, (int, float))
            )
            for key in sorted(
                {
                    key
                    for record in usage_records
                    for key, value in record.items()
                    if isinstance(value, (int, float))
                }
            )
        },
        "tool_calls": tool_calls,
        "tool_result_counts": dict(tool_results),
        "tool_result_by_name": {
            name: dict(counts) for name, counts in tool_result_by_name.items()
        },
        "tool_error_codes": {},
        "sandbox_unavailable_count": sum(
            "sandbox_unavailable" in json.dumps(event, ensure_ascii=False).lower()
            for event in events
        ),
        "runtime_context_snapshot_count": sum(
            "runtime-context" in str(event.get("type", "")).lower()
            for event in events
        ),
        "skill_catalog": [],
        "request_header_tools": request_header_tools,
        "request_header_system_chars": (
            len(request_header_system) if request_header_system is not None else None
        ),
        "request_header_system_sha256": (
            hashlib.sha256(request_header_system.encode()).hexdigest()
            if request_header_system is not None
            else None
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--artifact-dir", required=True)
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    prompt_path = Path(args.prompt_file).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    artifact_dir = Path(args.artifact_dir).expanduser().resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result_path = artifact_dir / "worker_result.json"
    try:
        if not workspace.is_dir() or not workspace.is_absolute():
            raise RuntimeError(f"workspace must be an existing absolute directory: {workspace}")
        if not prompt_path.is_file():
            raise RuntimeError(f"prompt file does not exist: {prompt_path}")
        sdk_version = _package_version("deepseek-harness-sdk")
        runtime_version = _package_version("deepseek-harness-runtime-bin")
        if sdk_version != SDK_VERSION or runtime_version != RUNTIME_VERSION:
            raise RuntimeError(
                "DeepSeek Harness Python version mismatch: "
                f"sdk={sdk_version}, runtime={runtime_version}; "
                f"expected {SDK_VERSION}/{RUNTIME_VERSION}"
            )
        raw_key_file = os.environ.get("DEEPSEEK_API_KEY_FILE", "").strip()
        key_file = Path(raw_key_file).expanduser() if raw_key_file else None
        if key_file is not None:
            if not key_file.is_file():
                raise RuntimeError(f"DEEPSEEK_API_KEY_FILE is not readable: {key_file}")
            os.environ["DEEPSEEK_API_KEY"] = key_file.read_text(
                encoding="utf-8"
            ).strip()
        elif not os.environ.get("DEEPSEEK_API_KEY"):
            raise RuntimeError(
                "DEEPSEEK_API_KEY or a readable DEEPSEEK_API_KEY_FILE is required"
            )
        if os.environ.get("GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS") != "1":
            raise RuntimeError(
                "standalone minimal requires explicit "
                "GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS=1"
            )
        preset_name = os.environ.get("DSH_AGENT_PRESET", "minimal").strip().lower()
        if preset_name == "minimal":
            bundle = validate_minimal_bundle()
        elif preset_name == "standard":
            bundle = validate_standard_bundle()
        else:
            raise ValueError("DSH_AGENT_PRESET must be either 'minimal' or 'standard'")
        is_minimal = preset_name == "minimal"
        cordis_sha256 = MINIMAL_CORDIS_SHA256 if is_minimal else STANDARD_CORDIS_SHA256
        preset_sha256 = MINIMAL_PRESET_SHA256 if is_minimal else STANDARD_PRESET_SHA256
        runtime_kind = (
            "official-standalone-minimal"
            if is_minimal
            else "official-sdk-host-only-standard"
        )
        os.environ.pop("DSH_SYSTEM_PROMPT", None)

        combined = artifact_dir / "deepseek_harness.cordis.yml"
        runtime_manifest = artifact_dir / "deepseek_harness_runtime_manifest.json"
        preset = artifact_dir / "deepseek_harness_preset.yml"
        context_manifest = artifact_dir / "deepseek_harness_context_manifest.json"
        shutil.copy2(bundle.cordis, combined)
        shutil.copy2(bundle.preset, preset)
        _write_json(
            runtime_manifest,
            {
                "runtime_kind": "bundled-python-wheel-executable",
                "runtime_version": runtime_version,
                "runtime_command": [str(path) for path in bundle.runtime_command],
            },
        )
        _write_json(
            context_manifest,
            {
                "agent_preset": preset_name,
                "include_harness_identity": is_minimal is False,
                "include_runtime_context": is_minimal is False,
                "tool_presentation": "native",
                "model_visible_tools": (
                    ["bash", "str_replace_editor"] if is_minimal else "standard-catalog"
                ),
                **({"system_prompt_sha256": MINIMAL_SYSTEM_PROMPT_SHA256} if is_minimal else {}),
                "sandbox_policy": "danger-full-access",
                "outer_isolation_required": True,
            },
        )
        session_root = artifact_dir / "sessions"
        dsh_home = artifact_dir / "dsh_home"
        agents_home = artifact_dir / "agents_home"
        for path in (session_root, dsh_home, agents_home):
            path.mkdir(parents=True, exist_ok=True)

        model = os.environ.get("DSH_MODEL", "deepseek-v4-flash")
        session_id = "gameloop-" + artifact_dir.parent.name
        turn_retry_limit = int(
            os.environ.get("DSH_TURN_RETRY_LIMIT", "0" if is_minimal else "2")
        )
        if turn_retry_limit < 0:
            raise RuntimeError("DSH_TURN_RETRY_LIMIT must be non-negative")
        worker_spec = {
            "provider": "deepseek-official",
            "model": model,
            "max_tokens": int(os.environ.get("DSH_MAX_TOKENS", "49152")),
            "turn_retry_limit": turn_retry_limit,
            "worktree": str(workspace),
            "session_root": str(session_root),
            "session_id": session_id,
            "prompt": prompt_path.read_text(encoding="utf-8"),
            "cordis": str(combined),
            "cordis_profile": preset_name,
            "cordis_sha256": cordis_sha256,
            "runtime_kind": runtime_kind,
            "source_commit": SOURCE_COMMIT,
            "source_version": SOURCE_VERSION,
            "agent_preset": preset_name,
            "preset_sha256": preset_sha256,
            **({"system_prompt_sha256": MINIMAL_SYSTEM_PROMPT_SHA256} if is_minimal else {}),
            "runtime_command": [str(path) for path in bundle.runtime_command],
        }
        _write_json(artifact_dir / "worker_spec.json", worker_spec)

        worker_env = {
            "DSH_CWD": str(workspace),
            "DSH_HOME": str(dsh_home),
            "DSH_AGENTS_HOME": str(agents_home),
            "DSH_MODEL": model,
            "DSH_CONTEXT_WINDOW": os.environ.get("DSH_CONTEXT_WINDOW", "131072"),
            "DSH_MAX_TOKENS": str(worker_spec["max_tokens"]),
            "DSH_REASONING_EFFORT": os.environ.get("DSH_REASONING_EFFORT", "high"),
            "NODE_USE_ENV_PROXY": "1",
            "PYTHONUNBUFFERED": "1",
        }
        from deepseek_harness import DeepSeekHarness

        with DeepSeekHarness(
            provider="deepseek-official",
            model=model,
            max_tokens=worker_spec["max_tokens"],
            cwd=str(workspace),
            runtime_cwd=str(workspace),
            session_root=str(session_root),
            cordis=str(combined),
            runtime_bin=str(bundle.runtime_command[0]),
            launch_args_override=tuple(str(path) for path in bundle.runtime_command),
            env=worker_env,
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.environ["DEEPSEEK_BASE_URL"],
        ) as harness:
            result = harness.run(worker_spec["prompt"], session_id=session_id)
            all_events = list(result.events)
            all_notifications = list(result.notifications)
            for retry_index in range(turn_retry_limit):
                if result.finish_reason == "completed":
                    break
                result = harness.run(
                    "The previous model turn ended with a recoverable protocol or tool-argument "
                    "error. Continue the same task from the current workspace. Keep tool calls "
                    "small and emit strictly valid JSON arguments. Do not restart completed work.",
                    session_id=session_id,
                )
                all_events.extend(result.events)
                all_notifications.extend(result.notifications)
            result.events = all_events
            result.notifications = all_notifications

        events_path = artifact_dir / "deepseek_harness_events.jsonl"
        notifications_path = artifact_dir / "deepseek_harness_notifications.jsonl"
        summary_path = artifact_dir / "deepseek_harness_summary.json"
        _write_jsonl(events_path, result.events)
        _write_jsonl(notifications_path, [asdict(item) for item in result.notifications])
        summary = _summary(result.events, result.notifications)
        _write_json(summary_path, summary)
        if result.finish_reason != "completed":
            raise RuntimeError(
                f"DeepSeek Harness did not complete: {result.finish_reason!r}"
            )
        if not summary["tool_calls"]:
            raise RuntimeError(f"{preset_name} DSH completed without a real tool call")
        if is_minimal:
            if summary["runtime_context_snapshot_count"]:
                raise RuntimeError("minimal DSH unexpectedly emitted runtime context")
            if summary["request_header_tools"] != ["bash", "str_replace_editor"]:
                raise RuntimeError(
                    "minimal DSH request-header tool surface mismatch: "
                    + repr(summary["request_header_tools"])
                )
            if summary["request_header_system_sha256"] != MINIMAL_SYSTEM_PROMPT_SHA256:
                raise RuntimeError("minimal DSH request-header system prompt hash mismatch")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.final_response.rstrip() + "\n", encoding="utf-8")
        payload = {
            "ok": True,
            "result": {
                "runtime_kind": runtime_kind,
                "source_commit": SOURCE_COMMIT,
                "source_version": SOURCE_VERSION,
                "agent_preset": preset_name,
                "sdk_version": sdk_version,
                "runtime_version": runtime_version,
                "session_id": result.session_id,
                "finish_reason": result.finish_reason,
                "final_response": result.final_response,
                "event_count": len(result.events),
                "notification_count": len(result.notifications),
                "events_path": str(events_path),
                "notifications_path": str(notifications_path),
                "summary_path": str(summary_path),
                "session_files": [
                    str(path)
                    for path in sorted(session_root.rglob("*"))
                    if path.is_file()
                ],
            },
        }
        _write_json(result_path, payload)
        return 0
    except Exception as error:
        _write_json(
            result_path,
            {
                "ok": False,
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
