"""Preflight configured harness/model profiles without printing secrets."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from gameloop.env import load_runtime_env, project_env_defaults
from gameloop.harnesses.deepseek import (
    MINIMAL_CORDIS_SHA256,
    MINIMAL_PRESET_SHA256,
    validate_minimal_bundle,
)


EXPECTED = {
    "codex": ("codex", None, "gpt-5.5"),
    "opencode": ("opencode", "1.14.30", "deepseek-v4-pro"),
    "pi": ("pi", "0.80.10", "minimax-m3"),
}


def _cli_check(harness: str, env: dict[str, str]) -> dict[str, Any]:
    executable_name, expected, model = EXPECTED[harness]
    executable = shutil.which(executable_name, path=env.get("PATH"))
    if not executable:
        return {
            "ready": False,
            "model": model,
            "expected_version": expected,
            "error": f"{executable_name} is not installed on PATH",
        }
    completed = subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    output = (completed.stdout or completed.stderr).strip()
    version_ready = completed.returncode == 0 and (
        expected is None or expected in output
    )
    credential_errors: list[str] = []
    credentials: dict[str, str] = {}
    if harness == "opencode":
        for name in ("BAILIAN_API_KEY", "BAILIAN_BASE_URL"):
            present = bool(env.get(name, "").strip())
            credentials[name] = "set" if present else "missing"
            if not present:
                credential_errors.append(f"{name} is missing")
    elif harness == "pi":
        key_file_value = env.get("PJLAB_API_KEY_FILE", "").strip()
        key_file = Path(key_file_value).expanduser() if key_file_value else None
        has_key = bool(env.get("PJLAB_API_KEY", "").strip()) or bool(
            key_file and key_file.is_file() and key_file.stat().st_size
        )
        credentials["PJLAB_API_KEY"] = "set" if has_key else "missing"
        credentials["PJLAB_BASE_URL"] = (
            "set" if env.get("PJLAB_BASE_URL", "").strip() else "default"
        )
        if not has_key:
            credential_errors.append(
                "PJLAB_API_KEY or a non-empty PJLAB_API_KEY_FILE is required"
            )
    ready = version_ready and not credential_errors
    return {
        "ready": ready,
        "model": model,
        "expected_version": expected or "latest installed",
        "observed_version": output,
        "executable": str(Path(executable).resolve()),
        "credentials": credentials,
        "error": (
            None
            if ready
            else (
                "; ".join(credential_errors)
                if version_ready
                else (
                    "CLI version command failed"
                    if expected is None
                    else "CLI version does not match the configured pin"
                )
            )
        ),
    }


def _dsh_check(env: dict[str, str]) -> dict[str, Any]:
    package_versions: dict[str, str] = {}
    errors: list[str] = []
    for package in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin"):
        try:
            package_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            package_versions[package] = "missing"
        if package_versions[package] != "0.1.0rc6":
            errors.append(f"{package} must be 0.1.0rc6")
    key_file_value = env.get("DEEPSEEK_API_KEY_FILE", "").strip()
    key_file = Path(key_file_value).expanduser() if key_file_value else None
    has_key = bool(env.get("DEEPSEEK_API_KEY", "").strip()) or bool(
        key_file and key_file.is_file() and key_file.stat().st_size
    )
    if not has_key:
        errors.append("DEEPSEEK_API_KEY or DEEPSEEK_API_KEY_FILE is missing")
    if not env.get("DEEPSEEK_BASE_URL"):
        errors.append("DEEPSEEK_BASE_URL is missing")
    try:
        bundle = validate_minimal_bundle()
    except RuntimeError as error:
        errors.append(str(error))
        runtime_command = None
    else:
        runtime_command = [str(path) for path in bundle.runtime_command]
    danger_allowed = env.get("GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS") == "1"
    if not danger_allowed:
        errors.append(
            "GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS=1 is required for the official "
            "standalone minimal composition"
        )
    return {
        "ready": not errors,
        "model": "deepseek-v4-flash",
        "preset": "minimal",
        "expected_version": "0.1.0rc6",
        "package_versions": package_versions,
        "runtime_command": runtime_command,
        "minimal_cordis_sha256": MINIMAL_CORDIS_SHA256,
        "minimal_preset_sha256": MINIMAL_PRESET_SHA256,
        "sandbox_policy": "danger-full-access",
        "danger_full_access_acknowledged": danger_allowed,
        "credentials": {
            "DEEPSEEK_API_KEY": "set" if has_key else "missing",
            "DEEPSEEK_BASE_URL": "set" if env.get("DEEPSEEK_BASE_URL") else "missing",
        },
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harness",
        choices=["all", "codex", "opencode", "pi", "deepseek-harness"],
        default="all",
    )
    args = parser.parse_args(argv)
    selected = (
        ("codex", "opencode", "pi", "deepseek-harness")
        if args.harness == "all"
        else (args.harness,)
    )
    project_root = Path.cwd()
    defaults = project_env_defaults(project_root)
    bench_value = defaults.get("GAMELOOP_BENCH", "").strip()
    bench = Path(bench_value).expanduser().resolve() if bench_value else None
    env = load_runtime_env(project_root=project_root, bench=bench)
    payload = {
        harness: (
            _dsh_check(env)
            if harness == "deepseek-harness"
            else _cli_check(harness, env)
        )
        for harness in selected
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0 if all(item["ready"] for item in payload.values()) else 1)


if __name__ == "__main__":
    main()
