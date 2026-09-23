"""Codex CLI adapter for any GameLoop role."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from gameloop.core.roles import GodotMCPAccess, WorkspaceAccess
from gameloop.harnesses.base import HarnessRequest, PreparedHarness


class CodexHarness:
    harness_id = "codex"

    def prepare(self, request: HarnessRequest) -> PreparedHarness:
        executable = shutil.which("codex", path=request.environment.get("PATH"))
        if not executable:
            raise RuntimeError("codex executable is required for the Codex harness")

        command = [
            executable,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
        ]
        if request.ephemeral:
            command.append("--ephemeral")
        if request.json_stream:
            command.append("--json")
        command.extend(
            [
                "--sandbox",
                request.sandbox_mode
                or (
                    "read-only"
                    if request.binding.workspace_access is WorkspaceAccess.READ_ONLY
                    else "workspace-write"
                ),
                "--skip-git-repo-check",
                "-C",
                str(request.workspace),
                "--model",
                request.binding.model,
                "-o",
                str(request.output_path),
            ]
        )
        configs = list(request.extra_config)
        if request.binding.reasoning_effort:
            configs.append(
                f'model_reasoning_effort="{request.binding.reasoning_effort}"'
            )
        configs.extend(self._godot_mcp_configs(request))
        for config in configs:
            command.extend(["-c", config])
        command.append("-")
        return PreparedHarness(
            command=tuple(command),
            environment=dict(request.environment),
            stdin_path=request.prompt_path,
            output_mode="codex",
            preserved_paths=(Path(executable),),
        )

    @staticmethod
    def _godot_mcp_configs(request: HarnessRequest) -> list[str]:
        access = request.binding.godot_mcp
        if access is GodotMCPAccess.DISABLED:
            return []
        raw_command = request.environment.get("GAMELOOP_GODOT_MCP_COMMAND")
        if not raw_command:
            return []
        configs = [
            "mcp_servers.godot_mcp.command="
            + json.dumps(raw_command, ensure_ascii=True)
        ]
        if access is GodotMCPAccess.READ_ONLY_RUNTIME:
            configs.append(
                'mcp_servers.godot_mcp.args=["serve", "--read-only-runtime"]'
            )
        evidence_dir = request.environment.get("GAMELOOP_MCP_EVIDENCE_DIR")
        if evidence_dir:
            configs.append(
                "mcp_servers.godot_mcp.env.GAMELOOP_MCP_EVIDENCE_DIR="
                + json.dumps(evidence_dir, ensure_ascii=True)
            )
        project = request.environment.get("GAMELOOP_GODOT_PROJECT")
        if project:
            # Codex may sanitize the MCP child environment. Pass the exact
            # candidate path through the server config as well as the role
            # process environment so cold direct-Harness projects do not fall
            # back to ``cwd/game``.
            configs.append(
                "mcp_servers.godot_mcp.env.GAMELOOP_GODOT_PROJECT="
                + json.dumps(project, ensure_ascii=True)
            )
        return configs
