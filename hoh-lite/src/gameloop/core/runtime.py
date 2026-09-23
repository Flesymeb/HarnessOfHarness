"""Deterministic host-side coordination for GameLoop roles.

The runtime is not an agent.  It owns sequencing and auditable receipts while
role implementations remain replaceable harness invocations.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
from pathlib import Path
import time
from typing import Any, Callable, Mapping, TypeVar

from gameloop.core.documents import write_json
from gameloop.core.roles import RoleBinding, RoleName


T = TypeVar("T")


@dataclass(frozen=True)
class RuntimeEvent:
    loop_index: int
    sequence: int
    role: RoleName
    status: str
    started_at: str
    duration_seconds: float
    details: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_index": self.loop_index,
            "sequence": self.sequence,
            "role": self.role.value,
            "status": self.status,
            "started_at": self.started_at,
            "duration_seconds": round(self.duration_seconds, 6),
            "details": dict(self.details),
        }


class GameLoopRuntime:
    """Coordinate role calls without performing product-development work."""

    def __init__(
        self,
        *,
        run_dir: Path,
        roles: Mapping[RoleName, RoleBinding],
    ) -> None:
        missing = set(RoleName) - set(roles)
        if missing:
            names = ", ".join(sorted(role.value for role in missing))
            raise ValueError(f"missing runtime role bindings: {names}")
        self.run_dir = run_dir.resolve()
        self.roles = dict(roles)
        self._events: list[RuntimeEvent] = []
        self._active_loop: int | None = None

    @property
    def receipt_path(self) -> Path:
        return self.run_dir / "runtime_receipt.json"

    def begin_loop(self, loop_index: int) -> None:
        if loop_index < 1:
            raise ValueError("loop_index must be >= 1")
        if self._active_loop is not None:
            raise RuntimeError(f"loop {self._active_loop} is still active")
        self._active_loop = loop_index
        self._write_receipt()

    def invoke(
        self,
        role: RoleName,
        operation: Callable[[], T],
        *,
        summarize: Callable[[T], Mapping[str, Any]] | None = None,
    ) -> T:
        if self._active_loop is None:
            raise RuntimeError("begin_loop must be called before invoking a role")
        self._validate_transition(role)
        started_wall = dt.datetime.now(dt.timezone.utc)
        started = time.monotonic()
        try:
            result = operation()
        except BaseException as error:
            self._append_event(
                role=role,
                status="failed",
                started_wall=started_wall,
                started=started,
                details={"error_type": type(error).__name__, "message": str(error)[:500]},
            )
            raise
        details = dict(summarize(result)) if summarize is not None else {}
        status = str(details.pop("status", "completed"))
        self._append_event(
            role=role,
            status=status,
            started_wall=started_wall,
            started=started,
            details=details,
        )
        return result

    def record_skipped_role(
        self,
        role: RoleName,
        *,
        status: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if self._active_loop is None:
            raise RuntimeError("begin_loop must be called before recording a role")
        self._validate_transition(role)
        now = dt.datetime.now(dt.timezone.utc)
        self._append_event(
            role=role,
            status=status,
            started_wall=now,
            started=time.monotonic(),
            details=details or {},
        )

    def finish_loop(self) -> None:
        if self._active_loop is None:
            raise RuntimeError("no active loop")
        current = self._loop_events(self._active_loop)
        if not any(event.role is RoleName.DEVELOPER for event in current):
            raise RuntimeError("a loop cannot finish before the Developer stage")
        self._active_loop = None
        self._write_receipt()

    def role_seen(self, loop_index: int, role: RoleName) -> bool:
        return any(event.role is role for event in self._loop_events(loop_index))

    def _validate_transition(self, role: RoleName) -> None:
        assert self._active_loop is not None
        current = self._loop_events(self._active_loop)
        if not current:
            if role is not RoleName.PLANNER:
                raise RuntimeError("the first role in a loop must be Planner")
            return
        previous = current[-1].role
        allowed = {
            RoleName.PLANNER: {RoleName.DEVELOPER},
            RoleName.DEVELOPER: {RoleName.TESTER},
            # repair-then-next alternates Tester and Developer; an acceptance
            # Tester may also be followed by the final next-loop Tester.
            RoleName.TESTER: {RoleName.DEVELOPER, RoleName.TESTER},
        }
        if role not in allowed[previous]:
            raise RuntimeError(
                f"invalid role transition in loop {self._active_loop}: "
                f"{previous.value} -> {role.value}"
            )

    def _loop_events(self, loop_index: int) -> list[RuntimeEvent]:
        return [event for event in self._events if event.loop_index == loop_index]

    def _append_event(
        self,
        *,
        role: RoleName,
        status: str,
        started_wall: dt.datetime,
        started: float,
        details: Mapping[str, Any],
    ) -> None:
        assert self._active_loop is not None
        event = RuntimeEvent(
            loop_index=self._active_loop,
            sequence=len(self._events) + 1,
            role=role,
            status=status,
            started_at=started_wall.isoformat(),
            duration_seconds=max(0.0, time.monotonic() - started),
            details=details,
        )
        self._events.append(event)
        self._write_receipt()

    def _write_receipt(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            self.receipt_path,
            {
                "schema_version": 1,
                "runtime": "gameloop-lite",
                "coordination": "deterministic-host",
                "active_loop": self._active_loop,
                "roles": {
                    role.value: self.roles[role].to_dict() for role in RoleName
                },
                "events": [event.to_dict() for event in self._events],
            },
        )
