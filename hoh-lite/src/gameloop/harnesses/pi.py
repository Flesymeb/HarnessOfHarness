"""Pi Coding Agent adapter for the MiniMax-M3 profile."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

from gameloop.core.roles import RoleName
from gameloop.harnesses.base import HarnessRequest, PreparedHarness
from gameloop.harnesses.providers import (
    build_pi_settings_config,
    build_pjlab_pi_models_config,
)


class PiHarness:
    harness_id = "pi"

    def prepare(self, request: HarnessRequest) -> PreparedHarness:
        if request.binding.model != "minimax-m3":
            raise ValueError("Pi profile requires minimax-m3")
        env = dict(request.environment)
        self._hydrate_key(env)
        if not env.get("PJLAB_API_KEY"):
            raise RuntimeError("PJLAB_API_KEY or PJLAB_API_KEY_FILE is required for Pi")
        executable = shutil.which("pi", path=env.get("PATH"))
        if not executable:
            raise RuntimeError("pi executable is required")

        home = request.output_path.parent / ".pi-home"
        config_dir = home / ".pi" / "agent"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "models.json").write_text(
            json.dumps(
                build_pjlab_pi_models_config(
                    env.get("PJLAB_BASE_URL", "https://api.pjlab.org.cn/v1")
                ),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (config_dir / "settings.json").write_text(
            json.dumps(build_pi_settings_config(), indent=2) + "\n",
            encoding="utf-8",
        )
        env.update(
            {
                "HOME": str(home),
                "PI_CODING_AGENT_DIR": str(config_dir),
                "PI_OFFLINE": "1",
                "PI_TELEMETRY": "0",
                "GAMELOOP_OPENAI_BRIDGE_UPSTREAM": env.get(
                    "PJLAB_BASE_URL", "https://api.pjlab.org.cn/v1"
                ),
            }
        )
        prompt = request.prompt_path.read_text(encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "gameloop.adapters.gamecraft_bench.openai_bridge_exec",
            "--",
            executable,
            "--print",
            "--mode",
            "json",
            "--no-session",
            "--provider",
            "pjlab",
            "--model",
            "minimax-m3",
            "--thinking",
            request.binding.reasoning_effort or "high",
        ]
        if request.binding.role is RoleName.PLANNER:
            command.append("--no-tools")
        else:
            command.extend(["--tools", "read,bash,edit,write"])
        command.extend(
            [
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-context-files",
                "--no-approve",
                prompt,
            ]
        )
        return PreparedHarness(
            command=tuple(command),
            environment=env,
            stdin_path=None,
            output_mode="pi-json",
            preserved_paths=(Path(executable), Path(sys.executable)),
        )

    @staticmethod
    def _hydrate_key(env: dict[str, str]) -> None:
        if env.get("PJLAB_API_KEY"):
            return
        raw_path = env.get("PJLAB_API_KEY_FILE")
        if not raw_path:
            return
        path = Path(raw_path).expanduser()
        if path.is_file():
            env["PJLAB_API_KEY"] = path.read_text(encoding="utf-8").strip()
