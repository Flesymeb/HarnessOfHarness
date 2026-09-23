"""GameLoop-owned Harbor agent adapters.

This module deliberately depends on Harbor's public installed-agent API, not
on locally patched ``gamecraft_bench.local_agents`` implementations.  A clean
upstream GameCraft-Bench checkout can therefore load it through Harbor's
``--agent-import-path`` option.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from harbor.agents.installed.base import (
    BaseInstalledAgent,
    NonZeroAgentExitCodeError,
    with_prompt_template,
)
from harbor.agents.installed.codex import Codex
from harbor.agents.installed.opencode import OpenCode, OpenCodeOptions
from harbor.agents.installed.pi import Pi, PiOptions
from harbor.agents.options import Cli
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.agent.name import AgentName
from harbor.models.trial.paths import EnvironmentPaths

from gameloop.harnesses.providers import (
    build_bailian_opencode_config,
    build_pi_settings_config,
    build_pjlab_pi_models_config,
)


_RETRYABLE_CODEX_ERROR_RE = re.compile(
    r"(?:http\s+(?:error:\s*)?|unexpected\s+status\s+|"
    r"status(?:\s+code)?[\"':=\s]+)5[0-9]{2}\b|"
    r"server\.error|internal\.error|temporarily\s+unavailable|overloaded|"
    r"stream\s+disconnected\s+before\s+completion|connection\s+reset\s+by\s+peer",
    re.IGNORECASE,
)


def is_retryable_codex_error(text: str) -> bool:
    """Recognize transport/server failures without matching IDs or prompt text."""

    return _RETRYABLE_CODEX_ERROR_RE.search(text) is not None


class GameLoopCodex(Codex):
    """Pre-installed Codex runner with MCP, auth isolation, and safe retries."""

    MAX_RETRIES = 3
    RETRY_BACKOFF_SECONDS = 30

    @staticmethod
    def name() -> str:
        return AgentName.CODEX.value

    async def install(self, environment: BaseEnvironment) -> None:
        result = await environment.exec(command="command -v codex && codex --version")
        output = (result.stdout or "") if result is not None else ""
        if result is not None and result.return_code == 0 and "codex" in output.lower():
            return
        await super().install(environment)

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        del context
        for attempt in range(self.MAX_RETRIES):
            if attempt:
                delay = self.RETRY_BACKOFF_SECONDS * attempt
                self.logger.info(
                    "retrying Codex after retryable upstream failure (%d/%d, %ds)",
                    attempt + 1,
                    self.MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
            try:
                await self._run_once(instruction, environment)
                return
            except NonZeroAgentExitCodeError:
                log_path = (EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME).as_posix()
                retryable = await self._log_has_retryable_error(environment, log_path)
                if not retryable or attempt == self.MAX_RETRIES - 1:
                    raise

    async def _run_once(
        self,
        instruction: str,
        environment: BaseEnvironment,
    ) -> None:
        if not self.model_name:
            raise ValueError("model name is required")

        model = self.model_name.split("/")[-1]
        cli_flags = self.build_cli_flags()
        cli_flags_arg = f"{cli_flags} " if cli_flags else ""
        auth_json_path = self._resolve_auth_json_path()
        remote_home = self._REMOTE_CODEX_HOME.as_posix()
        remote_secrets = self._REMOTE_CODEX_SECRETS_DIR.as_posix()
        remote_auth = (self._REMOTE_CODEX_SECRETS_DIR / "auth.json").as_posix()

        clear_base_url = os.environ.get(
            "GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL", "1"
        ) == "0"
        environment_vars: dict[str, str] = {"CODEX_HOME": remote_home}
        if clear_base_url:
            environment_vars.update({"OPENAI_BASE_URL": "", "OPENAI_API_BASE": ""})
        if auth_json_path is not None:
            environment_vars["OPENAI_API_KEY"] = ""

        await self.exec_as_agent(
            environment,
            command=(
                f'mkdir -p "$CODEX_HOME" {shlex.quote(remote_secrets)} '
                f"{shlex.quote(EnvironmentPaths.agent_dir.as_posix())}"
            ),
            env=environment_vars,
        )

        if auth_json_path is not None:
            await environment.upload_file(auth_json_path, remote_auth)
            if environment.default_user is not None:
                await self.exec_as_root(
                    environment,
                    command=f"chown {environment.default_user} {shlex.quote(remote_auth)}",
                )
            setup = f'ln -sf {shlex.quote(remote_auth)} "$CODEX_HOME/auth.json"\n'
        else:
            environment_vars["OPENAI_API_KEY"] = self._get_env("OPENAI_API_KEY") or ""
            setup = (
                f"cat >{shlex.quote(remote_auth)} <<EOF\n"
                '{\n  "OPENAI_API_KEY": "${OPENAI_API_KEY}"\n}\nEOF\n'
                f'ln -sf {shlex.quote(remote_auth)} "$CODEX_HOME/auth.json"\n'
            )

        if not clear_base_url and (base_url := self._get_env("OPENAI_BASE_URL")):
            environment_vars["OPENAI_BASE_URL"] = base_url
            setup += (
                '\ncat >>"$CODEX_HOME/config.toml" <<TOML\n'
                'openai_base_url = "${OPENAI_BASE_URL}"\n'
                "TOML"
            )
        for command in (
            self._build_register_skills_command(),
            self._build_register_mcp_servers_command(),
        ):
            if command:
                setup += f"\n{command}"
        await self.exec_as_agent(environment, command=setup, env=environment_vars)

        clear_prefix = ""
        if clear_base_url:
            clear_prefix += "unset OPENAI_BASE_URL OPENAI_API_BASE; "
        if auth_json_path is not None:
            clear_prefix += "unset OPENAI_API_KEY; "
        log_path = EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    "set -o pipefail; "
                    "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                    + clear_prefix
                    + "codex exec "
                    "--dangerously-bypass-approvals-and-sandbox "
                    "--skip-git-repo-check "
                    f"--model {shlex.quote(model)} "
                    "--json --enable unified_exec "
                    f"{cli_flags_arg}-- {shlex.quote(instruction)} "
                    f"2>&1 </dev/null | tee {shlex.quote(log_path.as_posix())}"
                ),
                env=environment_vars,
            )
        finally:
            await self._archive_and_remove_remote_home(environment, environment_vars)

    async def _archive_and_remove_remote_home(
        self,
        environment: BaseEnvironment,
        environment_vars: dict[str, str],
    ) -> None:
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    f"mkdir -p {EnvironmentPaths.agent_dir.as_posix()}\n"
                    'if [ -d "$CODEX_HOME/sessions" ]; then\n'
                    f"  rm -rf {(EnvironmentPaths.agent_dir / 'sessions').as_posix()}\n"
                    f'  cp -R "$CODEX_HOME/sessions" '
                    f"{(EnvironmentPaths.agent_dir / 'sessions').as_posix()}\n"
                    "fi"
                ),
                env=environment_vars,
            )
        except Exception:
            pass
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    f"rm -rf {shlex.quote(self._REMOTE_CODEX_SECRETS_DIR.as_posix())} "
                    '"$CODEX_HOME"'
                ),
                env=environment_vars,
            )
        except Exception:
            pass

    @staticmethod
    async def _log_has_retryable_error(
        environment: BaseEnvironment,
        log_path: str,
    ) -> bool:
        program = (
            "import pathlib,re,sys; "
            "text=pathlib.Path(sys.argv[1]).read_text(errors='ignore'); "
            f"pattern={_RETRYABLE_CODEX_ERROR_RE.pattern!r}; "
            "print('retryable' if re.search(pattern,text,re.I) else '')"
        )
        result = await environment.exec(
            command=f"python3 -c {shlex.quote(program)} {shlex.quote(log_path)}",
        )
        return bool((result.stdout or "").strip())


class LocalOpenCodeOptions(OpenCodeOptions):
    title: Annotated[str, Cli("--title")] = Field(default="GameCraft-Build")
    pure: Annotated[bool, Cli("--pure")] = Field(default=True)
    directory: Annotated[str, Cli("--dir")] = Field(default="/workspace/game")


class LocalOpenCode(OpenCode):
    """Reuse the configured host OpenCode installation."""

    options_model = LocalOpenCodeOptions

    async def install(self, environment: BaseEnvironment) -> None:
        result = await environment.exec(command="command -v opencode && opencode --version")
        if result.return_code == 0 and (result.stdout or "").strip():
            return
        raise RuntimeError("OpenCode 1.14.30 is not installed on PATH")


class BailianDeepSeekOpenCode(LocalOpenCode):
    """OpenCode 1.14.30 + Bailian DeepSeek-V4-Pro."""

    def __init__(
        self,
        *args: Any,
        opencode_config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if kwargs.get("model_name") != "bailian/deepseek-v4-pro":
            raise ValueError(
                "BailianDeepSeekOpenCode requires "
                "model_name='bailian/deepseek-v4-pro'"
            )
        config = build_bailian_opencode_config(
            os.environ.get("BAILIAN_BASE_URL", "")
        )
        if opencode_config:
            config = self._deep_merge(config, opencode_config)
        super().__init__(*args, opencode_config=config, **kwargs)

    def _build_register_config_command(self) -> str | None:
        command = super()._build_register_config_command()
        if command:
            return f"mkdir -p /workspace/game && {command}"
        return "mkdir -p /workspace/game"


class IsolatedPjlabMinimaxPiOptions(PiOptions):
    thinking: Annotated[
        Literal["off", "minimal", "low", "medium", "high", "xhigh"],
        Cli("--thinking"),
    ] = Field(default="high")


class IsolatedPjlabMinimaxPi(Pi):
    """Pi Coding Agent 0.80.10 + PJLab MiniMax-M3."""

    options_model = IsolatedPjlabMinimaxPiOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("model_name") != "pjlab/minimax-m3":
            raise ValueError(
                "IsolatedPjlabMinimaxPi requires model_name='pjlab/minimax-m3'"
            )
        self.models_config = build_pjlab_pi_models_config(
            os.environ.get("PJLAB_BASE_URL", "https://api.pjlab.org.cn/v1")
        )
        self.settings_config = build_pi_settings_config()
        super().__init__(*args, **kwargs)

    def get_version_command(self) -> str | None:
        return "pi --version"

    async def install(self, environment: BaseEnvironment) -> None:
        result = await environment.exec(command="command -v pi && pi --version")
        if result.return_code != 0 or not (result.stdout or "").strip():
            raise RuntimeError(
                "Pi 0.80.10 is not installed on PATH; install "
                "@earendil-works/pi-coding-agent"
            )

    def _build_setup_command(self) -> str:
        models = shlex.quote(json.dumps(self.models_config, ensure_ascii=True))
        settings = shlex.quote(json.dumps(self.settings_config, ensure_ascii=True))
        return (
            'test -n "${PI_CODING_AGENT_DIR:-}" && '
            'mkdir -p "$PI_CODING_AGENT_DIR" && '
            f"printf '%s\\n' {models} > \"$PI_CODING_AGENT_DIR/models.json\" && "
            f"printf '%s\\n' {settings} > \"$PI_CODING_AGENT_DIR/settings.json\" && "
            'chmod 700 "$PI_CODING_AGENT_DIR" && '
            'chmod 600 "$PI_CODING_AGENT_DIR/models.json" '
            '"$PI_CODING_AGENT_DIR/settings.json"'
        )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        del context
        if not self._has_env("PJLAB_API_KEY"):
            raise RuntimeError("PJLAB_API_KEY is required")
        await self.exec_as_agent(
            environment, command=self._build_setup_command(), cwd="/workspace"
        )
        flags = self.build_cli_flags()
        log_path = EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME
        command = (
            f"{shlex.quote(sys.executable)} -m "
            "gameloop.adapters.gamecraft_bench.openai_bridge_exec -- "
            "pi --print --mode json --no-session --provider pjlab "
            f"--model minimax-m3 {flags} "
            "--no-extensions --no-skills --no-prompt-templates "
            "--no-context-files --no-approve --tools read,bash,edit,write "
            f"{shlex.quote(instruction)} 2>&1 </dev/null | "
            f"tee {shlex.quote(log_path.as_posix())}"
        )
        await self.exec_as_agent(environment, command=command, cwd="/workspace")


class GameLoopDeepSeekHarness(BaseInstalledAgent):
    """Pinned Python SDK/JSON-RPC DeepSeek Harness developer agent."""

    @staticmethod
    def name() -> str:
        return "deepseek-harness"

    def version(self) -> str | None:
        return "0.1.0rc6"

    async def install(self, environment: BaseEnvironment) -> None:
        program = (
            "import importlib.metadata as m; "
            "assert m.version('deepseek-harness-sdk') == '0.1.0rc6'; "
            "assert m.version('deepseek-harness-runtime-bin') == '0.1.0rc6'"
        )
        result = await environment.exec(
            command=f"{shlex.quote(sys.executable)} -c {shlex.quote(program)}"
        )
        if result.return_code != 0:
            raise RuntimeError(
                "DeepSeek Harness SDK/runtime 0.1.0rc6 are not installed"
            )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        del context
        if self.model_name != "deepseek-v4-flash":
            raise ValueError(
                "GameLoopDeepSeekHarness requires model_name='deepseek-v4-flash'"
            )
        required = ("DEEPSEEK_BASE_URL", "GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS")
        missing = [name for name in required if not self._get_env(name)]
        if not (
            self._get_env("DEEPSEEK_API_KEY")
            or self._get_env("DEEPSEEK_API_KEY_FILE")
        ):
            missing.append("DEEPSEEK_API_KEY or DEEPSEEK_API_KEY_FILE")
        if missing:
            raise RuntimeError("missing DSH environment: " + ", ".join(missing))

        remote_dir = EnvironmentPaths.agent_dir / "deepseek_harness"
        remote_prompt = remote_dir / "prompt.md"
        rewrite_contract_text = getattr(
            environment, "rewrite_contract_text_for_backend", None
        )
        runtime_instruction = (
            rewrite_contract_text(instruction)
            if callable(rewrite_contract_text)
            else instruction
        )
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".md", delete=False
        ) as handle:
            handle.write(runtime_instruction)
            local_prompt = Path(handle.name)
        try:
            await self.exec_as_agent(
                environment, command=f"mkdir -p {shlex.quote(remote_dir.as_posix())}"
            )
            await environment.upload_file(local_prompt, remote_prompt.as_posix())
        finally:
            local_prompt.unlink(missing_ok=True)

        forwarded = {name: self._get_env(name) or "" for name in required}
        for name in (
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY_FILE",
            "DSH_AGENT_PRESET",
            "DSH_MAX_TOKENS",
            "DSH_REASONING_EFFORT",
            "DSH_TURN_RETRY_LIMIT",
            "GAMELOOP_DSH_STANDARD_RUNTIME",
        ):
            if value := self._get_env(name):
                forwarded[name] = value
        forwarded.update(
            {
                "DSH_MODEL": self.model_name,
                "DSH_REASONING_EFFORT": self._get_env("DSH_REASONING_EFFORT") or "high",
                "PYTHONUNBUFFERED": "1",
            }
        )
        output = remote_dir / "final_response.md"
        # Empty GameCraft templates expose /workspace but intentionally do not
        # pre-create the candidate root. Bootstrap it before selecting it as
        # both the SDK cwd and the Harbor exec cwd (notably in direct mode).
        await self.exec_as_agent(environment, command="mkdir -p /workspace/game")
        await self.exec_as_agent(
            environment,
            command=(
                f"{shlex.quote(sys.executable)} -m "
                "gameloop.harnesses.deepseek_worker "
                f"--prompt-file {shlex.quote(remote_prompt.as_posix())} "
                f"--output {shlex.quote(output.as_posix())} "
                "--workspace /workspace/game "
                f"--artifact-dir {shlex.quote(remote_dir.as_posix())}"
            ),
            env=forwarded,
            cwd="/workspace/game",
        )


__all__ = [
    "BailianDeepSeekOpenCode",
    "GameLoopCodex",
    "GameLoopDeepSeekHarness",
    "IsolatedPjlabMinimaxPi",
    "is_retryable_codex_error",
]
