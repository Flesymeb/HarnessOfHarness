"""Public-evidence policies for GameLoop iterations."""

from __future__ import annotations


PUBLIC_ONLY_EVIDENCE_POLICY = (
    "Use only public task text, generated artifacts, replay media, screenshots, "
    "visible runtime errors, and role-produced reports. Do not use hidden tests, "
    "private evaluator text, numeric score formulas, hidden requirement IDs, or "
    "private evaluator rationales as loop inputs."
)

ITERATION_UPGRADE_DIMENSIONS = [
    "gameplay mechanics",
    "content breadth",
    "difficulty progression",
    "visual production",
    "result surfaces",
    "demo evidence",
]

FORBIDDEN_PRIVATE_EVIDENCE_TERMS = [
    "hidden tests",
    "private evaluator",
    "score formula",
    "hidden requirement IDs",
    "evaluator-only rationales",
]


def public_only_policy_text() -> str:
    return PUBLIC_ONLY_EVIDENCE_POLICY
