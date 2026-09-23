"""Prepare and verify the pinned public Godot MCP dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Sequence

from gameloop.locations import PACKAGE_ROOT


VENDOR_ROOT = PACKAGE_ROOT / "_vendor"
LOCK_PATH = VENDOR_ROOT / "godot-mcp.lock.json"


class VendorError(RuntimeError):
    pass


_TREE_EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".godot",
    "addon",
    "coverage",
    "dist",
    "node_modules",
}


def load_lock() -> dict[str, Any]:
    try:
        value = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VendorError(f"cannot read Godot MCP lock: {error}") from error
    if not isinstance(value, dict):
        raise VendorError("Godot MCP lock must contain a JSON object")
    return value


def doctor() -> dict[str, Any]:
    lock = load_lock()
    checkout = VENDOR_ROOT / str(lock["checkout"])
    overlay = VENDOR_ROOT / str(lock["overlay"]["path"])
    expected_overlay = str(lock["overlay"]["sha256"])
    actual_overlay = _sha256(overlay) if overlay.is_file() else None
    node = shutil.which("node")
    npm = shutil.which("npm")
    source_digest, source_files = _source_tree_sha256(checkout)
    expected_source = str(lock["vendored_source"]["sha256"])
    expected_files = int(lock["vendored_source"]["file_count"])
    source_matches = source_digest == expected_source and source_files == expected_files
    checks = {
        "node": node is not None,
        "npm": npm is not None,
        "checkout": checkout.is_dir(),
        "vendored_source": source_matches,
        "overlay_digest": actual_overlay == expected_overlay,
        "server_build": (checkout / "server" / "dist" / "cli.js").is_file(),
        "server_dependencies": (
            checkout
            / "server"
            / "node_modules"
            / "@modelcontextprotocol"
            / "sdk"
            / "package.json"
        ).is_file(),
        "addon_build": (
            checkout / "server" / "addon" / "commands" / "input_commands.gd"
        ).is_file(),
    }
    return {
        "schema_version": 1,
        "tool": "gameloop-godot-mcp-vendor",
        "status": "ready" if all(checks.values()) else "blocked",
        "source_mode": "vendored",
        "source": lock["source"],
        "expected_commit": lock["commit"],
        "actual_commit": lock["commit"] if source_matches else None,
        "checkout": str(checkout),
        "source_tree_sha256": source_digest,
        "source_file_count": source_files,
        "overlay": str(overlay),
        "overlay_sha256": actual_overlay,
        "checks": checks,
    }


def prepare() -> dict[str, Any]:
    lock = load_lock()
    checkout = VENDOR_ROOT / str(lock["checkout"])
    overlay = VENDOR_ROOT / str(lock["overlay"]["path"])
    if _sha256(overlay) != str(lock["overlay"]["sha256"]):
        raise VendorError("Godot MCP overlay does not match the lock file")
    if not checkout.is_dir():
        raise VendorError(f"vendored Godot MCP source is missing: {checkout}")
    source_digest, source_files = _source_tree_sha256(checkout)
    if (
        source_digest != str(lock["vendored_source"]["sha256"])
        or source_files != int(lock["vendored_source"]["file_count"])
    ):
        raise VendorError(
            "vendored Godot MCP source does not match the locked public tree"
        )

    _run(["npm", "ci", "--ignore-scripts"], cwd=checkout / "server")
    _run(["npm", "run", "build"], cwd=checkout / "server")
    payload = doctor()
    if payload["status"] != "ready":
        raise VendorError("Godot MCP build completed but doctor remains blocked")
    return payload


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise VendorError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            + (result.stderr.strip() or result.stdout.strip())
        )


def _source_tree_sha256(checkout: Path) -> tuple[str | None, int]:
    if not checkout.is_dir():
        return None, 0
    digest = hashlib.sha256()
    count = 0
    for path in sorted(checkout.rglob("*")):
        relative = path.relative_to(checkout)
        if any(part in _TREE_EXCLUDED_DIRS for part in relative.parts):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        count += 1
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), count


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "prepare"))
    args = parser.parse_args(argv)
    try:
        payload = prepare() if args.command == "prepare" else doctor()
    except (OSError, VendorError) as error:
        payload = {
            "schema_version": 1,
            "tool": "gameloop-godot-mcp-vendor",
            "status": "blocked",
            "error": str(error),
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
