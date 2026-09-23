"""Small explicit registry for public role harness adapters."""

from __future__ import annotations

from gameloop.harnesses.base import HarnessAdapter


class HarnessRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, HarnessAdapter] = {}

    def register(self, adapter: HarnessAdapter) -> None:
        harness_id = adapter.harness_id.strip()
        if not harness_id:
            raise ValueError("harness_id must not be empty")
        if harness_id in self._adapters:
            raise ValueError(f"harness already registered: {harness_id}")
        self._adapters[harness_id] = adapter

    def get(self, harness_id: str) -> HarnessAdapter:
        try:
            return self._adapters[harness_id]
        except KeyError as error:
            available = ", ".join(sorted(self._adapters)) or "none"
            raise ValueError(
                f"unknown harness {harness_id!r}; registered harnesses: {available}"
            ) from error

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def default_harness_registry() -> HarnessRegistry:
    from gameloop.harnesses.codex import CodexHarness
    from gameloop.harnesses.deepseek import DeepSeekHarnessAdapter
    from gameloop.harnesses.opencode import OpenCodeHarness
    from gameloop.harnesses.pi import PiHarness

    registry = HarnessRegistry()
    registry.register(CodexHarness())
    registry.register(DeepSeekHarnessAdapter())
    registry.register(OpenCodeHarness())
    registry.register(PiHarness())
    return registry
