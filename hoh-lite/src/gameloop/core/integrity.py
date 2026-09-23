"""Candidate source integrity helpers for read-only role enforcement."""

from __future__ import annotations

import hashlib
from pathlib import Path


_IGNORED_DIRS = {".godot", ".import", "reports", "demo_outputs", "logs"}


def candidate_source_sha256(root: Path) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    observed = False
    for path in sorted(root.rglob("*")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in _IGNORED_DIRS for part in relative.parts):
            continue
        if relative.parts[:2] == ("addons", "godot_mcp"):
            continue
        if path.name.endswith((".uid", ".import", ".tmp")):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        observed = True
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest() if observed else hashlib.sha256(b"").hexdigest()
