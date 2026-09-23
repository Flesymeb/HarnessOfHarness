"""DeepSeek Harness SDK adapters for the official minimal and standard presets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sys

from gameloop.harnesses.base import HarnessRequest, PreparedHarness


SDK_VERSION = "0.1.0rc6"
RUNTIME_VERSION = "0.1.0rc6"
SOURCE_VERSION = "0.1.0-rc.5"
SOURCE_COMMIT = "47f943859bef60e4160492346772ded9b24f765a"
MINIMAL_PRESET_SHA256 = (
    "cacb47f09a88985c8eb0906a62e6883205727a3c8db901807cb03f936b863cca"
)
MINIMAL_CORDIS_SHA256 = (
    "4ddf99b5492fac7b578e3caddb0158815e44d5db176ba0aeab57012d35299fca"
)
MINIMAL_SYSTEM_PROMPT_SHA256 = (
    "5fab6e32f283d71510531ce850df2690b8fb77437d36bfabbe8c4ac862f19df9"
)
STANDARD_PRESET_SHA256 = (
    "cb98756a9ed76ca351a45a0ba138a97bf0ab7eead4fe2f1e9d1c9f9ec97937f0"
)
STANDARD_CORDIS_SHA256 = (
    "1a945ebc8c41a2d56c5c4bfc8ba7654ccdbb58b269fcba8eda4174f15558d636"
)
STANDARD_RUNTIME_DEFAULT = (
    Path.home()
    / ".local/share/gameloop/deepseek-harness/"
    / "standard-runtime/dsh-jsonrpc-agent-pkg-linux-x64"
)


@dataclass(frozen=True)
class DshMinimalBundle:
    cordis: Path
    preset: Path
    runtime_command: tuple[Path, ...]


@dataclass(frozen=True)
class DshStandardBundle:
    cordis: Path
    preset: Path
    runtime_command: tuple[Path, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_minimal_bundle() -> DshMinimalBundle:
    """Validate the vendored official minimal composition and bundled runtime."""
    resources = Path(__file__).parents[1] / "resources/deepseek_harness"
    cordis = resources / "minimal.cordis.yml"
    preset = resources / "official_minimal.cordis.yml"
    expected = (
        (cordis, MINIMAL_CORDIS_SHA256, "standalone minimal config"),
        (preset, MINIMAL_PRESET_SHA256, "official minimal preset"),
    )
    for path, digest, label in expected:
        if not path.is_file():
            raise RuntimeError(f"DSH {label} is missing: {path}")
        actual = sha256_file(path)
        if actual != digest:
            raise RuntimeError(
                f"DSH {label} SHA-256 mismatch: expected {digest}, got {actual}"
            )

    try:
        from deepseek_harness_runtime import resolve_bundled_launch_args

        raw_command = resolve_bundled_launch_args()
    except (ImportError, FileNotFoundError, ValueError) as error:
        raise RuntimeError(
            "DeepSeek Harness bundled runtime executable is unavailable"
        ) from error
    runtime_command = tuple(Path(item).expanduser().resolve() for item in raw_command)
    missing = [str(path) for path in runtime_command if not path.is_file()]
    if missing:
        raise RuntimeError("DSH bundled runtime files are missing: " + ", ".join(missing))
    return DshMinimalBundle(
        cordis=cordis,
        preset=preset,
        runtime_command=runtime_command,
    )


def validate_standard_bundle() -> DshStandardBundle:
    """Validate the GameLoop host-only standard composition and runtime."""
    resources = Path(__file__).parents[1] / "resources/deepseek_harness"
    cordis = resources / "standard.cordis.yml"
    preset = resources / "official_standard.cordis.yml"
    for path, digest, label in (
        (cordis, STANDARD_CORDIS_SHA256, "standard config"),
        (preset, STANDARD_PRESET_SHA256, "official standard preset"),
    ):
        if not path.is_file():
            raise RuntimeError(f"DSH {label} is missing: {path}")
        actual = sha256_file(path)
        if actual != digest:
            raise RuntimeError(
                f"DSH {label} SHA-256 mismatch: expected {digest}, got {actual}"
            )
    override = os.environ.get("GAMELOOP_DSH_STANDARD_RUNTIME", "").strip()
    runtime = Path(override).expanduser() if override else STANDARD_RUNTIME_DEFAULT
    runtime = runtime.resolve()
    if not runtime.is_file():
        raise RuntimeError(
            "DSH standard host-only runtime executable is unavailable: "
            f"{runtime}; set GAMELOOP_DSH_STANDARD_RUNTIME to the built binary"
        )
    return DshStandardBundle(
        cordis=cordis,
        preset=preset,
        runtime_command=(runtime,),
    )


class DeepSeekHarnessAdapter:
    harness_id = "deepseek-harness"

    def prepare(self, request: HarnessRequest) -> PreparedHarness:
        if request.binding.model != "deepseek-v4-flash":
            raise ValueError(
                "DeepSeek Harness profile requires deepseek-v4-flash"
            )
        env = dict(request.environment)
        if not env.get("DEEPSEEK_API_KEY"):
            raw_key_file = env.get("DEEPSEEK_API_KEY_FILE") or env.get(
                "PJLAB_API_KEY_FILE"
            )
            if raw_key_file:
                key_file = Path(raw_key_file).expanduser()
                if key_file.is_file():
                    env["DEEPSEEK_API_KEY"] = key_file.read_text(
                        encoding="utf-8"
                    ).strip()
        if not env.get("DEEPSEEK_BASE_URL") and env.get("PJLAB_BASE_URL"):
            env["DEEPSEEK_BASE_URL"] = env["PJLAB_BASE_URL"]
        if not env.get("DEEPSEEK_API_KEY"):
            raise RuntimeError(
                "DEEPSEEK_API_KEY or DEEPSEEK_API_KEY_FILE is required for "
                "DeepSeek Harness"
            )
        if not env.get("DEEPSEEK_BASE_URL"):
            raise RuntimeError("DEEPSEEK_BASE_URL is required for DeepSeek Harness")
        if env.get("GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS") != "1":
            raise RuntimeError(
                "official standalone minimal uses danger-full-access; set "
                "GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS=1 only in an isolated or "
                "trusted evaluation environment"
            )
        preset_name = env.get("DSH_AGENT_PRESET", "minimal").strip().lower()
        if preset_name == "minimal":
            bundle = validate_minimal_bundle()
        elif preset_name == "standard":
            bundle = validate_standard_bundle()
        else:
            raise ValueError("DSH_AGENT_PRESET must be either 'minimal' or 'standard'")
        artifact_dir = request.output_path.parent / "deepseek_harness"
        command = (
            sys.executable,
            "-m",
            "gameloop.harnesses.deepseek_worker",
            "--prompt-file",
            str(request.prompt_path),
            "--output",
            str(request.output_path),
            "--workspace",
            str(request.workspace),
            "--artifact-dir",
            str(artifact_dir),
        )
        env.update(
            {
                "DSH_MODEL": request.binding.model,
                "DSH_REASONING_EFFORT": env.get("DSH_REASONING_EFFORT")
                or request.binding.reasoning_effort
                or "high",
                "DSH_AGENT_PRESET": preset_name,
            }
        )
        env.pop("DSH_SYSTEM_PROMPT", None)
        return PreparedHarness(
            command=command,
            environment=env,
            stdin_path=None,
            output_mode="dsh",
            preserved_paths=(Path(sys.executable), bundle.cordis, *bundle.runtime_command),
        )
