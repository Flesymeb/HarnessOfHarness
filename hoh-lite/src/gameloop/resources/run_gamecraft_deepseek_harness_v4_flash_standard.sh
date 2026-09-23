#!/usr/bin/env bash
# Run GameCraft-Bench with the official DeepSeek Harness standard preset.

set -euo pipefail

BENCH_ROOT="${GAMELOOP_BENCH_ROOT:-$PWD}"
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_ROOT/../src/gameloop" ]; then
    PROJECT_SRC="$(cd "$SCRIPT_ROOT/../src" && pwd)"
else
    PROJECT_SRC="$(python -c 'import pathlib,gameloop; print(pathlib.Path(gameloop.__file__).resolve().parent.parent)')"
fi
cd "$BENCH_ROOT"

parent_judge="${GAMECRAFT_BENCH_JUDGE:-}"
parent_judge_model="${GAMECRAFT_BENCH_JUDGE_MODEL:-}"
parent_jobs_root="${GAMECRAFT_BENCH_JOBS_ROOT:-}"
parent_deepseek_key="${DEEPSEEK_API_KEY:-}"
parent_deepseek_key_file="${DEEPSEEK_API_KEY_FILE:-}"
parent_deepseek_url="${DEEPSEEK_BASE_URL:-}"
parent_danger_ack="${GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS:-}"
parent_standard_runtime="${GAMELOOP_DSH_STANDARD_RUNTIME:-}"
parent_dsh_max_tokens="${DSH_MAX_TOKENS:-16384}"
parent_dsh_reasoning_effort="${DSH_REASONING_EFFORT:-high}"
parent_dsh_turn_retry_limit="${DSH_TURN_RETRY_LIMIT:-2}"
default_standard_runtime="${XDG_DATA_HOME:-$HOME/.local/share}/gameloop/deepseek-harness/standard-runtime/dsh-jsonrpc-agent-pkg-linux-x64"

if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
fi
if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source ".env"
    set +a
fi
for item in \
    "GAMECRAFT_BENCH_JUDGE=$parent_judge" \
    "GAMECRAFT_BENCH_JUDGE_MODEL=$parent_judge_model" \
    "GAMECRAFT_BENCH_JOBS_ROOT=$parent_jobs_root" \
    "DEEPSEEK_API_KEY=$parent_deepseek_key" \
    "DEEPSEEK_API_KEY_FILE=$parent_deepseek_key_file" \
    "DEEPSEEK_BASE_URL=$parent_deepseek_url" \
    "GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS=$parent_danger_ack" \
    "GAMELOOP_DSH_STANDARD_RUNTIME=$parent_standard_runtime" \
    "DSH_AGENT_PRESET=standard" \
    "DSH_MAX_TOKENS=$parent_dsh_max_tokens" \
    "DSH_REASONING_EFFORT=$parent_dsh_reasoning_effort" \
    "DSH_TURN_RETRY_LIMIT=$parent_dsh_turn_retry_limit"
do
    name="${item%%=*}"
    value="${item#*=}"
    if [ -n "$value" ]; then export "$name=$value"; fi
done

credential_args=()
credential_tmp=""
cleanup_credential_tmp() {
    if [ -n "$credential_tmp" ]; then rm -f -- "$credential_tmp"; fi
}
trap cleanup_credential_tmp EXIT
if [ -n "${DEEPSEEK_API_KEY_FILE:-}" ]; then
    if [ ! -r "$DEEPSEEK_API_KEY_FILE" ]; then
        echo "error: DEEPSEEK_API_KEY_FILE is not readable: $DEEPSEEK_API_KEY_FILE" >&2
        exit 1
    fi
    unset DEEPSEEK_API_KEY
    credential_args=(--ae "DEEPSEEK_API_KEY_FILE=$DEEPSEEK_API_KEY_FILE")
elif [ -n "${DEEPSEEK_API_KEY:-}" ]; then
    credential_tmp="$(mktemp "${TMPDIR:-/tmp}/gameloop-deepseek-key.XXXXXX")"
    chmod 600 "$credential_tmp"
    printf '%s' "$DEEPSEEK_API_KEY" > "$credential_tmp"
    unset DEEPSEEK_API_KEY
    credential_args=(--ae "DEEPSEEK_API_KEY_FILE=$credential_tmp")
else
    echo 'error: DEEPSEEK_API_KEY or DEEPSEEK_API_KEY_FILE is required' >&2
    exit 1
fi
: "${DEEPSEEK_BASE_URL:?DEEPSEEK_BASE_URL is required}"
if [ "${GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS:-}" != "1" ]; then
    echo 'error: standalone DSH standard uses danger-full-access; set GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS=1 only on a trusted evaluation host' >&2
    exit 1
fi

python -c 'import importlib.metadata as m; assert m.version("deepseek-harness-sdk") == "0.1.0rc6"; assert m.version("deepseek-harness-runtime-bin") == "0.1.0rc6"' || {
    echo 'error: install gameloop[deepseek-harness] into the GameCraft venv' >&2
    exit 1
}

export GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL=0
# The official standard composition runs against the host-only runtime. It is
# intentionally used in the trusted direct backend on this machine because
# bwrap user namespaces are blocked by the host AppArmor policy.
# This direct backend is therefore an explicit trusted-host mode, acknowledged
# above, until the host can provide an outer container or working bwrap.
export GAMECRAFT_BENCH_LOCAL_ENV_BACKEND=direct
export GAMELOOP_GAMECRAFT_ALLOW_DIRECT_BACKEND=1
export PYTHONPATH="$PROJECT_SRC:$BENCH_ROOT:${PYTHONPATH:-}"

delete_args=(--no-delete)
for arg in "$@"; do
    case "$arg" in --delete|--no-delete) delete_args=() ;; esac
done

: "${GAMECRAFT_BENCH_JOBS_ROOT:?set GAMECRAFT_BENCH_JOBS_ROOT to a writable jobs directory outside the Bench checkout}"
mkdir -p "$GAMECRAFT_BENCH_JOBS_ROOT"

harbor run \
    --environment-import-path gameloop.adapters.gamecraft_bench.local_env:StableLocalSubprocessEnvironment \
    --agent-import-path gameloop.adapters.gamecraft_bench.local_agent:GameLoopDeepSeekHarness \
    --jobs-dir "$GAMECRAFT_BENCH_JOBS_ROOT" \
    --model deepseek-v4-flash \
    --ae HOME=/tmp/gamecraft-dsh-home \
    --ae "PATH=$PATH" \
    --ae "PYTHONPATH=$PYTHONPATH" \
    "${credential_args[@]}" \
    --ae "DEEPSEEK_BASE_URL=$DEEPSEEK_BASE_URL" \
    --ae "GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS=$GAMELOOP_DSH_ALLOW_DANGER_FULL_ACCESS" \
    --ae "DSH_AGENT_PRESET=standard" \
    --ae "DSH_MAX_TOKENS=${DSH_MAX_TOKENS:-16384}" \
    --ae "DSH_REASONING_EFFORT=${DSH_REASONING_EFFORT:-high}" \
    --ae "DSH_TURN_RETRY_LIMIT=${DSH_TURN_RETRY_LIMIT:-2}" \
    --ae "GAMELOOP_DSH_STANDARD_RUNTIME=${GAMELOOP_DSH_STANDARD_RUNTIME:-$default_standard_runtime}" \
    "${delete_args[@]}" \
    "$@"
