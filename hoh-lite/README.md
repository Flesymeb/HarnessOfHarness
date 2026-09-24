# HoH-lite

HoH-lite is a lightweight, extensible implementation of the core
[Harness-of-Harness](https://arxiv.org/abs/2609.01481) workflow. It runs the
Planner–Developer–Tester loop and carries the project forward between
iterations. You can add harnesses and adapters for other benchmarks or real
projects.

## Quick start

You need Python 3.12+, Godot 4, and the CLI and credentials for your chosen
harness. The bundled example also needs an external benchmark checkout,
Node.js/npm, bubblewrap, Xvfb, xdotool, and FFmpeg for MCP and replay.

From `hoh-lite/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e /path/to/benchmark -e '.[gamecraft-bench]'
cp .env.example .env
# Set GAMELOOP_HOME, GAMELOOP_BENCH, and your local credentials in .env.
gameloop-godot-mcp-vendor prepare
gameloop --config configs/harnesses/codex-gpt-5.5.json \
  --bench /path/to/benchmark \
  --task tasks/your-task \
  --run-id my-run
```

Run IDs must be new. To continue from an archived trial, use a new run ID with
`--seed-trial-dir` and `--start-loop-index`; reusing an existing run ID fails
before its receipts or artifacts can be overwritten.

To pick the latest completed valid loop from a previous run automatically, use
`--resume-from runs/old-run --run-id new-run` with the same `--task`. Partial
work in an interrupted loop is left untouched in the old run.

Each run writes `reproducibility.json` with the observed tool versions, source
and benchmark revisions, role bindings, and configuration hash. The paper used
Codex CLI 0.142.5; the default profile accepts the installed Codex CLI, so
check this manifest before comparing a run with the paper's results.

Choose another profile in `configs/harnesses/` to use a different harness or
model. For a new benchmark or real project, add an adapter to the registry.

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) ·
[Apache-2.0 License](LICENSE)
