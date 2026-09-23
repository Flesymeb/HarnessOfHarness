"""Codex CLI multimodal judge for an unmodified GameCraft-Bench verifier."""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO

from gamecraft_bench.verifier.judges.base import (
    JudgeError,
    JudgeRequest,
    JudgeResponse,
    MultimodalJudge,
)
from gameloop.core.execution import run_captured_command


_MAX_FRAMES = 24
_DEFAULT_TIMEOUT_SECONDS = 900
_LOCK_PATH = "/tmp/gameloop-gamecraft-codex-judge.lock"
CODEX_JUDGE_PROTOCOL = "gameloop-codex-cli-visible-frames-v1"
_VALID_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
_INSTRUCTION = (
    "Review only the visible evidence in the attached time-ordered game frames. "
    "Score every listed requirement from 0.0 to 1.0 and return only schema-valid "
    "JSON. Do not infer hidden implementation details."
)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _select_frames(frames: list[Path]) -> list[Path]:
    limit = _positive_int("GAMECRAFT_BENCH_JUDGE_CODEX_MAX_FRAMES", _MAX_FRAMES)
    if len(frames) <= limit:
        return list(frames)
    step = len(frames) / float(limit)
    return [frames[min(int(index * step), len(frames) - 1)] for index in range(limit)]


