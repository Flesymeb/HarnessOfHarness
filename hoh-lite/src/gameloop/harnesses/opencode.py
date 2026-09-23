"""OpenCode adapter for the DeepSeek-V4-Pro profile."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from gameloop.core.roles import RoleName
from gameloop.harnesses.base import HarnessRequest, PreparedHarness
from gameloop.harnesses.providers import build_bailian_opencode_config


class OpenCodeHarness:
    harness_id = "opencode"

    def prepare(self, request: HarnessRequest) -> PreparedHarness:
        if request.binding.model != "deepseek-v4-pro":
            raise ValueError("OpenCode profile requires deepseek-v4-pro")
        env = dict(request.environment)
        if not env.get("BAILIAN_API_KEY"):
            raise RuntimeError("BAILIAN_API_KEY is required for OpenCode")
        executable = shutil.which("opencode", path=env.get("PATH"))
        if not executable:
            raise RuntimeError("opencode executable is required")

        home = request.output_path.parent / ".opencode-home"
        config = build_bailian_opencode_config(env.get("BAILIAN_BASE_URL", ""))
        config["permission"] = (
            {"*": "deny"}
            if request.binding.role is RoleName.PLANNER
            else {"*": "allow", "task": "deny"}
        )
        config_path = home / ".config" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        env.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
        )
        prompt = request.prompt_path.read_text(encoding="utf-8")
        command = (
            executable,
            "--pure",
            "run",
            "--model",
            "bailian/deepseek-v4-pro",
            "--format",
            "json",
            "--dir",
            str(request.workspace),
            "--title",
            f"GameLoop-{request.binding.role.value.title()}",
            "--",
            prompt,
        )
        return PreparedHarness(
            command=command,
            environment=env,
            stdin_path=None,
            output_mode="opencode-json",
            preserved_paths=(Path(executable),),
        )
