"""Document helpers shared by GameLoop adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def trim_public_task_instruction(text: str, *, limit: int = 3600) -> str:
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    cut_headers = (
        "\n## Assets",
        "\n## Project layout",
        "\n## Demos",
        "\n## Submission",
        "\n## Evaluation",
        "\n### Trace file format",
    )
    cut_points = [normalized.find(header) for header in cut_headers if normalized.find(header) != -1]
    if cut_points:
        normalized = normalized[: min(cut_points)].rstrip()
    return normalized[:limit].rstrip()


def load_public_task_instruction(task_dir: Path, *, limit: int = 3600) -> str:
    for name in ("instruction.md", "README.md"):
        text = read_text_if_exists(task_dir / name).strip()
        if text:
            return trim_public_task_instruction(text, limit=limit)
    return ""


def development_doc_filename(loop_index: int) -> str:
    return f"development_doc_v{loop_index:03d}.md"
