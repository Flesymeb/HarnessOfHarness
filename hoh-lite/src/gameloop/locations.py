"""Package and writable-workspace location discovery."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


PACKAGE_ROOT = Path(__file__).resolve().parent


def discover_project_root(
    *,
    package_root: Path = PACKAGE_ROOT,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Choose a writable runtime root without assuming an editable install."""

    env = os.environ if environment is None else environment
    configured = env.get("GAMELOOP_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    checkout = package_root.parent.parent
    if (
        (checkout / "pyproject.toml").is_file()
        and (checkout / "src" / "gameloop").is_dir()
    ):
        return checkout.resolve()
    return (cwd or Path.cwd()).expanduser().resolve()


PROJECT_ROOT = discover_project_root()
