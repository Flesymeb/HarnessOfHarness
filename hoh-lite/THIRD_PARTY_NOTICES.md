# Third-party notices

HoH-lite itself is distributed under the Apache License, Version 2.0;
see the top-level `LICENSE` and `NOTICE` files. The notices below apply only to
third-party components and do not change the license of HoH-lite code.

HoH-lite vendors `satelliteoflove/godot-mcp` at the commit recorded in
`src/gameloop/_vendor/godot-mcp.lock.json`. The upstream project is licensed
under the MIT License, retained in
`src/gameloop/_vendor/godot_mcp/LICENSE`. The complete patched source is
included under `src/gameloop/_vendor/godot_mcp/`; dependency and build directories
remain excluded from source control.

The `src/gameloop/_vendor/godot-mcp-gameloop.patch` HoH-lite overlay adds runtime-QA capability
boundaries, reliable screenshots and runtime diagnostics, bounded input/time
control, UI/skeleton inspection, connection hardening, and per-process Godot
port selection. It does not include private game assets, task policies,
benchmark results, or demo product code.
