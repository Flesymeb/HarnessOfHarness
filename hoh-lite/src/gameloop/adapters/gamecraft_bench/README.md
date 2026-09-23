# GameCraft-Bench adapter

This directory is the optional GameCraft-Bench integration for HoH-lite.
It owns only the benchmark-facing concerns:

- task/workspace resolution and the upstream compatibility contract;
- benchmark wrapper and verifier invocation;
- GameCraft-specific prompt templates and result summaries;
- compatibility entry points used by older integrations.

The benchmark checkout itself is external and read-only. Generic orchestration,
the three roles, Harness Runtime, domain policies, local asset roots, and Godot
MCP tools live outside this directory under `gameloop.core`,
`gameloop.harnesses`, and `gameloop.tools`.

To add another benchmark, implement `BenchmarkAdapter` in a new sibling under
`gameloop.adapters` and register it without importing GameCraft-specific code
into Core. The `gameloop.adapters.gamecraft` package is a deprecated import
alias kept temporarily for existing integrations; it contains no second
implementation.
