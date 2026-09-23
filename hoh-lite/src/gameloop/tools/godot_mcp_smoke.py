"""Run a real, bounded Godot MCP lifecycle/input/state/screenshot smoke test."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

from gameloop.core.mcp_evidence import (
    mcp_coverage_gaps,
    summarize_godot_mcp_evidence,
)


REQUIRED_TOOLS = {
    "godot_editor_edit",
    "godot_editor_read",
    "godot_game_time",
    "godot_input",
    "godot_project",
    "godot_runtime_state",
}


class SmokeFailure(RuntimeError):
    """A bounded MCP smoke-test assertion or transport failure."""


def _assert_bounded_model_images(result: Mapping[str, Any], *, label: str) -> int:
    """Validate the model receives native image blocks below Codex's fallback cap."""

    images = [
        item
        for item in result.get("content", [])
        if isinstance(item, dict) and item.get("type") == "image"
    ]
    if not images:
        raise SmokeFailure(f"{label} returned no native model image")
    for item in images:
        if item.get("mimeType") != "image/jpeg":
            raise SmokeFailure(f"{label} returned a non-JPEG model preview")
        try:
            payload = base64.b64decode(str(item.get("data", "")), validate=True)
        except (ValueError, binascii.Error) as error:
            raise SmokeFailure(f"{label} returned invalid base64 image data") from error
        if not payload or len(payload) > 700 * 1024:
            raise SmokeFailure(
                f"{label} model preview is outside the 1..716800 byte budget: "
                f"{len(payload)}"
            )
    return len(images)


