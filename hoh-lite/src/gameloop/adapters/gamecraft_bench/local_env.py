"""GameLoop-owned local environment compatible with upstream GameCraft-Bench.

The upstream environment only implements rootless ``unshare``.  This adapter
adds bwrap and an explicit trusted-host direct fallback without requiring any
patches in the GameCraft-Bench checkout.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
import re
import select
import signal
import shlex
import shutil
import subprocess
import time

from gamecraft_bench import config
from gamecraft_bench.local_env import LocalSubprocessEnvironment
from gameloop.core.execution import terminate_process_group_pid as _terminate_group_pid
from harbor.environments.base import ExecResult


MCP_TRANSPORT_REQUIRED_ENV = "GAMELOOP_REQUIRE_DEVELOPER_MCP_TRANSPORT"


def write_mcp_shell_guard_bin(directory: Path, real_godot: str | None) -> Path:
    """Create PATH shims that keep interactive QA on Runtime-owned MCP."""

    directory.mkdir(parents=True, exist_ok=True)
    godot_guard = directory / "godot"
    godot_guard.write_text(
        "\n".join(
            (
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "allow=0",
                "for arg in \"$@\"; do",
                "  case \"$arg\" in --headless|--version) allow=1 ;; esac",
                "done",
                f"real_godot={shlex.quote(real_godot or '')}",
                "if [ \"$allow\" -eq 1 ] && [ -n \"$real_godot\" ]; then",
                "  exec \"$real_godot\" \"$@\"",
                "fi",
                "echo 'GameLoop: visual Godot shell launches are disabled when Developer MCP coverage is required. Use registered Godot MCP run/input/state/log/screenshot tools; shell Godot is limited to --headless or --version.' >&2",
                "exit 126",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    godot_guard.chmod(0o700)
    for name in ("xdotool", "ydotool"):
        path = directory / name
        path.write_text(
            "#!/usr/bin/env bash\n"
            "echo 'GameLoop: direct desktop input automation is disabled; use registered Godot MCP input tools.' >&2\n"
            "exit 126\n",
            encoding="utf-8",
        )
        path.chmod(0o700)
    return directory


async def create_exec_subprocess(
    argv: list[str],
    *,
    backend: str,
    env: dict[str, str],
) -> asyncio.subprocess.Process:
    """Start a cancellable subprocess with isolated session/process group."""

    kwargs: dict[str, object] = {
        "env": env,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    kwargs["start_new_session"] = True
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


async def terminate_process_group(pid: int, *, term_timeout: float = 1.0) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGTERM)
    deadline = asyncio.get_running_loop().time() + term_timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


def terminate_process_group_sync(
    process: subprocess.Popen[bytes], *, term_timeout: float = 1.0
) -> None:
    _terminate_group_pid(process.pid, grace_seconds=term_timeout)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=term_timeout)


def run_until_done_marker_sync(
    argv: list[str], marker: str, *, timeout: float
) -> tuple[bytes, int]:
    """Run a short command without relying on bwrap to reap its child."""

    marker_bytes = marker.encode()
    pattern = re.compile(
        rb"(?:^|\r?\n)" + re.escape(marker_bytes) + rb"(-?\d+)\r?\n"
    )
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    assert process.stdout is not None
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while True:
            match = pattern.search(output)
            if match:
                return_code = int(match.group(1))
                terminate_process_group_sync(process)
                lines = bytes(output).splitlines(keepends=True)
                cleaned = b"".join(
                    line for line in lines if not line.startswith(marker_bytes)
                )
                return cleaned, return_code

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"subprocess did not emit {marker!r}")
            readable, _, _ = select.select(
                [process.stdout.fileno()], [], [], min(remaining, 0.1)
            )
            if readable:
                chunk = os.read(process.stdout.fileno(), 65536)
                if chunk:
                    output.extend(chunk)
                    continue
            if process.poll() is not None:
                output.extend(process.stdout.read() or b"")
                match = pattern.search(output)
                if match:
                    return bytes(output), int(match.group(1))
                return bytes(output), process.returncode or 0
    finally:
        if process.poll() is None:
            terminate_process_group_sync(process)


async def communicate_until_done_marker(
    process: asyncio.subprocess.Process,
    marker: str,
) -> tuple[bytes, bytes, int]:
    """Capture output and stop bwrap once its completed child emits ``marker``."""

    marker_bytes = marker.encode()
    pattern = re.compile(
        rb"(?:^|\r?\n)" + re.escape(marker_bytes) + rb"(-?\d+)\r?\n"
    )
    marker_result: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def read_stdout() -> bytes:
        assert process.stdout is not None
        output = bytearray()
        while chunk := await process.stdout.read(65536):
            search_from = max(0, len(output) - len(marker_bytes) - 32)
            output.extend(chunk)
            match = pattern.search(output, search_from)
            if match and not marker_result.done():
                marker_result.set_result(int(match.group(1)))
        return bytes(output)

    async def read_stderr() -> bytes:
        assert process.stderr is not None
        return await process.stderr.read()

    stdout_task = asyncio.create_task(read_stdout())
    stderr_task = asyncio.create_task(read_stderr())
    wait_task = asyncio.create_task(process.wait())
    tasks = (stdout_task, stderr_task, wait_task)
    try:
        done, _ = await asyncio.wait(
            (marker_result, wait_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if marker_result in done:
            return_code = marker_result.result()
            await terminate_process_group(process.pid)
            await wait_task
        else:
            return_code = process.returncode or 0
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()

    lines = stdout.splitlines(keepends=True)
    stdout = b"".join(
        line for line in lines if not line.startswith(marker_bytes)
    )
    return stdout, stderr, return_code


class StableLocalSubprocessEnvironment(LocalSubprocessEnvironment):
    """Portable GameCraft environment with isolated-first backend selection."""

    DIRECT_BACKEND_ENV = "GAMELOOP_GAMECRAFT_ALLOW_DIRECT_BACKEND"
    BACKEND_ENV = "GAMELOOP_GAMECRAFT_BACKEND"

    @staticmethod
    def _configured_backend() -> str:
        value = (
            os.environ.get(StableLocalSubprocessEnvironment.BACKEND_ENV)
            or os.environ.get("GAMECRAFT_BENCH_LOCAL_ENV_BACKEND")
            or "auto"
        ).strip().lower()
        if value not in {"auto", "namespace", "bwrap", "direct"}:
            raise RuntimeError(
                f"{StableLocalSubprocessEnvironment.BACKEND_ENV} must be one of "
                f"auto|namespace|bwrap|direct, got {value!r}"
            )
        return value

    def _select_exec_backend(self) -> str:
        """Prefer isolation and use direct mode only after explicit opt-in."""

        configured = self._configured_backend()
        direct_allowed = os.environ.get(self.DIRECT_BACKEND_ENV) == "1"
        if configured == "direct":
            if not direct_allowed:
                raise RuntimeError(
                    f"{self.BACKEND_ENV}=direct requires "
                    f"{self.DIRECT_BACKEND_ENV}=1"
                )
            self.logger.warning(
                "using explicitly enabled direct compatibility backend; "
                "filesystem namespaces are unavailable"
            )
            return "direct"

        namespace_error: RuntimeError | None = None
        if configured in {"auto", "namespace"}:
            try:
                LocalSubprocessEnvironment._preflight_unshare()
                return "namespace"
            except RuntimeError as error:
                namespace_error = error
                if configured == "namespace":
                    raise

        bwrap_error: RuntimeError | None = None
        if configured in {"auto", "bwrap"}:
            try:
                self._preflight_bwrap()
                return "bwrap"
            except RuntimeError as error:
                bwrap_error = error
                if configured == "bwrap":
                    raise

        if direct_allowed:
            self.logger.warning(
                "namespace and bwrap are unavailable; using explicitly "
                "enabled trusted-host direct backend"
            )
            return "direct"

        raise RuntimeError(
            "No usable GameCraft local filesystem backend. "
            f"namespace failed: {namespace_error}; bwrap failed: {bwrap_error}. "
            f"On a trusted single-user host only, set {self.DIRECT_BACKEND_ENV}=1 "
            "to enable path-rewritten direct execution."
        )

    async def start(self, force_build: bool) -> None:
        """Initialize the upstream sandbox after selecting a Lite-owned backend."""

        del force_build
        self._exec_backend = self._select_exec_backend()
        self.logger.info("GameLoop local subprocess backend: %s", self._exec_backend)
        self._mcp_shell_guard_bin: Path | None = None
        if os.environ.get(MCP_TRANSPORT_REQUIRED_ENV) == "1":
            self._mcp_shell_guard_bin = write_mcp_shell_guard_bin(
                self._sandbox / "installed_agent" / "mcp-shell-guard-bin",
                shutil.which("godot"),
            )

        logs = self._sandbox / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        for name, host_dir in (
            ("verifier", self.trial_paths.verifier_dir),
            ("agent", self.trial_paths.agent_dir),
            ("artifacts", self.trial_paths.artifacts_dir),
        ):
            link = logs / name
            Path(host_dir).mkdir(parents=True, exist_ok=True)
            if link.is_symlink() or link.exists():
                if link.is_symlink():
                    link.unlink()
                else:
                    shutil.rmtree(link)
            link.symlink_to(Path(host_dir).resolve())

        self._started = True
        self._populate_workspace_template()
        self._watchdog_task = asyncio.create_task(self._stuck_godot_watchdog())
        self.logger.info(
            "Local subprocess env ready (sandbox=%s)", self._short(self._sandbox)
        )

    def _direct_path_replacements(self) -> dict[str, str]:
        replacements = {
            "/installed-agent": str(self._sandbox / "installed_agent"),
            "/tmp": str(self._runtime_tmp),
        }
        for prefix in config.PATH_REWRITE_PATTERNS:
            replacements[prefix] = str(self._host_path_for_prefix(prefix))
        for source, mountpoint in (
            (config.ASSET_LIBRARY, config.ASSET_LIBRARY_MOUNTPOINT),
            (config.OGA_LIBRARY, config.OGA_LIBRARY_MOUNTPOINT),
            (config.TOOLS_DIR, config.TOOLS_MOUNTPOINT),
        ):
            if source is not None:
                replacements[mountpoint] = str(source.resolve())
        # The public task instructions in the original Bench checkout refer
        # to ``/workspace/tools/...`` while the configured tools mountpoint is
        # ``/tools``.  Keep that upstream-facing alias in the adapter so the
        # direct backend does not first rewrite its ``/workspace`` prefix and
        # strand the helper path inside the candidate workspace.
        if config.TOOLS_DIR is not None:
            replacements["/workspace/tools"] = str(config.TOOLS_DIR.resolve())
        return replacements

    def _to_host(self, path: str | os.PathLike) -> Path:
        """Map uploaded ``/tmp`` files to the same per-trial runtime mount.

        Upstream's generic fallback stores unknown absolute paths below
        ``_root``.  Its namespace mounts a different ``_tmp`` directory at
        ``/tmp``, which makes uploaded Codex auth files invisible to the
        agent.  Keep this compatibility fix in the Lite adapter so an
        unmodified GameCraft-Bench checkout remains usable.
        """

        value = str(path)
        if value == "/tmp" or value.startswith("/tmp/"):
            return self._runtime_tmp / value.removeprefix("/tmp").lstrip("/")
        return super()._to_host(path)

    def _rewrite_direct_paths(self, value: str) -> str:
        replacements = self._direct_path_replacements()
        alternatives = "|".join(
            re.escape(path) for path in sorted(replacements, key=len, reverse=True)
        )
        pattern = re.compile(
            f"(?<![A-Za-z0-9_.-])(?:{alternatives})(?![A-Za-z0-9_.-])"
        )
        return pattern.sub(lambda match: replacements[match.group(0)], value)

    def rewrite_contract_text_for_backend(self, value: str) -> str:
        """Translate task-facing paths when the selected backend is direct.

        Normally ``exec`` rewrites container-style paths in the command it
        launches.  Agents such as DSH load their prompt from a file and issue
        later tool calls inside a child runtime, so those paths otherwise
        bypass ``exec``.  Expose the same translation for that prompt without
        changing instructions under namespace or bwrap isolation.
        """

        if getattr(self, "_exec_backend", None) == "direct":
            return self._rewrite_direct_paths(value)
        return value

    def _direct_runtime_script(self, contract_path: str) -> Path:
        """Materialize a host-path version of a mounted contract script."""

        destination = self._direct_runtime_text_file(contract_path)
        destination.chmod(0o700)
        return destination

    def _direct_runtime_text_file(self, contract_path: str) -> Path:
        """Copy one text contract with container paths rewritten for the host."""

        source = Path(self._rewrite_direct_paths(contract_path))
        relative = contract_path.lstrip("/")
        destination = self._runtime_tmp / "direct-inputs" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        rewritten = self._rewrite_direct_paths(source.read_text(encoding="utf-8"))
        destination.write_text(rewritten, encoding="utf-8")
        return destination

    @staticmethod
    def _has_mcp_runtime_ancestor(
        pid: int,
        rows: dict[int, tuple[int, int, str, str, str]],
    ) -> bool:
        """Keep Runtime-owned long-lived Godot editor/game processes alive."""

        current = pid
        seen: set[int] = set()
        while current not in seen:
            seen.add(current)
            row = rows.get(current)
            if row is None:
                return False
            parent, _etimes, _stat, _comm, args = row
            if (
                "gameloop.tools.godot_mcp" in args
                or "gameloop-godot-mcp" in args
            ):
                return True
            current = parent
        return False

    def _kill_stuck_godot_once(self) -> None:
        """Terminate only stale Godot descendants owned by this trial."""
        try:
            proc = subprocess.run(
                [
                    "ps",
                    "-eo",
                    "pid,ppid,etimes,stat,comm,args",
                    "--no-headers",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("watchdog ps failed: %s", exc)
            return

        rows: dict[int, tuple[int, int, str, str, str]] = {}
        for line in (proc.stdout or "").splitlines():
            parts = line.strip().split(None, 5)
            if len(parts) < 6:
                continue
            pid_s, ppid_s, etimes_s, stat, comm, args = parts
            try:
                rows[int(pid_s)] = (
                    int(ppid_s),
                    int(etimes_s),
                    stat,
                    comm,
                    args,
                )
            except ValueError:
                continue

        owned = {int(pid) for pid in self._active_exec_pids}
        changed = True
        while changed:
            changed = False
            for pid, (ppid, *_rest) in rows.items():
                if ppid in owned and pid not in owned:
                    owned.add(pid)
                    changed = True

        for pid in sorted(owned):
            row = rows.get(pid)
            if row is None:
                continue
            _ppid, etimes, stat, comm, args = row
            if "godot" not in comm or stat.startswith("Z"):
                continue
            if self._has_mcp_runtime_ancestor(pid, rows):
                continue
            if etimes < self.STUCK_GODOT_KILL_SEC:
                continue
            self.logger.warning(
                "watchdog killing owned stuck godot pid=%d etime=%ds args=%s",
                pid,
                etimes,
                args,
            )
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "watchdog SIGTERM pid=%d failed: %s",
                    pid,
                    exc,
                )

    @staticmethod
    def _preflight_bwrap() -> None:
        bwrap = shutil.which("bwrap")
        if not bwrap:
            raise RuntimeError("`bwrap` not found on PATH; install bubblewrap")
        marker = "__GAMECRAFT_BWRAP_PREFLIGHT_DONE__"
        command = (
            "echo bwrap-ok\n"
            "rc=$?\n"
            f"printf '\\n{marker}%s\\n' \"$rc\"\n"
            "exit \"$rc\""
        )
        try:
            output, return_code = run_until_done_marker_sync(
                [
                    bwrap,
                    "--bind",
                    "/",
                    "/",
                    "--dev-bind",
                    "/dev",
                    "/dev",
                    "--tmpfs",
                    "/tmp",
                    "--chdir",
                    "/",
                    "bash",
                    "-c",
                    command,
                ],
                marker,
                timeout=10,
            )
        except TimeoutError as exc:
            raise RuntimeError("bubblewrap preflight timed out") from exc
        if return_code != 0 or b"bwrap-ok" not in output:
            raise RuntimeError(
                "bubblewrap is installed but cannot start a local filesystem "
                f"view. bwrap output: {output.decode(errors='replace').strip()!r}"
            )

    def _bwrap_source_for_bind(self, sub: str) -> Path:
        source = self._workspace_host if sub == "workspace" else self._sandbox / sub
        if source.exists():
            return source
        empty = self._sandbox / "_empty" / sub
        empty.mkdir(parents=True, exist_ok=True)
        return empty

    def _ensure_bwrap_mountpoint(self, target: str) -> None:
        if target == "/workspace" or target.startswith("/workspace/"):
            self._to_host(target).mkdir(parents=True, exist_ok=True)

    def _build_bwrap_command(self, inner_cmd: str, inner_cwd: str) -> list[str]:
        """Build the filesystem view missing from upstream GameCraft-Bench."""

        bwrap = shutil.which("bwrap") or "bwrap"
        args = [bwrap, "--bind", "/", "/", "--dev-bind", "/dev", "/dev"]
        for sub, target in self._BIND_PLAN:
            if sub == "logs":
                args += ["--dir", "/logs"]
                for name, host_dir in (
                    ("agent", self.trial_paths.agent_dir),
                    ("verifier", self.trial_paths.verifier_dir),
                    ("artifacts", self.trial_paths.artifacts_dir),
                ):
                    Path(host_dir).mkdir(parents=True, exist_ok=True)
                    args += [
                        "--dir",
                        f"/logs/{name}",
                        "--bind",
                        str(Path(host_dir).resolve()),
                        f"/logs/{name}",
                    ]
                continue
            source = self._bwrap_source_for_bind(sub)
            self._ensure_bwrap_mountpoint(target)
            args += ["--dir", target, "--bind", str(source), target]

        for source, target in (
            (config.ASSET_LIBRARY, config.ASSET_LIBRARY_MOUNTPOINT),
            (config.OGA_LIBRARY, config.OGA_LIBRARY_MOUNTPOINT),
            (config.TOOLS_DIR, config.TOOLS_MOUNTPOINT),
        ):
            if source is None:
                continue
            self._ensure_bwrap_mountpoint(target)
            args += ["--dir", target, "--ro-bind", str(source.resolve()), target]

        self._runtime_tmp.mkdir(parents=True, exist_ok=True)
        args += ["--dir", "/tmp", "--bind", str(self._runtime_tmp), "/tmp"]
        args += ["--chdir", inner_cwd, "bash", "-c", inner_cmd]
        return args

    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        user: str | int | None = None,
    ) -> ExecResult:
        del user
        inner_cwd = cwd if cwd else "/workspace"
        xdg_data = self._sandbox / "_xdg_data"
        xdg_data.mkdir(parents=True, exist_ok=True)

        merged_env = os.environ.copy()
        merged_env["GAMECRAFT_BENCH_SANDBOX"] = str(self._sandbox)
        merged_env.update(config.env_for_subprocess())
        merged_env["GAME_PROJECT_PATH"] = config.GAME_PROJECT_PATH
        merged_env["XDG_DATA_HOME"] = str(xdg_data)
        if env:
            merged_env.update(env)

        backend = self._exec_backend or "namespace"
        if backend == "direct":
            done_marker = None
            rubric_contract = merged_env.get(
                "GAMECRAFT_BENCH_RUBRIC", "/tests/rubric.json"
            )
            merged_env = {
                key: self._rewrite_direct_paths(value)
                for key, value in merged_env.items()
            }
            if rubric_contract == "/tests" or rubric_contract.startswith("/tests/"):
                rubric_source = Path(
                    self._rewrite_direct_paths(rubric_contract)
                )
                if rubric_source.is_file():
                    merged_env["GAMECRAFT_BENCH_RUBRIC"] = str(
                        self._direct_runtime_text_file(rubric_contract)
                    )
            inner_cwd = self._rewrite_direct_paths(inner_cwd)
            direct_command = self._rewrite_direct_paths(command)
            for contract_script in ("/tests/test.sh", "/solution/solve.sh"):
                if contract_script not in command:
                    continue
                host_script = self._rewrite_direct_paths(contract_script)
                if Path(host_script).is_file():
                    direct_command = direct_command.replace(
                        host_script,
                        str(self._direct_runtime_script(contract_script)),
                    )
            argv = [
                "bash",
                "-c",
                f"cd {shlex.quote(inner_cwd)} && eval {shlex.quote(direct_command)}",
            ]
        elif backend == "bwrap" and command.strip() == "mkdir -p /installed-agent":
            command = "mkdir -p /installed_agent"
            done_marker = "__GAMECRAFT_BWRAP_DONE__"
            command_for_exec = (
                f"{command}\n"
                "rc=$?\n"
                f"printf '\\n{done_marker}%s\\n' \"$rc\"\n"
                "exit \"$rc\""
            )
            argv = self._build_bwrap_command(command_for_exec, inner_cwd)
        elif backend == "bwrap":
            done_marker = "__GAMECRAFT_BWRAP_DONE__"
            command_for_exec = (
                f"{command}\n"
                "rc=$?\n"
                f"printf '\\n{done_marker}%s\\n' \"$rc\"\n"
                "exit \"$rc\""
            )
            argv = self._build_bwrap_command(command_for_exec, inner_cwd)
        else:
            done_marker = None
            argv = self._build_ns_command(command, inner_cwd)
        guard_bin = getattr(self, "_mcp_shell_guard_bin", None)
        if guard_bin is not None:
            guard_path = (
                str(guard_bin)
                if backend == "direct"
                else "/installed_agent/mcp-shell-guard-bin"
            )
            merged_env["PATH"] = os.pathsep.join(
                (guard_path, merged_env.get("PATH", ""))
            ).rstrip(os.pathsep)
        self.logger.debug("exec> %s (cwd=%s)", self._short(command), inner_cwd)

        process = await create_exec_subprocess(
            argv,
            backend=backend,
            env=merged_env,
        )
        self._active_exec_pids.add(process.pid)
        try:
            if done_marker:
                communicate = communicate_until_done_marker(process, done_marker)
            else:
                async def communicate_without_marker():
                    stdout, stderr = await process.communicate()
                    return stdout, stderr, process.returncode or 0

                communicate = communicate_without_marker()
            if timeout_sec:
                stdout_bytes, stderr_bytes, return_code = await asyncio.wait_for(
                    communicate, timeout=timeout_sec
                )
            else:
                stdout_bytes, stderr_bytes, return_code = await communicate
        except asyncio.TimeoutError:
            await self._terminate_process_group(process.pid)
            stdout_bytes, stderr_bytes = await process.communicate()
            return ExecResult(
                stdout=stdout_bytes.decode(errors="replace"),
                stderr=stderr_bytes.decode(errors="replace"),
                return_code=124,
            )
        except asyncio.CancelledError:
            await self._terminate_process_group(process.pid)
            raise
        finally:
            self._active_exec_pids.discard(process.pid)

        stdout = stdout_bytes.decode(errors="replace") if stdout_bytes else None
        stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else None
        return ExecResult(
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )
