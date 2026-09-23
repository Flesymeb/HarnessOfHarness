"""Normalize final text and usage from harness JSON streams."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def json_lines(path: Path) -> list[dict[str, Any]]:
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


def parse_harness_output(
    output_mode: str,
    *,
    stdout_path: Path,
    output_path: Path,
) -> tuple[str, dict[str, Any] | None]:
    if output_mode in {"codex", "dsh"}:
        text = (
            output_path.read_text(encoding="utf-8", errors="ignore")
            if output_path.is_file()
            else ""
        )
        usage = None
        for event in json_lines(stdout_path):
            if event.get("type") == "turn.completed" and isinstance(
                event.get("usage"), dict
            ):
                usage = event["usage"]
        if output_mode == "dsh":
            summary_path = (
                output_path.parent / "deepseek_harness/deepseek_harness_summary.json"
            )
            if summary_path.is_file():
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    summary = None
                if isinstance(summary, dict) and isinstance(
                    summary.get("usage_totals"), dict
                ):
                    usage = summary["usage_totals"]
        return text, usage

    if output_mode == "opencode-json":
        text_parts: list[str] = []
        usage = None
        for event in json_lines(stdout_path):
            if event.get("type") == "text":
                part = event.get("part")
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            elif event.get("type") == "step_finish":
                part = event.get("part")
                if isinstance(part, dict) and isinstance(part.get("tokens"), dict):
                    usage = part["tokens"]
        return "\n".join(text_parts), usage

    if output_mode == "pi-json":
        text = ""
        usage = None
        for event in json_lines(stdout_path):
            if event.get("type") not in {"turn_end", "message_end"}:
                continue
            message = event.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            content = message.get("content")
            if isinstance(content, list):
                parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                candidate = "\n".join(part for part in parts if part)
                if candidate:
                    text = candidate
            if isinstance(message.get("usage"), dict):
                usage = message["usage"]
        return text, usage

    raise ValueError(f"unknown harness output mode: {output_mode!r}")
