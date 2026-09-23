# Contributing to HoH-lite

Issues and pull requests are welcome in
[HarnessOfHarness](https://github.com/Flesymeb/HarnessOfHarness). Please keep
changes scoped to `hoh-lite/` and describe the behavior changed, the harness
and Godot versions used, and how you tested it.

## Local checks

From `hoh-lite/`:

```bash
python3 -m pip install -e /absolute/path/to/gamecraft-bench
python3 -m pip install -e '.[gamecraft-bench]'
python3 -m compileall -q src/gameloop
gameloop-gamecraft-doctor --bench /absolute/path/to/gamecraft-bench
```

Use an unmodified external benchmark checkout for adapter changes and describe
how you verified the behavior. Do not commit credentials, task copies, game
assets, generated candidates, runs, or logs. Redact local paths and tokens from
issue reports.

Contributions submitted for inclusion are licensed under the project's
[Apache-2.0 license](LICENSE), as described in its contribution terms.