def _positive_float(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _observation_frames(frames: list[Path], output_dir: Path) -> list[Path]:
    """Create bounded model-side images while preserving original evidence.

    The verifier keeps the native-resolution PNGs in its evidence directory,
    but Codex receives temporary JPEG observations.  A complex 1280x720 PNG
    can exceed the CLI's single-image/context limits; resizing and quality
    bounding avoids truncation without changing the recorded evidence.
    """

    width_limit = int(
        _positive_float("GAMECRAFT_BENCH_JUDGE_CODEX_OBSERVATION_MAX_WIDTH", 854)
    )
    quality = int(
        _positive_float("GAMECRAFT_BENCH_JUDGE_CODEX_OBSERVATION_JPEG_QUALITY", 80)
    )
    quality = max(30, min(95, quality))
    try:
        from PIL import Image
    except ImportError:
        return list(frames)

    result: list[Path] = []
    for index, frame in enumerate(frames):
        target = output_dir / f"observation-{index:04d}.jpg"
        try:
            with Image.open(frame) as image:
                image = image.convert("RGB")
                if image.width > width_limit:
                    height = max(1, round(image.height * width_limit / image.width))
                    image = image.resize((width_limit, height), Image.Resampling.LANCZOS)
                image.save(target, format="JPEG", quality=quality, optimize=True)
            result.append(target)
        except (OSError, ValueError):
            # A malformed fixture should still produce the same judge error
            # as before; do not hide it behind an observation conversion error.
            result.append(frame)
    return result


def _schema(request: JudgeRequest) -> dict:
    ids = [requirement.id for requirement in request.requirements]
    return {
        "type": "object",
        "required": ["scores", "rationales"],
        "additionalProperties": False,
        "properties": {
            "scores": {
                "type": "object",
                "required": ids,
                "additionalProperties": False,
                "properties": {
                    item: {"type": "number", "minimum": 0.0, "maximum": 1.0}
                    for item in ids
                },
            },
            "rationales": {
                "type": "object",
                "required": ids,
                "additionalProperties": False,
                "properties": {item: {"type": "string"} for item in ids},
            },
        },
    }


def _build_user_prompt(request: JudgeRequest) -> str:
    lines = ["Evaluate the recording against each requirement.", "", "Requirements:"]
    lines.extend(
        f"- {requirement.id}: {requirement.description}"
        for requirement in request.requirements
    )
    lines.extend(
        (
            "",
            "Return JSON matching the supplied output schema. Include a score "
            "and one short visible-evidence rationale for every requirement.",
        )
    )
    return "\n".join(lines)


def _extract_json_object(text: str) -> str | None:
    fenced = _JSON_FENCE_RE.search(text)
    if fenced and fenced.group(1).lstrip().startswith("{"):
        return fenced.group(1).strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return text[index : index + end]
    return None


def _parse_judge_json(
    text: str,
    request: JudgeRequest,
) -> tuple[dict[str, float], dict[str, str]]:
    payload = _extract_json_object(text)
    if payload is None:
        raise ValueError("no JSON object found in judge response")
    data = json.loads(payload)
    raw_scores = data.get("scores") if isinstance(data, dict) else None
    raw_rationales = data.get("rationales") if isinstance(data, dict) else None
    if not isinstance(raw_scores, dict):
        raise ValueError("judge response is missing the scores object")
    if not isinstance(raw_rationales, dict):
        raw_rationales = {}

    scores: dict[str, float] = {}
    rationales: dict[str, str] = {}
    for requirement in request.requirements:
        try:
            value = float(raw_scores.get(requirement.id, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        scores[requirement.id] = max(0.0, min(1.0, value))
        rationale = raw_rationales.get(requirement.id, "")
        rationales[requirement.id] = "" if rationale is None else str(rationale)
    return scores, rationales


@contextmanager
def _judge_slot() -> Iterator[TextIO]:
    path = Path(os.environ.get("GAMECRAFT_BENCH_JUDGE_CODEX_LOCK_PATH", _LOCK_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield handle
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class CodexCliJudge(MultimodalJudge):
    """Use the user's existing Codex login without patching the Bench registry."""

    name = "codex-cli"
    default_model = "gpt-5.5"
    protocol = CODEX_JUDGE_PROTOCOL

    def score(self, request: JudgeRequest) -> JudgeResponse:
        if not request.frame_paths:
            raise JudgeError(f"no sampled frames available for {request.demo_id!r}")

        frames = _select_frames(request.frame_paths)
        prompt = "\n\n".join(
            (
                _INSTRUCTION,
                f"The next {len(frames)} PNG frames are ordered by time.",
                _build_user_prompt(request),
            )
        )
        effort = os.environ.get(
            "GAMECRAFT_BENCH_JUDGE_CODEX_REASONING_EFFORT", "high"
        ).strip().lower()
        if effort not in _VALID_EFFORTS:
            effort = "high"
        timeout = float(
            os.environ.get(
                "GAMECRAFT_BENCH_JUDGE_CODEX_TIMEOUT_SECONDS",
                str(_DEFAULT_TIMEOUT_SECONDS),
            )
        )
        env = os.environ.copy()
        if os.environ.get("GAMECRAFT_BENCH_JUDGE_CODEX_CLEAR_OPENAI_ENV", "1") != "0":
            for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_API_KEY"):
                env.pop(name, None)

        with tempfile.TemporaryDirectory(prefix="gameloop-codex-judge-") as temp:
            temp_path = Path(temp)
            schema_path = temp_path / "schema.json"
            output_path = temp_path / "result.json"
            observation_frames = _observation_frames(frames, temp_path)
            schema_path.write_text(json.dumps(_schema(request)), encoding="utf-8")
            command = [
                os.environ.get("GAMECRAFT_BENCH_JUDGE_CODEX_BIN", "codex"),
                "exec",
                "--skip-git-repo-check",
                "--ignore-user-config",
                "--ignore-rules",
                "--ephemeral",
                "--model",
                self.model,
                "--sandbox",
                "read-only",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-c",
                f"model_reasoning_effort={effort}",
            ]
            for frame in observation_frames:
                command.extend(("--image", str(frame)))
            command.append("-")
            try:
                with _judge_slot():
                    result = run_captured_command(
                        command,
                        input_text=prompt,
                        cwd=Path(
                            os.environ.get("GAMECRAFT_BENCH_JUDGE_CODEX_CWD", "/tmp")
                        ),
                        env=env,
                        timeout_seconds=timeout,
                    )
            except FileNotFoundError as error:
                raise JudgeError("codex CLI not found on PATH") from error

            if result.timed_out:
                raise JudgeError(f"codex CLI judge timed out after {timeout:.1f}s")

            raw = output_path.read_text(encoding="utf-8").strip() if output_path.is_file() else ""
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or raw).strip().splitlines()[-8:]
                raise JudgeError(
                    f"codex CLI judge exited {result.returncode}: {' | '.join(detail)}"
                )
            if not raw:
                raw = (result.stdout or "").strip()

        try:
            scores, rationales = _parse_judge_json(raw, request)
        except (json.JSONDecodeError, ValueError) as error:
            raise JudgeError(f"could not parse Codex judge response: {error}") from error
        return JudgeResponse(scores=scores, rationales=rationales, raw=raw)


__all__ = ["CODEX_JUDGE_PROTOCOL", "CodexCliJudge"]
