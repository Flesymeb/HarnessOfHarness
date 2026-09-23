"""Subprocess execution helpers for GameLoop runtimes."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time


@dataclass(frozen=True)
class CommandRunResult:
    returncode: int
    timed_out: bool
    idle_timed_out: bool
    wall_timed_out: bool


@dataclass(frozen=True)
class CapturedCommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def terminate_process_group_pid(pid: int, *, grace_seconds: float = 2.0) -> bool:
    """Stop an independently recorded process group without requiring its leader."""

    if pid <= 1:
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return True


def terminate_process_group(
    process: subprocess.Popen, *, grace_seconds: float = 2.0
) -> None:
    """Stop a role command and every child it launched."""

    terminate_process_group_pid(process.pid, grace_seconds=grace_seconds)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_captured_command(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    timeout_seconds: float | None,
    input_text: str | None = None,
) -> CapturedCommandResult:
    """Capture a command while guaranteeing timeout cleanup of descendants."""

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            input=input_text,
            timeout=timeout_seconds,
        )
        return CapturedCommandResult(
            returncode=process.returncode or 0,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        terminate_process_group(process)
        stdout, stderr = process.communicate()
        return CapturedCommandResult(
            returncode=124,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=True,
        )


def run_command_with_idle_timeout(
    cmd: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    wall_timeout_seconds: float | None,
    idle_timeout_seconds: float,
    env: dict[str, str] | None = None,
    stdin_path: Path | None = None,
) -> CommandRunResult:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    stdin_handle = stdin_path.open("rb") if stdin_path else None
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=stdin_handle,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("subprocess pipes were not created")

    selector = selectors.DefaultSelector()
    for stream, path in ((process.stdout, stdout_path), (process.stderr, stderr_path)):
        os.set_blocking(stream.fileno(), False)
        handle = path.open("wb")
        selector.register(stream, selectors.EVENT_READ, data=handle)

    start = time.monotonic()
    last_activity = start
    timed_out = False
    idle_timed_out = False
    wall_timed_out = False

    def terminate(reason: str) -> None:
        nonlocal timed_out, idle_timed_out, wall_timed_out
        timed_out = True
        if reason == "idle":
            idle_timed_out = True
            message = (
                f"\n[gameloop] idle timeout after {idle_timeout_seconds} seconds "
                "without stdout/stderr activity.\n"
            )
        else:
            wall_timed_out = True
            message = f"\n[gameloop] wall timeout after {wall_timeout_seconds} seconds.\n"
        with stderr_path.open("ab") as stderr_file:
            stderr_file.write(message.encode("utf-8"))
        terminate_process_group(process)

    try:
        while selector.get_map():
            now = time.monotonic()
            if wall_timeout_seconds is not None and now - start >= wall_timeout_seconds:
                terminate("wall")
                break
            if now - last_activity >= idle_timeout_seconds:
                terminate("idle")
                break

            next_deadlines = [idle_timeout_seconds - (now - last_activity)]
            if wall_timeout_seconds is not None:
                next_deadlines.append(wall_timeout_seconds - (now - start))
            wait_time = max(0.01, min(0.1, *next_deadlines))

            events = selector.select(wait_time)
            if not events and process.poll() is not None:
                events = list(selector.select(0))
                if not events:
                    break

            for key, _ in events:
                stream = key.fileobj
                handle = key.data
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if chunk:
                    handle.write(chunk)
                    handle.flush()
                    last_activity = time.monotonic()
                else:
                    selector.unregister(stream)
                    handle.close()

        if timed_out:
            returncode = 124
        else:
            returncode = process.wait()
    finally:
        for key in list(selector.get_map().values()):
            try:
                selector.unregister(key.fileobj)
            except Exception:
                pass
            key.data.close()
        selector.close()
        if stdin_handle is not None:
            stdin_handle.close()

    return CommandRunResult(
        returncode=returncode,
        timed_out=timed_out,
        idle_timed_out=idle_timed_out,
        wall_timed_out=wall_timed_out,
    )
