"""Runtime-owned launcher for the pinned Godot MCP server and editor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Sequence

from gameloop.core.execution import (
    terminate_process_group as _terminate_process_group,
    terminate_process_group_pid,
)
from gameloop.tools.godot_mcp_vendor import doctor as vendor_doctor


PLUGIN_PATH = "res://addons/godot_mcp/plugin.cfg"


class GodotMCPError(RuntimeError):
    pass


class GodotMCPShutdown(GodotMCPError):
    """Expected transport teardown requested by the MCP client/role runtime."""


def role_guidance(role: str, *, strict_coverage: bool = False) -> str:
    if role == "developer":
        coverage_note = (
            "This run explicitly enables strict receipt coverage, so missing required "
            "receipts reject the candidate."
            if strict_coverage
            else (
                "The Runtime audits missing receipts as process warnings; do not let "
                "receipt completeness displace product work."
            )
        )
        return (
            "## Godot MCP development loop\n\n"
            "The harness registers the complete candidate-bound development/runtime "
            "`godot_*` tool set. The open-world network `godot_docs` tool is omitted; "
            "use the Runtime-provided local `gameloop-godot-docs` index instead. "
            "Use it actively for concrete implementation decisions and regressions, not "
            "as a deliverable of its own. Normally use one baseline observation cycle "
            "and one retest after a meaningful edit, roughly 8-24 successful calls in "
            "total. Every additional cycle must correspond to a specific defect and "
            "code, scene, resource, or demo change. Stop probing once the defect is "
            "understood, and reserve most of the run for mechanics, content, visible "
            "art, and replay evidence. Avoid unchanged duplicate probes; use more than "
            "36 calls only for a bounded transport recovery. The Runtime owns the "
            "Godot editor/MCP lifecycle; never start another editor or MCP server from "
            "the shell. When MCP coverage is required, non-headless Godot shell launches "
            "are rejected; shell Godot remains available only for headless build/import "
            "checks. Use only the mounted local asset pool; inspect at most a few "
            "task-relevant packs instead of recursively enumerating the full library, "
            "and establish a runnable project before polishing asset selection.\n\n"
            "For a cold task, create `project.godot` before the first "
            "`godot_project(get_info)` call. The Runtime starts the editor only "
            "after that file exists. If a probe made before project creation says "
            "Not connected, that is expected startup state—not evidence that MCP is "
            "unavailable. Finish the minimal project, wait for Runtime startup, and "
            "retry `godot_project(get_info)` before using any shell-only fallback or "
            "making an availability claim.\n\n"
            "For each concrete defect, run a serial observe-change-retest loop:\n"
            "1. Confirm `godot_project(get_info)` resolves to the current candidate.\n"
            "2. Start fresh disk bytes with `godot_editor_edit(run)`, then inspect "
            "runtime/editor logs and `godot_runtime_state(digest)`.\n"
            "3. Exercise the relevant player path with `godot_input(sequence)` and/or "
            "deterministic `godot_game_time`; use runtime/node/UI/spatial probes for "
            "state and `godot_editor_read(screenshot_game)` for appearance.\n"
            "For point-and-click UI, read Control rectangles with "
            "`godot_node_read(inspect_ui)`, then send `mouse_position:[x,y]` and a "
            "positioned `mouse_button:left` entry through `godot_input(sequence)`; "
            "do not encode a mouse button as a keyboard key.\n"
            "4. Make one bounded code/scene/resource change. Stop and run again, then "
            "repeat the same state, log, input, and screenshot family so before/after "
            "evidence is comparable. Continue until the public acceptance condition "
            "passes or a concrete blocker is demonstrated.\n\n"
            "A successful tool transport is not product evidence. Inspect returned "
            "values and pixels. A screenshot alone does not prove mechanics; pair it "
            "with input and state. For transient feedback, capture a few useful "
            "`screenshot_at_ms` frames inside the same input sequence. Before finishing "
            "a game change, the Runtime requires `godot_project(get_info)`, a fresh "
            "run/stop lifecycle, runtime logs, `godot_runtime_state(digest)`, actual "
            "player inputs, and a screenshot in one coherent observation cycle. Warm-start iterations "
            "must produce two such cycles: one baseline before the main edit and one "
            "retest afterward. "
            + coverage_note
            + " Shell commands, headless launches, and pre-existing images do not "
            "count as MCP observations.\n\n"
            "Before your final response, briefly audit the current cycle by tool name. "
            "When the corresponding checks were needed, the useful receipt set is: "
            "`godot_project(get_info)`, "
            "`godot_editor_edit(run)`, runtime logs, `godot_runtime_state(digest)`, "
            "a non-empty `godot_input(sequence)` or input-bearing `godot_game_time`, "
            "a fresh MCP screenshot, and `godot_editor_edit(stop)`. `godot_exec` state "
            "helpers do not replace the required digest or player-input receipts. If "
            "anything important is missing and product work is complete, perform at "
            "most one short coherent closeout cycle before answering.\n"
        )
    if role == "tester":
        return (
            "## Godot MCP runtime QA\n\n"
            "Actively play and inspect the isolated candidate copy with the registered "
            "Tester-safe Godot MCP profile. It permits run/stop, read-only editor and "
            "runtime observation, bounded player input, deterministic game time, and "
            "screenshots; source/resource mutation actions are unavailable. Use multiple "
            "state-specific calls whenever they test different requirements, but keep "
            "the session goal-directed: prefer aggregate state/watch results over "
            "enumerating every live node, and normally cover the acceptance surface in "
            "2-5 representative checkpoints using roughly 12-30 successful MCP calls. "
            "After roughly 24 calls, reserve the remaining budget for the final log, "
            "digest, screenshot, and stop receipts. Past 27 calls, make only those "
            "missing closeout calls; do not open a new investigation branch. Never "
            "inspect properties on more than four individual nodes in one QA pass; "
            "prefer aggregate find, UI, state, or watch results. Once 30 calls are "
            "reached, stop probing and write the verdict unless one "
            "failed required transport call needs a bounded recovery. Do not repeat an unchanged view or grind "
            "ordinary play waiting for an unproven state; record the evidence gap and "
            "move on once a bounded attempt has failed.\n\n"
            "Independently establish a fresh session with `godot_project(get_info)` and "
            "`godot_editor_edit(run)`. Read runtime logs and a runtime-state digest before "
            "input. Then exercise the public core loop using `godot_input(sequence)` and "
            "`godot_game_time`, inspect the resulting node/UI/runtime state, and capture "
            "fresh game screenshots. Test applicable start, ordinary-play, pressure or "
            "failure, progress, and result/retry states rather than trusting Developer "
            "claims or only reviewing existing replay media. Pair screenshots with the "
            "input and state that produced them; use in-sequence screenshots for transient "
            "feedback.\n\n"
            "For point-and-click paths, use `godot_node_read(inspect_ui)` to obtain "
            "Control rectangles, then drive `mouse_position:[x,y]` plus a positioned "
            "`mouse_button:left` entry in `godot_input(sequence)`. Never pass names such "
            "as `MouseButtonLeft` through the raw-key field. Absolute pointer events "
            "drive Godot's event path but do not claim to move the physical OS cursor.\n\n"
            "The Runtime requires `godot_project(get_info)` plus one coherent fresh-run "
            "observation containing runtime logs, `godot_runtime_state(digest)`, actual player "
            "input, and a fresh screenshot before accepting MCP QA coverage. Shell commands and "
            "pre-existing images do not satisfy this gate. If a tool reports a readiness "
            "error, inspect the causal log, perform one bounded recovery, and report the "
            "blocker instead of spinning on unchanged calls. Stop the run explicitly when "
            "the call budget permits; Runtime-owned teardown remains the safe close if the "
            "read-only Tester has already completed every observation category. Cite the "
            "fresh MCP evidence in the playtest report.\n"
        )
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] in {"doctor", "--doctor"}:
        return _doctor()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("serve",), default="serve")
    parser.add_argument("--read-only-runtime", action="store_true")
    parser.add_argument("--project")
    args = parser.parse_args(raw)
    try:
        return _serve(
            project=_find_project(args.project, required=False),
            project_hint=args.project,
            runtime_qa=args.read_only_runtime,
        )
    except GodotMCPShutdown:
        # Codex closes its stdio MCP child with SIGTERM at the end of a normal
        # role. _serve() has already emitted the final stopped receipt.
        return 0
    except GodotMCPError as error:
        _write_lifecycle_receipt("blocked", error=str(error))
        print(f"gameloop-godot-mcp: {error}", file=sys.stderr)
        return 3


def _doctor() -> int:
    payload = doctor_payload()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ready" else 3


def doctor_payload() -> dict[str, Any]:
    payload = vendor_doctor()
    payload = {
        **payload,
        "launcher": "gameloop-godot-mcp",
        "godot": _find_godot_binary(required=False),
        "xvfb_run": shutil.which("xvfb-run"),
    }
    if not payload["godot"]:
        payload["status"] = "blocked"
    return payload


def _serve(
    *,
    project: Path | None,
    project_hint: str | None,
    runtime_qa: bool,
) -> int:
    vendor = vendor_doctor()
    if vendor["status"] != "ready":
        raise GodotMCPError(
            "pinned server is not prepared; run `gameloop-godot-mcp-vendor prepare`"
        )
    checkout = Path(str(vendor["checkout"]))
    cli = checkout / "server" / "dist" / "cli.js"
    node = shutil.which("node")
    if node is None:
        raise GodotMCPError("Node.js 20+ is required")
    godot = _find_godot_binary(required=True)

    addon_dir: Path | None = None
    addon_existed = False
    project_file: Path | None = None
    before_text: str | None = None
    plugin_was_enabled = False
    editor: subprocess.Popen[bytes] | None = None
    server: subprocess.Popen[bytes] | None = None
    editor_log = None
    port = _allocate_port()
    expected_project = project or _preferred_project_path(project_hint)
    child_env = _server_environment(port=port, expected_project=expected_project)
    mode = "runtime-qa" if runtime_qa else "developer"

    previous_handlers = _install_shutdown_handlers()
    try:
        # Connect stdio before waiting for a cold-start candidate to create
        # project.godot. Codex discovers the complete tool surface immediately;
        # the vendored server reconnects to Godot in the background once the
        # Runtime has installed the addon and launched the editor.
        server_command = [node, str(cli)]
        if runtime_qa:
            server_command.append("--read-only-runtime")
        server = subprocess.Popen(
            server_command,
            env=child_env,
            start_new_session=True,
        )
        if project is None:
            _write_lifecycle_receipt(
                "waiting_for_project",
                project=str(expected_project),
                port=port,
                mode=mode,
                server_pid=server.pid,
            )
            project = _wait_for_project(project_hint, server)

        addon_dir = project / "addons" / "godot_mcp"
        addon_existed = addon_dir.is_dir()
        project_file = project / "project.godot"
        before_text = project_file.read_text(encoding="utf-8")
        plugin_was_enabled = PLUGIN_PATH in before_text
        install = subprocess.run(
            [node, str(cli), "--install-addon", str(project), "--force"],
            env=child_env,
            text=True,
            capture_output=True,
            check=False,
        )
        if install.returncode != 0:
            raise GodotMCPError(
                "addon installation failed: "
                + (install.stderr.strip() or install.stdout.strip())
            )
        enabled_text, _ = enable_plugin_config_text(
            project_file.read_text(encoding="utf-8")
        )
        project_file.write_text(enabled_text, encoding="utf-8")

        editor_command = _editor_command(godot, project)
        editor_log_path = _editor_log_path()
        editor_log = editor_log_path.open("ab") if editor_log_path else None
        for startup_attempt in range(1, 3):
            log_offset = _log_size(editor_log_path)
            editor = subprocess.Popen(
                editor_command,
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=editor_log or subprocess.DEVNULL,
                stderr=subprocess.STDOUT if editor_log else subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                _wait_for_port(
                    editor,
                    port,
                    log_path=editor_log_path,
                    log_offset=log_offset,
                )
                break
            except GodotMCPError:
                _terminate_process_group(editor)
                editor = None
                if startup_attempt >= 2:
                    raise
                time.sleep(1.0)
        _write_lifecycle_receipt(
            "running",
            project=str(project),
            port=port,
            mode=mode,
            editor_pid=editor.pid,
            startup_attempt=startup_attempt,
            restart_count=0,
            server_pid=server.pid,
        )
        restart_count = 0
        while server.poll() is None:
            if editor.poll() is None:
                time.sleep(0.25)
                continue
            restart_count += 1
            if restart_count > 2:
                raise GodotMCPError(
                    "Godot editor repeatedly exited while MCP was active: "
                    + _log_tail(editor_log_path).strip()
                )
            _write_lifecycle_receipt(
                "recovering",
                project=str(project),
                port=port,
                mode=mode,
                failed_editor_pid=editor.pid,
                restart_count=restart_count,
                server_pid=server.pid,
            )
            time.sleep(0.5)
            log_offset = _log_size(editor_log_path)
            editor = subprocess.Popen(
                editor_command,
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=editor_log or subprocess.DEVNULL,
                stderr=subprocess.STDOUT if editor_log else subprocess.DEVNULL,
                start_new_session=True,
            )
            _wait_for_port(
                editor,
                port,
                log_path=editor_log_path,
                log_offset=log_offset,
            )
            _write_lifecycle_receipt(
                "running",
                project=str(project),
                port=port,
                mode=mode,
                editor_pid=editor.pid,
                restart_count=restart_count,
                server_pid=server.pid,
            )
        return int(server.returncode or 0)
    finally:
        _restore_signal_handlers(previous_handlers)
        if server is not None:
            _terminate_process_group(server)
        if editor is not None:
            _terminate_process_group(editor)
        if editor_log is not None:
            editor_log.close()
        if (
            project_file is not None
            and project_file.is_file()
            and before_text is not None
        ):
            if runtime_qa:
                # Tester owns no candidate source. Restore the exact bytes that
                # preceded addon/editor startup, including original formatting.
                project_file.write_text(before_text, encoding="utf-8")
            elif not plugin_was_enabled or not addon_existed:
                current = project_file.read_text(encoding="utf-8", errors="ignore")
                project_file.write_text(
                    remove_mcp_project_config(current),
                    encoding="utf-8",
                )
        if addon_dir is not None and not addon_existed and addon_dir.exists():
            shutil.rmtree(addon_dir)
            addons_root = addon_dir.parent
            try:
                addons_root.rmdir()
            except OSError:
                pass
        if project is not None:
            _write_lifecycle_receipt(
                "stopped",
                project=str(project),
                port=port,
                mode=mode,
            )


def _server_environment(*, port: int, expected_project: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["GODOT_PORT"] = str(port)
    environment["GODOT_MCP_EXPECTED_PROJECT"] = str(expected_project)
    environment.setdefault(
        "GODOT_MCP_STARTUP_WAIT_MS",
        str(int(_startup_timeout_seconds() * 1000)),
    )
    environment.setdefault("GODOT_MCP_USAGE_LOG", "0")
    environment.setdefault("GAMELOOP_GODOT_MCP_OFFLINE_ONLY", "1")
    # Godot's built-in restart escapes xvfb-run; this launcher respawns the
    # editor with a fresh X display after the supervised process exits.
    environment["GAMELOOP_GODOT_MCP_SUPERVISED_EDITOR"] = "1"
    return environment


def _project_candidates(explicit: str | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("GAMELOOP_GODOT_PROJECT"):
        candidates.append(Path(os.environ["GAMELOOP_GODOT_PROJECT"]))
    cwd = Path.cwd()
    candidates.extend(
        (
            cwd,
            cwd / "game",
            cwd / "workspace" / "game",
            cwd / "sandbox" / "workspace" / "game",
        )
    )
    return candidates


def _preferred_project_path(explicit: str | None) -> Path:
    candidates = _project_candidates(explicit)
    if explicit or os.environ.get("GAMELOOP_GODOT_PROJECT"):
        return candidates[0].expanduser().resolve(strict=False)
    return (Path.cwd() / "game").resolve(strict=False)


def _find_project(explicit: str | None, *, required: bool = True) -> Path | None:
    candidates = _project_candidates(explicit)
    for candidate in candidates:
        resolved = candidate.expanduser().resolve(strict=False)
        if (resolved / "project.godot").is_file():
            return resolved
    if not required:
        return None
    raise GodotMCPError(
        "could not locate project.godot in the role workspace; set GAMELOOP_GODOT_PROJECT"
    )


def _wait_for_project(
    explicit: str | None,
    server: subprocess.Popen[bytes],
) -> Path:
    timeout = _project_wait_timeout_seconds()
    deadline = None if timeout is None else time.monotonic() + timeout
    while deadline is None or time.monotonic() < deadline:
        project = _find_project(explicit, required=False)
        if project is not None:
            return project
        return_code = server.poll()
        if return_code is not None:
            raise GodotMCPError(
                "MCP transport exited before project.godot was created "
                f"(return code {return_code})"
            )
        time.sleep(0.25)
    assert timeout is not None
    raise GodotMCPError(
        f"project.godot was not created within {timeout:g} seconds; "
        "the MCP transport stayed available but the Godot editor could not start"
    )


def _project_wait_timeout_seconds() -> float | None:
    raw = os.environ.get("GAMELOOP_GODOT_PROJECT_WAIT_SECONDS", "0")
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return min(1800.0, max(5.0, value))


def _find_godot_binary(*, required: bool) -> str | None:
    configured = os.environ.get("GAMELOOP_GODOT_EDITOR_BIN") or os.environ.get(
        "GODOT_BIN"
    )
    candidates = [configured] if configured else []
    candidates.extend(("godot4.7", "godot4", "godot"))
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        found = shutil.which(candidate)
        if found:
            return found
    if required:
        raise GodotMCPError(
            "native Godot executable is unavailable; set GAMELOOP_GODOT_EDITOR_BIN"
        )
    return None


def _editor_command(godot: str, project: Path) -> list[str]:
    command = [
        godot,
        "--editor",
        "--path",
        str(project),
        "--rendering-method",
        "gl_compatibility",
        "--rendering-driver",
        "opengl3",
    ]
    if not os.environ.get("DISPLAY"):
        xvfb = shutil.which("xvfb-run")
        if xvfb is None:
            raise GodotMCPError("DISPLAY is unset and xvfb-run is unavailable")
        command = [xvfb, "-a", "-s", "-screen 0 1280x720x24", *command]
    return [*_cpu_affinity_prefix(project), *command]


def _cpu_affinity_prefix(project: Path) -> list[str]:
    """Bound long-lived software-rendered MCP runtimes on Linux hosts."""

    raw_limit = os.environ.get("GAMELOOP_GODOT_MAX_CPUS", "4").strip()
    try:
        limit = int(raw_limit)
    except ValueError as error:
        raise GodotMCPError(
            "GAMELOOP_GODOT_MAX_CPUS must be a non-negative integer"
        ) from error
    if limit < 0:
        raise GodotMCPError(
            "GAMELOOP_GODOT_MAX_CPUS must be a non-negative integer"
        )
    cpu_count = os.cpu_count() or 1
    taskset = shutil.which("taskset")
    if limit == 0 or limit >= cpu_count or taskset is None:
        return []

    identity = str(project.expanduser().resolve(strict=False)).encode("utf-8")
    start = int(hashlib.sha256(identity).hexdigest()[:8], 16) % cpu_count
    cpus = [(start + offset) % cpu_count for offset in range(limit)]
    return [taskset, "-c", ",".join(str(cpu) for cpu in cpus)]


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_port(
    editor: subprocess.Popen[bytes],
    port: int,
    *,
    log_path: Path | None = None,
    log_offset: int = 0,
) -> None:
    deadline = time.monotonic() + _startup_timeout_seconds()
    while time.monotonic() < deadline:
        if editor.poll() is not None:
            detail = _log_tail(log_path)
            raise GodotMCPError(
                f"Godot editor exited before MCP port {port} opened: {detail.strip()}"
            )
        # Do not connect to the port as a readiness probe. The Godot addon
        # treats every accepted TCP peer as an in-progress WebSocket. A probe
        # that disconnects before the handshake can crash some Godot builds and
        # can also occupy the addon's single-client slot. Prefer the addon's own
        # post-listen log marker. The bind fallback is only for direct launcher
        # use without an evidence log.
        if log_path is not None:
            marker = f"Server listening on 127.0.0.1:{port}"
            if marker in _log_from(log_path, offset=log_offset):
                return
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError:
                    return
        time.sleep(0.25)
    raise GodotMCPError(
        f"Godot editor did not open MCP port {port} within "
        f"{_startup_timeout_seconds():g} seconds: {_log_tail(log_path).strip()}"
    )


def _startup_timeout_seconds() -> float:
    raw = os.environ.get("GAMELOOP_GODOT_MCP_STARTUP_TIMEOUT_SECONDS", "45")
    try:
        return min(180.0, max(5.0, float(raw)))
    except ValueError:
        return 45.0


def _editor_log_path() -> Path | None:
    raw_root = os.environ.get("GAMELOOP_MCP_EVIDENCE_DIR")
    if not raw_root:
        return None
    root = Path(raw_root).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return root / "editor.stderr.log"


def _log_tail(path: Path | None, *, limit: int = 4_000) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read(limit).decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _log_size(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _log_from(path: Path, *, offset: int) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, offset))
            return handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _install_shutdown_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def handle(signum: int, _frame: Any) -> None:
        raise GodotMCPShutdown(f"launcher received signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, handle)
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def enable_plugin_config_text(text: str) -> tuple[str, bool]:
    section = re.search(r"(?ms)^\[editor_plugins\]\n(?P<body>.*?)(?=^\[|\Z)", text)
    if section is None:
        return (
            text.rstrip()
            + f'\n\n[editor_plugins]\n\nenabled=PackedStringArray("{PLUGIN_PATH}")\n',
            True,
        )
    enabled = re.search(
        r"(?m)^enabled=PackedStringArray\((?P<items>.*)\)$",
        section.group("body"),
    )
    if enabled is None:
        position = section.end("body")
        return (
            text[:position]
            + f'enabled=PackedStringArray("{PLUGIN_PATH}")\n'
            + text[position:],
            True,
        )
    items = re.findall(r'"([^"]+)"', enabled.group("items"))
    if PLUGIN_PATH in items:
        return text, False
    items.append(PLUGIN_PATH)
    replacement = "enabled=PackedStringArray(%s)" % ", ".join(
        json.dumps(item) for item in items
    )
    start = section.start("body") + enabled.start()
    end = section.start("body") + enabled.end()
    return text[:start] + replacement + text[end:], True


def remove_plugin_config_text(text: str) -> str:
    section = re.search(r"(?ms)^\[editor_plugins\]\n(?P<body>.*?)(?=^\[|\Z)", text)
    if section is None:
        return text
    enabled = re.search(
        r"(?m)^enabled=PackedStringArray\((?P<items>.*)\)$",
        section.group("body"),
    )
    if enabled is None:
        return text
    items = [
        item
        for item in re.findall(r'"([^"]+)"', enabled.group("items"))
        if item != PLUGIN_PATH
    ]
    replacement = "enabled=PackedStringArray(%s)" % ", ".join(
        json.dumps(item) for item in items
    )
    start = section.start("body") + enabled.start()
    end = section.start("body") + enabled.end()
    return text[:start] + replacement + text[end:]


def remove_mcp_project_config(text: str) -> str:
    """Remove only Runtime-owned addon settings from a Developer candidate."""

    cleaned = remove_plugin_config_text(text)
    cleaned = re.sub(
        r'(?m)^MCPGameBridge="res://addons/godot_mcp/game_bridge/mcp_game_bridge\.gd"\n?',
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?ms)^\[godot_mcp\]\n.*?(?=^\[|\Z)",
        "",
        cleaned,
    )
    return cleaned


def _write_lifecycle_receipt(status: str, **details: Any) -> None:
    raw_root = os.environ.get("GAMELOOP_MCP_EVIDENCE_DIR")
    if not raw_root:
        return
    root = Path(raw_root).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "lifecycle.json"
    payload = {
        "schema_version": 1,
        "tool": "gameloop-godot-mcp",
        "status": status,
        "timestamp": time.time(),
        **details,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def cleanup_lifecycle_processes(evidence_dir: Path) -> dict[str, Any]:
    """Reap only MCP process groups bound to an exact Runtime evidence receipt."""

    root = evidence_dir.expanduser().resolve(strict=False)
    path = root / "lifecycle.json"
    result: dict[str, Any] = {
        "status": "not_found",
        "evidence_dir": str(root),
        "processes": [],
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return result
    except (OSError, json.JSONDecodeError) as error:
        result.update(status="invalid_receipt", error=str(error))
        return result
    if not isinstance(payload, dict):
        result.update(status="invalid_receipt", error="lifecycle receipt is not an object")
        return result

    blocked = False
    stopped_any = False
    process_results: list[dict[str, Any]] = []
    lifecycle_groups: set[int] = set()
    for role in ("server", "editor"):
        raw_pid = payload.get(f"{role}_pid")
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            continue
        process_result: dict[str, Any] = {"role": role, "pid": pid}
        if pid <= 1 or not Path(f"/proc/{pid}").exists():
            process_result["status"] = "not_running"
            process_results.append(process_result)
            continue
        recorded_root = _process_evidence_root(pid)
        if recorded_root != root:
            blocked = True
            process_result.update(
                status="identity_mismatch",
                observed_evidence_dir=(
                    None if recorded_root is None else str(recorded_root)
                ),
            )
            process_results.append(process_result)
            continue
        try:
            process_group = os.getpgid(pid)
        except ProcessLookupError:
            process_result["status"] = "not_running"
            process_results.append(process_result)
            continue
        if process_group != pid:
            blocked = True
            process_result.update(
                status="not_process_group_leader",
                observed_process_group=process_group,
            )
            process_results.append(process_result)
            continue
        lifecycle_groups.add(process_group)
        stopped = terminate_process_group_pid(pid)
        stopped_any = stopped_any or stopped
        process_result["status"] = "terminated" if stopped else "not_running"
        process_results.append(process_result)

    raw_project = payload.get("project")
    if not blocked and isinstance(raw_project, str) and raw_project.strip():
        project = Path(raw_project).expanduser()
        if project.is_absolute():
            project = project.resolve(strict=False)
            for pid, process_group in _project_bound_godot_process_groups(
                root, project
            ):
                if process_group in lifecycle_groups:
                    continue
                process_result = {
                    "role": "candidate_godot",
                    "pid": pid,
                    "process_group": process_group,
                    "project": str(project),
                }
                stopped = terminate_process_group_pid(process_group)
                stopped_any = stopped_any or stopped
                process_result["status"] = (
                    "terminated" if stopped else "not_running"
                )
                process_results.append(process_result)

    result["processes"] = process_results
    if blocked:
        result["status"] = "cleanup_blocked"
    elif stopped_any:
        result["status"] = "stopped"
    else:
        result["status"] = "already_stopped"

    updated = dict(payload)
    updated["timestamp"] = time.time()
    updated["runtime_cleanup"] = result
    if not blocked:
        updated["status"] = "stopped"
        updated["shutdown_reason"] = "runtime_post_role_cleanup"
        updated.pop("server_pid", None)
        updated.pop("editor_pid", None)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)
    except OSError as error:
        result["receipt_update_error"] = str(error)
        try:
            temporary.unlink()
        except OSError:
            pass
    return result


def _process_evidence_root(pid: int) -> Path | None:
    """Read the immutable-at-exec evidence binding of a live Linux process."""

    try:
        environ = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    prefix = b"GAMELOOP_MCP_EVIDENCE_DIR="
    for entry in environ.split(b"\0"):
        if entry.startswith(prefix):
            try:
                value = entry[len(prefix) :].decode("utf-8")
            except UnicodeDecodeError:
                return None
            return Path(value).expanduser().resolve(strict=False)
    return None


def _godot_argv_targets_project(argv: Sequence[str], project: Path) -> bool:
    """Return whether a native Godot argv is bound to one exact project path."""

    if not argv or "godot" not in Path(argv[0]).name.casefold():
        return False
    raw_path: str | None = None
    for index, argument in enumerate(argv):
        if argument == "--path" and index + 1 < len(argv):
            raw_path = argv[index + 1]
            break
        if argument.startswith("--path="):
            raw_path = argument.partition("=")[2]
            break
    if not raw_path:
        return False
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        return False
    return candidate.resolve(strict=False) == project.resolve(strict=False)


def _project_bound_godot_process_groups(
    evidence_root: Path, project: Path
) -> list[tuple[int, int]]:
    """Find independently grouped Godot processes with two exact bindings.

    A launched game can reparent itself and create a process group separate from
    the editor.  Requiring both the immutable evidence-root environment and the
    exact ``--path`` argument prevents cleanup from touching an unrelated Godot
    project on the same host.
    """

    proc = Path("/proc")
    if not proc.is_dir():
        return []
    root = evidence_root.expanduser().resolve(strict=False)
    target = project.expanduser().resolve(strict=False)
    groups: dict[int, int] = {}
    try:
        entries = list(proc.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        pid = int(entry.name)
        if pid <= 1 or _process_evidence_root(pid) != root:
            continue
        try:
            raw_argv = (entry / "cmdline").read_bytes().split(b"\0")
            argv = [os.fsdecode(item) for item in raw_argv if item]
        except OSError:
            continue
        if not _godot_argv_targets_project(argv, target):
            continue
        try:
            process_group = os.getpgid(pid)
        except ProcessLookupError:
            continue
        if process_group > 1:
            groups.setdefault(process_group, pid)
    return [(pid, process_group) for process_group, pid in sorted(groups.items())]


if __name__ == "__main__":
    raise SystemExit(main())
