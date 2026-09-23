"""Benchmark-neutral public CLI dispatcher.

The legacy GameCraft command is an adapter entry point, not the GameLoop Core
entry point.  Adding another benchmark only adds a registry adapter and its
own CLI; Core does not grow benchmark conditionals.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from gameloop.benchmarks.registry import default_benchmark_registry


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--benchmark", default="gamecraft-bench")
    parser.add_argument("--list-benchmarks", action="store_true")
    dispatch, remainder = parser.parse_known_args(raw)
    registry = default_benchmark_registry()
    if dispatch.list_benchmarks:
        print("\n".join(registry.ids()))
        return 0
    if dispatch.benchmark not in registry.ids():
        raise SystemExit(
            f"unknown benchmark {dispatch.benchmark!r}; available: "
            + ", ".join(registry.ids())
        )
    if dispatch.benchmark == "gamecraft-bench":
        from gameloop.adapters.gamecraft_bench.runner import main as gamecraft_main

        if not any(
            item == "--developer-backend"
            or item.startswith("--developer-backend=")
            for item in remainder
        ):
            remainder.extend(("--developer-backend", "harness"))
        return gamecraft_main(remainder)
    raise SystemExit(
        f"benchmark {dispatch.benchmark!r} is registered but has no CLI adapter"
    )


if __name__ == "__main__":
    raise SystemExit(main())
