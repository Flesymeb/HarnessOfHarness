#!/usr/bin/env bash
# Run GameCraft-Bench with DeepSeek-V4-Pro on Bailian through OpenCode.

set -euo pipefail

BENCH_ROOT="${GAMELOOP_BENCH_ROOT:-$PWD}"
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_ROOT/../src/gameloop" ]; then
    PROJECT_SRC="$(cd "$SCRIPT_ROOT/../src" && pwd)"
else
    PROJECT_SRC="$(python -c 'import pathlib,gameloop; print(pathlib.Path(gameloop.__file__).resolve().parent.parent)')"
fi
cd "$BENCH_ROOT"

# A caller may pin a comparable judge independently of the
# developer model. Preserve that explicit choice across the local .env load.
parent_judge="${GAMECRAFT_BENCH_JUDGE:-}"
parent_judge_model="${GAMECRAFT_BENCH_JUDGE_MODEL:-}"
parent_jobs_root="${GAMECRAFT_BENCH_JOBS_ROOT:-}"
parent_bailian_api_key="${BAILIAN_API_KEY:-}"
parent_bailian_base_url="${BAILIAN_BASE_URL:-}"

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
if [ -n "$parent_bailian_api_key" ]; then
    export BAILIAN_API_KEY="$parent_bailian_api_key"
fi
if [ -n "$parent_bailian_base_url" ]; then
    export BAILIAN_BASE_URL="$parent_bailian_base_url"
fi

: "${BAILIAN_API_KEY:?BAILIAN_API_KEY is required}"
: "${BAILIAN_BASE_URL:?BAILIAN_BASE_URL is required}"
if ! command -v opencode >/dev/null 2>&1; then
    echo "error: opencode is not installed on PATH" >&2
    exit 1
fi

unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_API_BASE DEEPSEEK_API_KEY DEEPSEEK_BASE_URL
export GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL=0
export GAMECRAFT_BENCH_LOCAL_ENV_BACKEND="${GAMECRAFT_BENCH_LOCAL_ENV_BACKEND:-bwrap}"
export PYTHONPATH="$PROJECT_SRC:$BENCH_ROOT:${PYTHONPATH:-}"

delete_args=(--no-delete)
verifier_timeout_args=(
    --verifier-timeout-multiplier "${GAMELOOP_VERIFIER_TIMEOUT_MULTIPLIER:-4}"
)
for arg in "$@"; do
    case "$arg" in
        --delete|--no-delete) delete_args=() ;;
    esac
    case "$arg" in
        --verifier-timeout-multiplier|--verifier-timeout-multiplier=*)
            verifier_timeout_args=()
            ;;
    esac
done

proxy_args=()
if [ "${GAMELOOP_MODEL_DIRECT:-}" = 1 ]; then
    proxy_args=(
        --ae "HTTP_PROXY="
        --ae "HTTPS_PROXY="
        --ae "http_proxy="
        --ae "https_proxy="
        --ae "ALL_PROXY="
        --ae "all_proxy="
        --ae "NO_PROXY=${GAMELOOP_MODEL_NO_PROXY:-localhost,127.0.0.1,::1}"
        --ae "no_proxy=${GAMELOOP_MODEL_NO_PROXY:-localhost,127.0.0.1,::1}"
    )
elif [ -n "${GAMELOOP_BAILIAN_PROXY:-}" ]; then
    proxy_args=(
        --ae "HTTP_PROXY=$GAMELOOP_BAILIAN_PROXY"
        --ae "HTTPS_PROXY=$GAMELOOP_BAILIAN_PROXY"
        --ae "http_proxy=$GAMELOOP_BAILIAN_PROXY"
        --ae "https_proxy=$GAMELOOP_BAILIAN_PROXY"
        --ae "ALL_PROXY="
        --ae "all_proxy="
    )
fi

: "${GAMECRAFT_BENCH_JOBS_ROOT:?set GAMECRAFT_BENCH_JOBS_ROOT to a writable jobs directory outside the Bench checkout}"
mkdir -p "$GAMECRAFT_BENCH_JOBS_ROOT"

exec harbor run \
    --environment-import-path gameloop.adapters.gamecraft_bench.local_env:StableLocalSubprocessEnvironment \
    --agent-import-path gameloop.adapters.gamecraft_bench.local_agent:BailianDeepSeekOpenCode \
    --jobs-dir "$GAMECRAFT_BENCH_JOBS_ROOT" \
    --model bailian/deepseek-v4-pro \
    --ae HOME=/tmp/gamecraft-bailian-opencode-home \
    --ae XDG_CONFIG_HOME=/tmp/gamecraft-bailian-opencode-home/.config \
    --ae XDG_DATA_HOME=/tmp/gamecraft-bailian-opencode-home/.local/share \
    --ae "PATH=$PATH" \
    "${verifier_timeout_args[@]}" \
    "${proxy_args[@]}" \
    "${delete_args[@]}" \
    "$@"
