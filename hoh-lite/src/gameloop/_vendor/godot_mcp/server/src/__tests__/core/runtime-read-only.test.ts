import { beforeAll, describe, expect, it } from 'vitest';
import { registry } from '../../core/registry.js';
import { runtimeEditorEdit } from '../../tools/editor.js';
import { registerAllTools } from '../../tools/index.js';
import { createMockGodot, createToolContext } from '../helpers/mock-godot.js';

// This file owns one isolated registry configured exactly like
// --read-only-runtime. It verifies the capability boundary before any Godot
// bridge command is dispatched.
describe('runtime read-only mode', () => {
  beforeAll(() => {
    registerAllTools({ runtimeReadOnly: true });
  });

  it('publishes only bounded runtime control and atomic 3D inspection', () => {
    expect(runtimeEditorEdit.schema.safeParse({ action: 'run' }).success).toBe(true);
    expect(runtimeEditorEdit.schema.safeParse({ action: 'stop' }).success).toBe(true);
    expect(runtimeEditorEdit.schema.safeParse({
      action: 'inspect_scene_3d',
      scene_path: 'res://levels/arena.tscn',
      node_path: '/root/Arena/Player',
    }).success).toBe(true);
    for (const action of ['select', 'restart', 'save', 'reload', 'set_viewport_2d']) {
      expect(runtimeEditorEdit.schema.safeParse({ action }).success, action).toBe(false);
    }
  });

  it('retains bounded runtime controls without labelling mutations read-only', () => {
    const tools = new Map(registry.getToolList().map((tool) => [tool.name, tool]));
    expect(tools.size).toBe(15);
    for (const name of ['godot_editor_edit', 'godot_input', 'godot_game_time']) {
      expect(tools.has(name), name).toBe(true);
      expect(tools.get(name)?.annotations?.readOnlyHint, name).toBe(false);
      expect(tools.get(name)?.annotations?.destructiveHint, name).toBe(false);
    }
    expect(tools.get('godot_editor_edit')?.annotations?.idempotentHint).toBe(true);
    expect(tools.has('godot_exec')).toBe(false);
  });

  it('rejects disallowed editor actions before calling the bridge', async () => {
    const mock = createMockGodot();
    const ctx = createToolContext(mock);

    await expect(
      registry.executeTool('godot_editor_edit', { action: 'restart' }, ctx)
    ).rejects.toThrow(/unknown action "restart".*Valid actions: run, stop, inspect_scene_3d/s);
    expect(mock.calls).toHaveLength(0);
  });

  it('does not register the scene handler, so save and reload cannot reach Godot', async () => {
    const mock = createMockGodot();
    const ctx = createToolContext(mock);

    for (const action of ['open', 'save', 'reload']) {
      await expect(
        registry.executeTool('godot_scene', { action, scene_path: 'res://main.tscn' }, ctx)
      ).rejects.toThrow('Unknown tool: godot_scene');
    }
    expect(mock.calls).toHaveLength(0);
  });

  it('dispatches inspection as one bounded command with no save or reload calls', async () => {
    const mock = createMockGodot();
    mock.mockResponse({
      image_base64: 'AAAA',
      width: 640,
      height: 360,
      scene_path: 'res://main.tscn',
      node_path: '/root/Main/Target',
      node_type: 'MeshInstance3D',
      framing: {
        center: { x: 0, y: 0, z: 0 },
        distance: 4,
        projection: 'perspective',
        geometry_count: 1,
        used_fallback_bounds: false,
      },
    });
    const ctx = createToolContext(mock);

    await registry.executeTool('godot_editor_edit', {
      action: 'inspect_scene_3d',
      scene_path: 'res://main.tscn',
      node_path: '/root/Main/Target',
      max_width: 640,
    }, ctx);

    expect(mock.calls.map((call) => call.command)).toEqual(['inspect_scene_3d']);
  });
});
