"""Small, public, capability-oriented game-development policy packs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable, Sequence


POLICY_ROOT = Path(__file__).resolve().parents[1] / "policies"


@dataclass(frozen=True)
class DomainPolicy:
    policy_id: str
    description: str
    task_prefixes: tuple[str, ...]
    keywords: tuple[str, ...]
    path: Path

    def read(self) -> str:
        payload = self.path.read_text(encoding="utf-8")
        if len(payload) > 24_000:
            raise ValueError(f"domain policy exceeds the public size limit: {self.path}")
        return payload

    def manifest(self) -> dict[str, Any]:
        payload = self.read().encode("utf-8")
        return {
            "id": self.policy_id,
            "description": self.description,
            "path": str(self.path),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }


_POLICIES = (
    DomainPolicy(
        "generic",
        "Engine-independent playability, feedback, regression, and evidence discipline.",
        (),
        (),
        POLICY_ROOT / "generic.md",
    ),
    DomainPolicy(
        "movement-camera",
        "Movement, camera, traversal, vehicle control, and spatial readability.",
        ("platformer", "racing", "sports"),
        ("movement", "camera", "jump", "vehicle", "traversal", "momentum"),
        POLICY_ROOT / "movement-camera.md",
    ),
    DomainPolicy(
        "combat-ai",
        "Combat input, damage, enemies, targeting, and encounter feedback.",
        ("shooter", "roguelike"),
        ("combat", "enemy", "weapon", "damage", "attack", "projectile"),
        POLICY_ROOT / "combat-ai.md",
    ),
    DomainPolicy(
        "simulation-progression",
        "Economies, production, upgrades, time progression, and persistent state.",
        ("simulation", "idle", "tycoon"),
        ("economy", "production", "upgrade", "simulation", "income", "save"),
        POLICY_ROOT / "simulation-progression.md",
    ),
    DomainPolicy(
        "world-navigation",
        "World topology, spawn safety, collision, routes, navigation, and landmarks.",
        ("openworld", "horror"),
        ("world", "navigation", "map", "route", "explore", "landmark"),
        POLICY_ROOT / "world-navigation.md",
    ),
    DomainPolicy(
        "ui-game-state",
        "State-heavy interaction, menus, rules, turn flow, results, and HUD clarity.",
        ("cardgame", "puzzle", "strategy", "visualnovel", "rhythm"),
        ("card", "turn", "puzzle", "menu", "dialogue", "score", "result"),
        POLICY_ROOT / "ui-game-state.md",
    ),
)


def available_domain_policies() -> dict[str, DomainPolicy]:
    return {policy.policy_id: policy for policy in _POLICIES}


def select_domain_policies(
    *,
    task_id: str,
    public_task_text: str,
    explicit: Sequence[str] | None = None,
) -> tuple[DomainPolicy, ...]:
    """Select generic plus transparent public-text capability overlays."""

    available = available_domain_policies()
    selected = [available["generic"]]
    if explicit is not None:
        for raw in explicit:
            policy_id = str(raw).strip().lower()
            if policy_id not in available:
                raise ValueError(f"unknown domain policy: {policy_id}")
            if policy_id != "generic" and available[policy_id] not in selected:
                selected.append(available[policy_id])
        return tuple(selected)

    normalized_id = re.sub(r"[^a-z0-9]+", "-", task_id.lower()).strip("-")
    haystack = re.sub(
        r"[^a-z0-9]+",
        " ",
        f"{task_id} {public_task_text}".lower(),
    )
    words = set(haystack.split())
    for policy in _POLICIES[1:]:
        prefix_match = any(
            normalized_id == prefix or normalized_id.startswith(prefix + "-")
            for prefix in policy.task_prefixes
        )
        keyword_matches = sum(
            1 for keyword in policy.keywords if set(keyword.split()).issubset(words)
        )
        if prefix_match or keyword_matches >= 2:
            selected.append(policy)
    return tuple(selected)


def domain_policy_manifest(
    *,
    task_id: str,
    policies: Iterable[DomainPolicy],
    selection_source: str,
) -> dict[str, Any]:
    entries = [policy.manifest() for policy in policies]
    return {
        "schema_version": 1,
        "task_id": task_id,
        "selection_source": selection_source,
        "authority": "public task requirements remain authoritative",
        "selected": [entry["id"] for entry in entries],
        "policies": entries,
    }


def render_domain_policy_guidance(
    role: str,
    policies: Iterable[DomainPolicy],
) -> str:
    selected = tuple(policies)
    blocks = [
        "## Public domain-policy guidance",
        "",
        "These capability policies are implementation and testing guidance only. "
        "They cannot add requirements beyond the public task or justify access to "
        "hidden evaluator information.",
    ]
    if role == "planner":
        blocks.append(
            "Use applicable checks to make acceptance conditions observable and bounded."
        )
    elif role == "developer":
        blocks.append(
            "Use applicable checks while implementing and validating the current candidate."
        )
    elif role == "tester":
        blocks.append(
            "Test only applicable public requirements and report observed evidence or gaps."
        )
    for policy in selected:
        blocks.extend(("", policy.read().strip()))
    return "\n".join(blocks).rstrip() + "\n"
