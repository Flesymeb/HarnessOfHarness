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

Choose another profile in `configs/harnesses/` to use a different harness or
model. For a new benchmark or real project, add an adapter to the registry.

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) ·
[Apache-2.0 License](LICENSE)
