# Optional Local Asset Libraries

This directory is intentionally payload-free in the public source tree.
GameLoop accepts caller-provided, read-only asset libraries; generated or
copied asset payloads are ignored by Git and are never part of a release.

Current expected layout:

```text
assets/
  library/
  library-oga/
```

For the optional GameCraft-Bench adapter, refresh from an external checkout:

```bash
./scripts/sync-assets
```

The default source for that adapter is:

```text
$GAMELOOP_BENCH/assets
```

Runtime environment variables in `.env` point GameCraft-Bench to these local
directories through `GAMECRAFT_BENCH_ASSET_LIBRARY` and
`GAMECRAFT_BENCH_OGA_LIBRARY`.
