#!/usr/bin/env bash
# Run GameCraft-Bench with MiniMax-M3 on PJLab through Pi.

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
parent_pjlab_api_key="${PJLAB_API_KEY:-}"
parent_pjlab_base_url="${PJLAB_BASE_URL:-}"
parent_upstream_timeout="${GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS:-}"

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
if [ -n "$parent_judge" ]; then
    export GAMECRAFT_BENCH_JUDGE="$parent_judge"
fi
if [ -n "$parent_judge_model" ]; then
    export GAMECRAFT_BENCH_JUDGE_MODEL="$parent_judge_model"
fi
if [ -n "$parent_jobs_root" ]; then
    export GAMECRAFT_BENCH_JOBS_ROOT="$parent_jobs_root"
fi
if [ -n "$parent_pjlab_api_key" ]; then
    export PJLAB_API_KEY="$parent_pjlab_api_key"
fi
if [ -n "$parent_pjlab_base_url" ]; then
    export PJLAB_BASE_URL="$parent_pjlab_base_url"
fi
if [ -n "$parent_upstream_timeout" ]; then
    export GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS="$parent_upstream_timeout"
fi

pjlab_key_file="${PJLAB_API_KEY_FILE:-$HOME/.config/gameloop/secrets/pjlab_api_key}"
if [ -z "${PJLAB_API_KEY:-}" ] && [ -r "$pjlab_key_file" ]; then
    PJLAB_API_KEY="$(<"$pjlab_key_file")"
    export PJLAB_API_KEY
fi
export PJLAB_BASE_URL="${PJLAB_BASE_URL:-https://api.pjlab.org.cn/v1}"
export GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS="${GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS:-300}"
if [ -n "${GAMELOOP_PI_MINIMAX_MODEL:-}" ] \
    && [ "$GAMELOOP_PI_MINIMAX_MODEL" != "minimax-m3" ]; then
    echo "error: Pi + MiniMax M3 profile requires minimax-m3" >&2
    exit 2
fi

: "${PJLAB_API_KEY:?PJLAB_API_KEY or a readable PJLAB_API_KEY_FILE is required}"
if ! command -v pi >/dev/null 2>&1; then
    echo "error: pi is not installed on PATH" >&2
    exit 1
fi

unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_API_BASE
export GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL=0
export GAMECRAFT_BENCH_LOCAL_ENV_BACKEND="${GAMECRAFT_BENCH_LOCAL_ENV_BACKEND:-bwrap}"
export PYTHONPATH="$PROJECT_SRC:$BENCH_ROOT:${PYTHONPATH:-}"

delete_args=(--no-delete)
verifier_timeout_args=(
    --verifier-timeout-multiplier "${GAMELOOP_VERIFIER_TIMEOUT_MULTIPLIER:-4}"
)
# Pi retries transient model failures in-session. Retrying at Harbor level
# starts from a fresh task workspace and loses already completed development.
retry_args=(--max-retries "${GAMELOOP_HARBOR_MAX_RETRIES:-0}")
loop_timeout_args=()
has_loop_instruction=0
has_agent_timeout_multiplier=0
for arg in "$@"; do
    case "$arg" in
        --delete|--no-delete) delete_args=() ;;
    esac
    case "$arg" in
        --verifier-timeout-multiplier|--verifier-timeout-multiplier=*)
            verifier_timeout_args=()
            ;;
    esac
    case "$arg" in
        --max-retries|--max-retries=*) retry_args=() ;;
    esac
    case "$arg" in
        --extra-instruction-path|--extra-instruction-path=*) has_loop_instruction=1 ;;
        --agent-timeout-multiplier|--agent-timeout-multiplier=*)
            has_agent_timeout_multiplier=1
            ;;
    esac
done
if [ "$has_loop_instruction" = 1 ] && [ "$has_agent_timeout_multiplier" = 0 ]; then
    loop_timeout_args=(
        --agent-timeout-multiplier
        "${GAMELOOP_PI_M3_LOOP_AGENT_TIMEOUT_MULTIPLIER:-4}"
    )
fi

: "${GAMECRAFT_BENCH_JOBS_ROOT:?set GAMECRAFT_BENCH_JOBS_ROOT to a writable jobs directory outside the Bench checkout}"
mkdir -p "$GAMECRAFT_BENCH_JOBS_ROOT"

exec harbor run \
    --environment-import-path gameloop.adapters.gamecraft_bench.local_env:StableLocalSubprocessEnvironment \
    --agent-import-path gameloop.adapters.gamecraft_bench.local_agent:IsolatedPjlabMinimaxPi \
    --jobs-dir "$GAMECRAFT_BENCH_JOBS_ROOT" \
    --model pjlab/minimax-m3 \
    --ae HOME=/tmp/gamecraft-pjlab-pi-home \
    --ae PI_CODING_AGENT_DIR=/tmp/gamecraft-pjlab-pi-home/.pi/agent \
    --ae PI_TELEMETRY=0 \
    --ae PI_OFFLINE=1 \
    --ae "GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS=$GAMELOOP_OPENAI_UPSTREAM_TIMEOUT_SECONDS" \
    --ae "PATH=$PATH" \
    --ae LD_PRELOAD= \
    --ae PROXYCHAINS_CONF_FILE= \
    --ae PROXYCHAINS_QUIET_MODE= \
    --ae HTTP_PROXY= \
    --ae HTTPS_PROXY= \
    --ae http_proxy= \
    --ae https_proxy= \
    --ae ALL_PROXY= \
    --ae all_proxy= \
    --ae NO_PROXY=localhost,127.0.0.1,::1,api.pjlab.org.cn,token.pjlab.org.cn \
    --ae no_proxy=localhost,127.0.0.1,::1,api.pjlab.org.cn,token.pjlab.org.cn \
    "${loop_timeout_args[@]}" \
    "${verifier_timeout_args[@]}" \
    "${retry_args[@]}" \
    "${delete_args[@]}" \
    "$@"
