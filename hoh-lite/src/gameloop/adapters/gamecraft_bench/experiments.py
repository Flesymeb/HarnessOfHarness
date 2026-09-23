"""Public harness/model identity used by the GameCraft adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import MutableMapping


@dataclass(frozen=True)
class GameCraftExperimentSpec:
    experiment_id: str
    harness: str
    model: str
    wrapper_name: str
    agent_import_path: str
    reasoning_effort: str | None = None
    harness_version: str | None = None
    harness_preset: str | None = None


EXPERIMENT_SPECS = {
    spec.experiment_id: spec
    for spec in (
        GameCraftExperimentSpec(
            experiment_id="codex-gpt-5.5",
            harness="codex",
            model="gpt-5.5",
            wrapper_name="run_gamecraft_codex_bench.sh",
            agent_import_path="gameloop.adapters.gamecraft_bench.local_agent:GameLoopCodex",
            reasoning_effort="high",
            # The benchmark fixes the model/reasoning pair, while the user
            # explicitly opts into the newest installed Codex CLI.
            harness_version="latest",
        ),
        GameCraftExperimentSpec(
            experiment_id="opencode-deepseek-v4-pro",
            harness="opencode",
            model="deepseek-v4-pro",
            wrapper_name="run_gamecraft_opencode_bailian_deepseek_v4_pro.sh",
            agent_import_path=(
                "gameloop.adapters.gamecraft_bench.local_agent:"
                "BailianDeepSeekOpenCode"
            ),
            harness_version="1.14.30",
        ),
        GameCraftExperimentSpec(
            experiment_id="pi-minimax-m3",
            harness="pi",
            model="minimax-m3",
            wrapper_name="run_gamecraft_pi_minimax_m3.sh",
            agent_import_path=(
                "gameloop.adapters.gamecraft_bench.local_agent:"
                "IsolatedPjlabMinimaxPi"
            ),
            reasoning_effort="high",
            harness_version="0.80.10",
        ),
        GameCraftExperimentSpec(
            experiment_id="dsh-minimal-deepseek-v4-flash",
            harness="deepseek-harness",
            model="deepseek-v4-flash",
            wrapper_name="run_gamecraft_deepseek_harness_v4_flash.sh",
            agent_import_path=(
                "gameloop.adapters.gamecraft_bench.local_agent:"
                "GameLoopDeepSeekHarness"
            ),
            reasoning_effort="high",
            harness_version="0.1.0rc6",
            harness_preset="minimal",
        ),
        GameCraftExperimentSpec(
            experiment_id="dsh-standard-deepseek-v4-flash",
            harness="deepseek-harness",
            model="deepseek-v4-flash",
            wrapper_name="run_gamecraft_deepseek_harness_v4_flash_standard.sh",
            agent_import_path=(
                "gameloop.adapters.gamecraft_bench.local_agent:"
                "GameLoopDeepSeekHarness"
            ),
            reasoning_effort="high",
            harness_version="0.1.0rc6",
            harness_preset="standard",
        ),
    )
}


def apply_experiment_environment(
    experiment_id: str, environment: MutableMapping[str, str]
) -> None:
    """Pin a profile's harness preset even when the host environment differs."""

    preset = EXPERIMENT_SPECS[experiment_id].harness_preset
    if preset is not None:
        environment["DSH_AGENT_PRESET"] = preset
