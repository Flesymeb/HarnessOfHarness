"""Loop-stage naming helpers."""

from __future__ import annotations


def loop_tag(loop_index: int) -> str:
    return f"loop-{loop_index:02d}"
