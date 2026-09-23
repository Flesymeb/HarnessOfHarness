#!/usr/bin/env bash
# Run GameCraft-Bench with the official Codex login and no demo-only credentials.

set -euo pipefail

BENCH_ROOT="${GAMELOOP_BENCH_ROOT:-$PWD}"
cd "$BENCH_ROOT"

# A caller may pin a comparable judge independently of the
# developer model. Preserve that explicit choice across the local .env load.
parent_judge="${GAMECRAFT_BENCH_JUDGE:-}"
parent_judge_model="${GAMECRAFT_BENCH_JUDGE_MODEL:-}"
parent_developer_model="${GAMELOOP_DEVELOPER_MODEL:-gpt-5.5}"

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
export GAMELOOP_DEVELOPER_MODEL="$parent_developer_model"

# Demo/e2e providers must never affect comparable benchmark runs.
login_base_url="${GAMECRAFT_BENCH_LOGIN_BASE_URL-${GAMELOOP_CODEX_LOGIN_BASE_URL-}}"
unset \
    DASHSCOPE_API_KEY \
    DASHSCOPE_BASE_URL \
    ANTHROPIC_AUTH_TOKEN \
    ANTHROPIC_BASE_URL \
    GAMECRAFT_BENCH_JUDGE_OPENAI_API_KEY \
    GAMECRAFT_BENCH_JUDGE_OPENAI_BASE_URL \
    GAMELOOP_TESTER_API_KEY \
    GAMELOOP_TESTER_BASE_URL

case "${CODEX_FORCE_AUTH_JSON:-}" in
    1|true|TRUE|yes|YES|on|ON) ;;
    *)
        echo "error: benchmark wrapper requires the official Codex login" >&2
        exit 1
        ;;
esac

unset OPENAI_API_KEY OPENAI_API_BASE
if [ -n "$login_base_url" ]; then
    # Keep the official auth.json login, but route Codex through an explicit
    # OpenAI-compatible endpoint when direct api.openai.com access is absent.
    export OPENAI_BASE_URL="$login_base_url"
    export GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL=1
else
    unset OPENAI_BASE_URL
    export GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL=0
fi
export PYTHONPATH="$BENCH_ROOT:${PYTHONPATH:-}"

delete_args=(--no-delete)
for arg in "$@"; do
    case "$arg" in
        --delete|--no-delete) delete_args=(); break ;;
    esac
done

reasoning_effort_set=0
developer_mcp_enforced=0
for arg in "$@"; do
    case "$arg" in
        reasoning_effort=?*|--ak=reasoning_effort=?*) reasoning_effort_set=1 ;;
        --mcp-config|--mcp-config=*) developer_mcp_enforced=1 ;;
    esac
done
if [ "$reasoning_effort_set" -ne 1 ]; then
    echo "error: reasoning_effort must be set via Harbor args" >&2
    exit 1
fi

: "${GAMECRAFT_BENCH_JOBS_ROOT:?set GAMECRAFT_BENCH_JOBS_ROOT to a writable jobs directory outside the Bench checkout}"
mkdir -p "$GAMECRAFT_BENCH_JOBS_ROOT"

clean_env=(
    "PATH=$PATH"
    "HOME=$HOME"
    "CODEX_FORCE_AUTH_JSON=1"
    "GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL=$GAMECRAFT_BENCH_FORWARD_OPENAI_BASE_URL"
    "GAMECRAFT_BENCH_JOBS_ROOT=$GAMECRAFT_BENCH_JOBS_ROOT"
    "GAMELOOP_DEVELOPER_MODEL=$GAMELOOP_DEVELOPER_MODEL"
    "PYTHONPATH=$PYTHONPATH"
)
if [ "$developer_mcp_enforced" -eq 1 ]; then
    clean_env+=("GAMELOOP_REQUIRE_DEVELOPER_MCP_TRANSPORT=1")
fi
for name in \
    ALL_PROXY \
    CODEX_HOME \
    CODEX_AUTH_JSON_PATH \
    DISPLAY \
    GAMECRAFT_BENCH_ASSET_LIBRARY \
    GAMECRAFT_BENCH_EXEC_BACKEND \
    GAMECRAFT_BENCH_LOCAL_ENV_BACKEND \
    GAMECRAFT_BENCH_JUDGE \
    GAMECRAFT_BENCH_JUDGE_CALL_TIMEOUT_SECONDS \
    GAMECRAFT_BENCH_JUDGE_CODEX_CLEAR_OPENAI_ENV \
    GAMECRAFT_BENCH_JUDGE_CODEX_TIMEOUT_SECONDS \
    GAMECRAFT_BENCH_JUDGE_MODEL \
    GAMELOOP_GODOT_DOCS_ROOT \
    GAMELOOP_GODOT_EDITOR_BIN \
    GAMELOOP_GAMECRAFT_BACKEND \
    GAMELOOP_GAMECRAFT_ALLOW_DIRECT_BACKEND \
    GAMELOOP_GODOT_MCP_STARTUP_TIMEOUT_SECONDS \
    GAMELOOP_GODOT_MAX_CPUS \
    GAMECRAFT_BENCH_OGA_LIBRARY \
    GODOT_BIN \
    HTTPS_PROXY \
    HTTP_PROXY \
    LANG \
    LC_ALL \
    LC_CTYPE \
    LOGNAME \
    NODE_EXTRA_CA_CERTS \
    NO_PROXY \
    REQUESTS_CA_BUNDLE \
    SHELL \
    SSL_CERT_DIR \
    SSL_CERT_FILE \
    TERM \
    TMPDIR \
    TZ \
    USER \
    VIRTUAL_ENV \
    WAYLAND_DISPLAY \
    XAUTHORITY \
    XDG_RUNTIME_DIR \
    all_proxy \
    http_proxy \
    https_proxy \
    no_proxy
do
    if [ -n "${!name:-}" ]; then
        clean_env+=("$name=${!name}")
    fi
done

# Keep host-level AGENTS.md and installed skills out of the vanilla baseline.
exec env -i "${clean_env[@]}" harbor run \
    --environment-import-path gameloop.adapters.gamecraft_bench.local_env:StableLocalSubprocessEnvironment \
    --agent-import-path gameloop.adapters.gamecraft_bench.local_agent:GameLoopCodex \
    --jobs-dir "$GAMECRAFT_BENCH_JOBS_ROOT" \
    --model "$GAMELOOP_DEVELOPER_MODEL" \
    --ae HOME=/tmp/gamecraft-vanilla-home \
    "${delete_args[@]}" \
    "$@"
