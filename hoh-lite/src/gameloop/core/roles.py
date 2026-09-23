"""Role and capability contracts for the public GameLoop runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class RoleName(str, Enum):
    PLANNER = "planner"
    DEVELOPER = "developer"
    TESTER = "tester"


class WorkspaceAccess(str, Enum):
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"


class GodotMCPAccess(str, Enum):
    DISABLED = "disabled"
    READ_ONLY_RUNTIME = "read-only-runtime"
    READ_WRITE = "read-write"


@dataclass(frozen=True)
class RoleBinding:
    """Public, serializable binding between one role and one harness."""

    role: RoleName
    harness: str
    model: str
    reasoning_effort: str | None
    workspace_access: WorkspaceAccess
    godot_mcp: GodotMCPAccess
    godot_docs: bool = True

    def __post_init__(self) -> None:
        if not self.harness.strip():
            raise ValueError(f"{self.role.value} harness must not be empty")
        if not self.model.strip():
            raise ValueError(f"{self.role.value} model must not be empty")
        if self.role is not RoleName.DEVELOPER:
            if self.workspace_access is WorkspaceAccess.READ_WRITE:
                raise ValueError(
                    f"{self.role.value} cannot receive a read-write candidate workspace"
                )
            if self.godot_mcp is GodotMCPAccess.READ_WRITE:
                raise ValueError(
                    f"{self.role.value} cannot receive read-write Godot MCP"
                )
        if self.role is RoleName.PLANNER and self.godot_mcp is not GodotMCPAccess.DISABLED:
            raise ValueError("planner cannot receive a live Godot MCP binding")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "harness": self.harness,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "workspace_access": self.workspace_access.value,
            "tools": {
                "godot_mcp": self.godot_mcp.value,
                "godot_docs": self.godot_docs,
            },
        }


def default_role_bindings(
    *,
    harness: str = "codex",
    model: str = "gpt-5.5",
    reasoning_effort: str | None = "high",
) -> dict[RoleName, RoleBinding]:
    return {
        RoleName.PLANNER: RoleBinding(
            role=RoleName.PLANNER,
            harness=harness,
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_access=WorkspaceAccess.READ_ONLY,
            godot_mcp=GodotMCPAccess.DISABLED,
        ),
        RoleName.DEVELOPER: RoleBinding(
            role=RoleName.DEVELOPER,
            harness=harness,
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_access=WorkspaceAccess.READ_WRITE,
            godot_mcp=GodotMCPAccess.READ_WRITE,
        ),
        RoleName.TESTER: RoleBinding(
            role=RoleName.TESTER,
            harness=harness,
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_access=WorkspaceAccess.READ_ONLY,
            godot_mcp=GodotMCPAccess.READ_ONLY_RUNTIME,
        ),
    }


def role_bindings_from_config(
    raw_roles: Mapping[str, Any] | None,
    *,
    fallback_harness: str,
    fallback_model: str,
    fallback_reasoning_effort: str | None,
) -> dict[RoleName, RoleBinding]:
    """Parse independent per-role harness bindings from public JSON config."""

    defaults = default_role_bindings(
        harness=fallback_harness,
        model=fallback_model,
        reasoning_effort=fallback_reasoning_effort,
    )
    if raw_roles is None:
        return defaults
    if not isinstance(raw_roles, Mapping):
        raise ValueError("roles must be a JSON object")

    unknown = set(raw_roles) - {role.value for role in RoleName}
    if unknown:
        raise ValueError(f"unknown role configuration: {', '.join(sorted(unknown))}")

    resolved: dict[RoleName, RoleBinding] = {}
    for role in RoleName:
        baseline = defaults[role]
        raw = raw_roles.get(role.value, {})
        if not isinstance(raw, Mapping):
            raise ValueError(f"roles.{role.value} must be a JSON object")
        tools = raw.get("tools", {})
        if not isinstance(tools, Mapping):
            raise ValueError(f"roles.{role.value}.tools must be a JSON object")
        resolved[role] = RoleBinding(
            role=role,
            harness=str(raw.get("harness", baseline.harness)),
            model=str(raw.get("model", baseline.model)),
            reasoning_effort=(
                None
                if raw.get("reasoning_effort", baseline.reasoning_effort) is None
                else str(raw.get("reasoning_effort", baseline.reasoning_effort))
            ),
            workspace_access=WorkspaceAccess(
                str(raw.get("workspace_access", baseline.workspace_access.value))
            ),
            godot_mcp=GodotMCPAccess(
                str(tools.get("godot_mcp", baseline.godot_mcp.value))
            ),
            godot_docs=bool(tools.get("godot_docs", baseline.godot_docs)),
        )
    return resolved
