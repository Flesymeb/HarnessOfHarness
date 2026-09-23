"""Compatibility namespace for the renamed GameCraft-Bench adapter.

New code must import :mod:`gameloop.adapters.gamecraft_bench`.  The namespace
is retained so existing legacy scripts and local test fixtures do not change
the benchmark execution semantics during the migration.
"""

from pathlib import Path

# Let legacy ``gameloop.adapters.gamecraft.<module>`` imports resolve to the
# canonical adapter directory without copying or maintaining two implementations.
__path__ = [
    str(Path(__file__).resolve().parent.parent / "gamecraft_bench")
]