class StdioMCPClient:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process
        self.next_id = 1
        self.selector = selectors.DefaultSelector()
        assert process.stdout is not None
        self.selector.register(process.stdout, selectors.EVENT_READ)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 90.0,
    ) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            if not self.selector.select(remaining):
                break
            assert self.process.stdout is not None
            line = self.process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise SmokeFailure(f"{method} failed: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise SmokeFailure(f"{method} returned a malformed result")
            return result
        return_code = self.process.poll()
        detail = f"; server exited {return_code}" if return_code is not None else ""
        raise SmokeFailure(f"timed out waiting for {method}{detail}")

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout: float = 90.0,
    ) -> dict[str, Any]:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
        )
        if result.get("isError"):
            text = " ".join(
                str(item.get("text", ""))
                for item in result.get("content", [])
                if isinstance(item, dict)
            )
            raise SmokeFailure(f"{name} rejected the call: {text}")
        return result

    def _send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None or self.process.poll() is not None:
            raise SmokeFailure("Godot MCP launcher is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()


def _call_tool_until_ready(
    client: StdioMCPClient,
    name: str,
    arguments: dict[str, Any],
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Wait through the launcher's cold editor/addon startup window."""

    deadline = time.monotonic() + timeout
    last_error: SmokeFailure | None = None
    while time.monotonic() < deadline:
        try:
            return client.call_tool(name, arguments, timeout=20.0)
        except SmokeFailure as error:
            last_error = error
            message = str(error)
            if not any(
                marker in message
                for marker in (
                    "Not connected to Godot",
                    "Cannot reach Godot",
                    "Connection not ready",
                )
            ):
                raise
            if client.process.poll() is not None:
                raise SmokeFailure(
                    "Godot MCP launcher exited during cold startup"
                ) from error
            time.sleep(1.0)
    raise SmokeFailure(
        f"{name} did not become ready within {timeout:.0f}s: {last_error}"
    )


def run_smoke(project: Path, evidence_dir: Path) -> dict[str, Any]:
    project = project.expanduser().resolve()
    evidence_dir = evidence_dir.expanduser().resolve()
    if not (project / "project.godot").is_file():
        raise SmokeFailure(f"project.godot not found under {project}")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stderr_path = evidence_dir / "smoke-client.stderr.log"
    environment = os.environ.copy()
    environment["GAMELOOP_MCP_EVIDENCE_DIR"] = str(evidence_dir)
    command = [
        sys.executable,
        "-m",
        "gameloop.tools.godot_mcp",
        "serve",
        "--read-only-runtime",
        "--project",
        str(project),
    ]
    with stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            bufsize=1,
            env=environment,
            start_new_session=True,
        )
        client = StdioMCPClient(process)
        stopped = False
        try:
            initialized = client.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "gameloop-mcp-smoke", "version": "1"},
                },
                timeout=120.0,
            )
            client.notify("notifications/initialized")
            listed = client.request("tools/list")
            names = {
                str(tool.get("name"))
                for tool in listed.get("tools", [])
                if isinstance(tool, dict)
            }
            missing = sorted(REQUIRED_TOOLS - names)
            if missing:
                raise SmokeFailure(f"runtime QA profile is missing tools: {missing}")

            info = _call_tool_until_ready(
                client,
                "godot_project",
                {"action": "get_info"},
            )
            info_data = info.get("structuredContent", {})
            if Path(str(info_data.get("path", ""))).resolve() != project:
                raise SmokeFailure(f"MCP attached to the wrong project: {info_data}")

            client.call_tool("godot_editor_read", {"action": "get_state"})
            client.call_tool("godot_editor_edit", {"action": "run"}, timeout=90.0)
            before = client.call_tool(
                "godot_runtime_state", {"action": "digest", "max_nodes": 40}
            )
            driven = client.call_tool(
                "godot_input",
                {
                    "action": "sequence",
                    "inputs": [
                        {
                            "action_name": "move_right",
                            "start_ms": 0,
                            "duration_ms": 500,
                        },
                        {
                            "mouse_position": [1025, 555],
                            "start_ms": 550,
                            "duration_ms": 0,
                        },
                        {
                            "mouse_button": "left",
                            "position": [1025, 555],
                            "start_ms": 600,
                            "duration_ms": 50,
                        },
                    ],
                    "report": ["/root/Main:distance", "/root/Main:clicks"],
                    "screenshot_at_ms": [0, 650],
                    "screenshot_max_width": 1280,
                },
                timeout=90.0,
            )
            sequence_preview_count = _assert_bounded_model_images(
                driven,
                label="godot_input(sequence)",
            )
            driven_data = driven.get("structuredContent", {})
            if driven_data.get("any_changed") is not True:
                raise SmokeFailure(f"injected input did not change game state: {driven_data}")
            click_probe = (driven_data.get("report") or {}).get(
                'root.get_node("/root/Main").clicks'
            )
            if not isinstance(click_probe, dict) or click_probe.get("after") != 1:
                raise SmokeFailure(
                    f"absolute mouse click did not activate the target: {driven_data}"
                )
            after = client.call_tool(
                "godot_runtime_state", {"action": "digest", "max_nodes": 40}
            )
            client.call_tool(
                "godot_editor_read",
                {"action": "get_runtime_log_messages", "limit": 50},
            )
            screenshot = client.call_tool(
                "godot_editor_read",
                {"action": "screenshot_game", "max_width": 1280},
            )
            screenshot_preview_count = _assert_bounded_model_images(
                screenshot,
                label="godot_editor_read(screenshot_game)",
            )
            client.call_tool("godot_editor_edit", {"action": "stop"})
            stopped = True
        finally:
            if not stopped and process.poll() is None:
                try:
                    client.call_tool("godot_editor_edit", {"action": "stop"}, timeout=15.0)
                except SmokeFailure:
                    pass
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=20.0)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=12.0)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5.0)

    summary = summarize_godot_mcp_evidence(evidence_dir)
    gaps = mcp_coverage_gaps(summary, role="tester")
    if summary["status"] != "observed" or gaps:
        raise SmokeFailure(f"invalid MCP evidence: summary={summary}, gaps={gaps}")
    return {
        "status": "passed",
        "server": initialized.get("serverInfo", {}),
        "tool_count": len(names),
        "project": str(project),
        "before_entities": len(before.get("structuredContent", {}).get("entities", [])),
        "after_entities": len(after.get("structuredContent", {}).get("entities", [])),
        "absolute_clicks": click_probe["after"],
        "model_preview_count": sequence_preview_count + screenshot_preview_count,
        "model_preview_mime_type": "image/jpeg",
        "model_preview_max_bytes": 700 * 1024,
        "evidence": summary,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args(argv)
    if args.evidence_dir is None:
        with tempfile.TemporaryDirectory(prefix="gameloop-mcp-smoke-") as temporary:
            payload = run_smoke(args.project, Path(temporary))
    else:
        payload = run_smoke(args.project, args.evidence_dir)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
