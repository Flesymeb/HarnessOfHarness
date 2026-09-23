import { afterEach, describe, expect, it } from 'vitest';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { compareVersions, installAddon } from '../../installer/install.js';

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe('compareVersions', () => {
  it('returns 0 for equal versions', () => {
    expect(compareVersions('1.0.0', '1.0.0')).toBe(0);
    expect(compareVersions('2.12.0', '2.12.0')).toBe(0);
    expect(compareVersions('0.0.1', '0.0.1')).toBe(0);
  });

  it('returns 1 when first version is greater', () => {
    expect(compareVersions('2.0.0', '1.0.0')).toBe(1);
    expect(compareVersions('1.1.0', '1.0.0')).toBe(1);
    expect(compareVersions('1.0.1', '1.0.0')).toBe(1);
    expect(compareVersions('2.12.0', '2.6.1')).toBe(1);
    expect(compareVersions('10.0.0', '9.0.0')).toBe(1);
  });

  it('returns -1 when first version is lesser', () => {
    expect(compareVersions('1.0.0', '2.0.0')).toBe(-1);
    expect(compareVersions('1.0.0', '1.1.0')).toBe(-1);
    expect(compareVersions('1.0.0', '1.0.1')).toBe(-1);
    expect(compareVersions('2.6.1', '2.12.0')).toBe(-1);
    expect(compareVersions('9.0.0', '10.0.0')).toBe(-1);
  });

  it('handles versions with different segment counts', () => {
    expect(compareVersions('1.0', '1.0.0')).toBe(0);
    expect(compareVersions('1.0.0', '1.0')).toBe(0);
    expect(compareVersions('1.0', '1.0.1')).toBe(-1);
    expect(compareVersions('1.0.1', '1.0')).toBe(1);
    expect(compareVersions('2', '1.9.9')).toBe(1);
  });

  it('correctly handles the reported bug case (2.12.0 vs 2.6.1)', () => {
    expect(compareVersions('2.12.0', '2.6.1')).toBe(1);
    expect(compareVersions('2.6.1', '2.12.0')).toBe(-1);
  });

  it('handles edge cases', () => {
    expect(compareVersions('0.0.0', '0.0.0')).toBe(0);
    expect(compareVersions('0.0.1', '0.0.0')).toBe(1);
    expect(compareVersions('0.1.0', '0.0.9')).toBe(1);
  });
});

describe('installAddon force refresh', () => {
  it('replaces drift even when plugin versions are equal', async () => {
    const root = mkdtempSync(join(tmpdir(), 'godot-mcp-install-'));
    roots.push(root);
    writeFileSync(join(root, 'project.godot'), '[application]\nconfig/name="Test"\n');

    const here = dirname(fileURLToPath(import.meta.url));
    const bundled = join(here, '..', '..', '..', 'addon');
    const target = join(root, 'addons', 'godot_mcp');
    cpSync(bundled, target, { recursive: true });
    const bridge = join(target, 'game_bridge', 'mcp_game_bridge.gd');
    writeFileSync(bridge, '# stale same-version bridge\n');

    const skipped = await installAddon(root);
    expect(skipped.skipped).toBe(true);
    expect(readFileSync(bridge, 'utf-8')).toContain('stale same-version');

    const refreshed = await installAddon(root, { force: true });
    expect(refreshed.success).toBe(true);
    expect(refreshed.skipped).not.toBe(true);
    expect(refreshed.message).toContain('Reinstalled addon version');
    expect(readFileSync(bridge, 'utf-8')).not.toContain('stale same-version');
  });
});
