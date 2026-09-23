#!/usr/bin/env python3
"""Run Pi through a local OpenAI request-normalization bridge."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

DEFAULT_UPSTREAM_INACTIVITY_TIMEOUT_SECONDS = 300.0


def pi_json_event_failed(line: bytes) -> bool:
    """Detect Pi's JSON-mode model failures even when its CLI exits zero."""

    try:
        event = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(event, dict):
        return False
    message = event.get("message")
    return bool(
        isinstance(message, dict)
        and message.get("role") == "assistant"
        and message.get("stopReason") == "error"
    )


def normalize_openai_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Split MiniMax reasoning from visible text for reliable multi-turn replay."""

    model = payload.get("model")
    if not isinstance(model, str) or model.rsplit("/", 1)[-1].lower() != "minimax-m3":
        return payload, False
    if "reasoning_split" in payload:
        return payload, False
    normalized = dict(payload)
    normalized["reasoning_split"] = True
    return normalized, True


def normalize_openai_error_body(status: int, body: bytes) -> tuple[bytes, bool]:
    """Preserve the HTTP status in 5xx messages so Pi retries them."""

    if not 500 <= status <= 599:
        return body, False
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body, False
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return body, False
    error = payload["error"]
    message = error.get("message")
    if not isinstance(message, str) or not message:
        return body, False
    normalized = dict(payload)
    normalized_error = dict(error)
    normalized_error["message"] = (
        f"HTTP {status} transient server error: {message}"
    )
    normalized["error"] = normalized_error
    return json.dumps(normalized, ensure_ascii=False).encode("utf-8"), True


def normalize_openai_sse_line(line: bytes) -> tuple[bytes, bool]:
    """Mark known streamed MiniMax backend failures as retryable."""

    if line.endswith(b"\r\n"):
        content, line_ending = line[:-2], b"\r\n"
    elif line.endswith(b"\n"):
        content, line_ending = line[:-1], b"\n"
    else:
        content, line_ending = line, b""
    if not content.startswith(b"data:"):
        return line, False
    payload_bytes = content[5:].lstrip()
    if not payload_bytes or payload_bytes == b"[DONE]":
        return line, False
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return line, False
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return line, False
    error = payload["error"]
    message = error.get("message")
    if not isinstance(message, str) or not message:
        return line, False
    error_identity = " ".join(
        str(error.get(name, "")) for name in ("code", "type", "message")
    ).lower()
    retryable_markers = (
        "enginecore",
        "engine_error",
        "backend_unavailable",
        "no healthy backend",
        "server_error",
        "internal_error",
        "upstream_error",
        "temporarily unavailable",
    )
    if not any(marker in error_identity for marker in retryable_markers):
        return line, False

    normalized = dict(payload)
    normalized_error = dict(error)
    normalized_error["message"] = f"HTTP 500 transient server error: {message}"
    normalized["error"] = normalized_error
    prefix_length = len(content) - len(payload_bytes)
    normalized_line = (
        content[:prefix_length]
        + json.dumps(normalized, ensure_ascii=False).encode("utf-8")
        + line_ending
    )
    return normalized_line, True


def build_upstream_url(upstream: str, request_path: str) -> str:
    """Join a gateway base URL and request path without duplicating ``/v1``."""

    base = upstream.rstrip("/")
    if base.endswith("/v1") and request_path.startswith("/v1/"):
        return base + request_path[3:]
    return base + "/" + request_path.lstrip("/")


def parse_upstream_inactivity_timeout(raw_value: str | None) -> float:
    """Return the maximum time an upstream socket may stay silent."""

    if raw_value is None or not raw_value.strip():
        return DEFAULT_UPSTREAM_INACTIVITY_TIMEOUT_SECONDS
    try:
        timeout = float(raw_value)
    except ValueError as error:
        raise ValueError(
            "GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS must be a number"
        ) from error
    if timeout <= 0:
        raise ValueError(
            "GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS must be positive"
        )
    return timeout


def build_proxy_map(proxy_url: str | None) -> dict[str, str]:
    """Build an explicit urllib proxy map without inheriting host settings."""

    if proxy_url is None or not proxy_url.strip():
        return {}
    proxy = proxy_url.strip()
    return {"http": proxy, "https": proxy}


def _handler(
    upstream: str,
    upstream_inactivity_timeout_seconds: float,
    proxy_url: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    opener = build_opener(ProxyHandler(build_proxy_map(proxy_url)))

    class OpenAIBridgeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            self._forward(None)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            request_path = self.path.split("?", 1)[0]
            if request_path in {"/chat/completions", "/v1/chat/completions"}:
                try:
                    payload = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, dict):
                    normalized, changed = normalize_openai_payload(payload)
                    if changed:
                        body = json.dumps(normalized, ensure_ascii=False).encode(
                            "utf-8"
                        )
            self._forward(body)

        def _forward(self, body: bytes | None) -> None:
            url = build_upstream_url(upstream, self.path)
            headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() not in HOP_BY_HOP_HEADERS
            }
            request = Request(url, data=body, headers=headers, method=self.command)
            try:
                # urllib applies this timeout to connect/read operations, not to
                # the total streamed response. Active long generations continue;
                # only a socket that emits no bytes for this period is abandoned.
                response = opener.open(
                    request,
                    timeout=upstream_inactivity_timeout_seconds,
                )
            except HTTPError as error:
                response = error
            except Exception as error:
                message = (
                    "OpenAI bridge upstream error: "
                    f"{type(error).__name__}: {error}"
                )
                encoded = message.encode("utf-8", errors="replace")
                self.send_response(HTTPStatus.BAD_GATEWAY)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                self.close_connection = True
                return

            with response:
                status = int(getattr(response, "status", response.code))
                content_type = response.headers.get("Content-Type", "").lower()
                error_body: bytes | None = None
                if 500 <= status <= 599:
                    raw_body = response.read()
                    error_body, _ = normalize_openai_error_body(status, raw_body)

                self.send_response(status)
                for name, value in response.headers.items():
                    if name.lower() not in HOP_BY_HOP_HEADERS:
                        self.send_header(name, value)
                if error_body is not None:
                    self.send_header("Content-Length", str(len(error_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if error_body is not None:
                    self.wfile.write(error_body)
                    self.wfile.flush()
                elif "text/event-stream" in content_type:
                    while line := response.readline():
                        normalized_line, _ = normalize_openai_sse_line(line)
                        self.wfile.write(normalized_line)
                        self.wfile.flush()
                else:
                    while chunk := response.read(65536):
                        self.wfile.write(chunk)
                        self.wfile.flush()
            self.close_connection = True

    return OpenAIBridgeHandler


def _set_pi_provider_base_url(
    config_path: Path,
    base_url: str,
    *,
    provider_id: str = "pjlab",
) -> str:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    provider = config["providers"][provider_id]
    original = provider["baseUrl"]
    provider["baseUrl"] = base_url
    config_path.write_text(
        json.dumps(config, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    return original


def _parent_death_signal() -> None:
    if not sys.platform.startswith("linux"):
        return
    import ctypes

    libc = ctypes.CDLL(None)
    libc.prctl(1, signal.SIGKILL)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command.pop(0)
    if not args.command:
        parser.error("a Pi command is required after --")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    provider_id = os.environ.get(
        "GAMELOOP_OPENAI_BRIDGE_PROVIDER",
        "pjlab",
    ).strip()
    if not provider_id:
        raise SystemExit("GAMELOOP_OPENAI_BRIDGE_PROVIDER must not be empty")
    upstream = (
        os.environ.get("GAMELOOP_OPENAI_BRIDGE_UPSTREAM")
        or os.environ.get("PJLAB_BASE_URL", "")
    ).rstrip("/")
    parsed = urlsplit(upstream)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(
            "GAMELOOP_OPENAI_BRIDGE_UPSTREAM must identify the upstream gateway"
        )
    proxy_url = os.environ.get("GAMELOOP_OPENAI_BRIDGE_PROXY")

    config_dir = os.environ.get("PI_CODING_AGENT_DIR", "")
    if not config_dir:
        raise SystemExit("PI_CODING_AGENT_DIR is required")
    config_path = Path(config_dir) / "models.json"
    if not config_path.is_file():
        raise SystemExit(f"Pi models config does not exist: {config_path}")

    try:
        upstream_inactivity_timeout_seconds = parse_upstream_inactivity_timeout(
            os.environ.get("GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS")
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _handler(upstream, upstream_inactivity_timeout_seconds, proxy_url),
    )
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    process: subprocess.Popen[bytes] | None = None
    original_base_url: str | None = None
    original_signal_handlers: dict[signal.Signals, Any] = {}
    try:
        server_thread.start()
        local_base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        original_base_url = _set_pi_provider_base_url(
            config_path,
            local_base_url,
            provider_id=provider_id,
        )

        env = os.environ.copy()
        for name in ("NO_PROXY", "no_proxy"):
            values = [value for value in env.get(name, "").split(",") if value]
            for value in ("127.0.0.1", "localhost"):
                if value not in values:
                    values.append(value)
            env[name] = ",".join(values)

        process = subprocess.Popen(
            args.command,
            env=env,
            stdout=subprocess.PIPE,
            preexec_fn=(
                _parent_death_signal if sys.platform.startswith("linux") else None
            ),
        )

        def terminate_child(signum: int, frame: Any) -> None:
            del signum, frame
            if process is not None and process.poll() is None:
                process.terminate()

        for watched_signal in (signal.SIGTERM, signal.SIGINT):
            original_signal_handlers[watched_signal] = signal.signal(
                watched_signal,
                terminate_child,
            )
        assert process.stdout is not None
        model_failed = False
        for line in iter(process.stdout.readline, b""):
            model_failed = pi_json_event_failed(line) or model_failed
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
        returncode = process.wait()
        return returncode or (1 if model_failed else 0)
    finally:
        for watched_signal, handler in original_signal_handlers.items():
            signal.signal(watched_signal, handler)
        try:
            if original_base_url is not None:
                _set_pi_provider_base_url(
                    config_path,
                    original_base_url,
                    provider_id=provider_id,
                )
        finally:
            if server_thread.is_alive():
                server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
