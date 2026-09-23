"""Environment loading helpers for local GameLoop runs."""

from __future__ import annotations

import os
from pathlib import Path
import re


DOTENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def iter_dotenv(path: Path) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if not path.is_file():
        return items
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        items.append((key, value.strip().strip("'").strip('"')))
    return items


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in iter_dotenv(path):
        values[key] = expand_dotenv_value(value, values)
    return values


def expand_dotenv_value(value: str, env: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        fallback = match.group(2)
        current = env.get(key)
        if current:
            return current
        return fallback if fallback is not None else ""

    return DOTENV_REF_RE.sub(replace, value)


def apply_dotenv(
    path: Path,
    env: dict[str, str],
    *,
    override: bool,
    protected_keys: set[str],
) -> None:
    for key, value in iter_dotenv(path):
        if key in protected_keys:
            continue
        if override or key not in env:
            env[key] = expand_dotenv_value(value, env)


def project_env_defaults(project_root: Path) -> dict[str, str]:
    values = parse_dotenv(project_root / ".env")
    explicit = os.environ.copy()
    values.update(explicit)
    return values


def load_runtime_env(
    *,
    project_root: Path,
    bench: Path | None = None,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    protected = set(env)

    if bench is not None:
        apply_dotenv(bench / ".env", env, override=False, protected_keys=protected)

    # Project .env overrides bench defaults, but not variables explicitly
    # exported in the parent shell.
    apply_dotenv(project_root / ".env", env, override=True, protected_keys=protected)

    extra_env_file = env.get("GAMELOOP_ENV_FILE")
    if extra_env_file:
        apply_dotenv(
            Path(extra_env_file).expanduser().resolve(),
            env,
            override=True,
            protected_keys=protected,
        )
    return env
