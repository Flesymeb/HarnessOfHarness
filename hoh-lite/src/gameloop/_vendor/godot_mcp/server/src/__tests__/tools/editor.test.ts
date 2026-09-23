import { describe, it, expect, beforeEach } from 'vitest';
import { createMockGodot, createToolContext, MockGodotConnection, structuredOf } from '../helpers/mock-godot.js';
import { editorRead, editorEdit, runtimeEditorEdit } from '../../tools/editor.js';
import { isStructuredMultiContentResult } from '../../core/structured.js';

describe('editorRead tool', () => {
  let mock: MockGodotConnection;

  beforeEach(() => {
    mock = createMockGodot();
  });

  describe('schema validation', () => {
    it('rejects actions that belong to godot_editor_edit', () => {
      expect(editorRead.schema.safeParse({ action: 'select', node_path: '/root/Test' }).success).toBe(false);
      expect(editorRead.schema.safeParse({ action: 'run' }).success).toBe(false);
      expect(editorRead.schema.safeParse({ action: 'set_viewport_2d', zoom: 2.0 }).success).toBe(false);
    });

    it('accepts its own read actions', () => {
      expect(editorRead.schema.safeParse({ action: 'get_state' }).success).toBe(true);
      expect(editorRead.schema.safeParse({ action: 'get_runtime_log_messages' }).success).toBe(true);
      expect(editorRead.schema.safeParse({ action: 'screenshot_game' }).success).toBe(true);
    });
  });

  describe('get_state', () => {
    it('returns JSON with editor state including camera and viewport info', async () => {
      const state = {
        current_scene: 'res://main.tscn',
        is_playing: false,
        godot_version: '4.5',
        open_scenes: ['res://main.tscn', 'res://player.tscn'],
        main_screen: '2D',
        camera: { position: { x: 0, y: 0, z: 10 } },
        viewport_2d: { center: { x: 0, y: 0 }, zoom: 1.0 },
      };
      mock.mockResponse(state);
      const ctx = createToolContext(mock);

      const result = await editorRead.execute({ action: 'get_state' }, ctx);

      expect(structuredOf(result)).toEqual(state);
    });
  });

  describe('get_selection', () => {
    it('returns formatted list or empty message', async () => {
      mock.mockResponse({ selected: [] });
      const ctx = createToolContext(mock);
      expect(await editorRead.execute({ action: 'get_selection' }, ctx)).toBe('No nodes selected');

      mock.mockResponse({ selected: ['/root/Main/Player', '/root/Main/Enemy'] });
      const result = await editorRead.execute({ action: 'get_selection' }, ctx);
      expect(result).toContain('Selected nodes:');
      expect(result).toContain('/root/Main/Player');
    });
  });

  describe('get_log_messages', () => {
    it('returns the cursor even when empty, so a first check can start polling', async () => {
      const ctx = createToolContext(mock);
      mock.mockResponse({ total_count: 0, match_count: 0, returned_count: 0, cursor: 0, messages: [] });
      expect(await editorRead.execute({ action: 'get_log_messages' }, ctx)).toBe('No messages (cursor 0).');
    });

    it('returns JSON with messages when present', async () => {
      const ctx = createToolContext(mock);
      const responseData = {
        total_count: 2,
        returned_count: 2,
        messages: [
          { timestamp: 12345, type: 'Parser Error', message: 'Could not find type', file: 'res://test.gd', line: 10, error_type: 0, frames: [] },
          { timestamp: 12346, type: 'Script Error', message: 'Type mismatch', file: 'res://test.gd', line: 15, error_type: 2, frames: [] },
        ],
      };
      mock.mockResponse(responseData);
      const result = await editorRead.execute({ action: 'get_log_messages' }, ctx);
      expect(structuredOf(result)).toEqual(responseData);
    });

    it('passes limit param to Godot', async () => {
      const ctx = createToolContext(mock);
      mock.mockResponse({ total_count: 0, returned_count: 0, messages: [] });
      await editorRead.execute({ action: 'get_log_messages', limit: 10 }, ctx);
      expect(mock.calls[0].params.limit).toBe(10);
    });

    it('defaults severity to "all" and since to 0', async () => {
      const ctx = createToolContext(mock);
      mock.mockResponse({ total_count: 0, match_count: 0, returned_count: 0, cursor: 0, messages: [] });
      await editorRead.execute({ action: 'get_log_messages' }, ctx);
      expect(mock.calls[0].params.severity).toBe('all');
      expect(mock.calls[0].params.since).toBe(0);
    });

    it('passes severity and since filters through to Godot', async () => {
      const ctx = createToolContext(mock);
      mock.mockResponse({ total_count: 5, match_count: 0, returned_count: 0, cursor: 5, messages: [] });
      await editorRead.execute({ action: 'get_log_messages', severity: 'error', since: 3 }, ctx);
      expect(mock.calls[0].params.severity).toBe('error');
      expect(mock.calls[0].params.since).toBe(3);
    });

    it('surfaces cursor and match_count in the structured response', async () => {
      const ctx = createToolContext(mock);
      const responseData = {
        total_count: 7,
        match_count: 2,
        returned_count: 2,
        cursor: 7,
        messages: [
          { timestamp: 1, type: 'Error', message: 'boom', file: 'res://a.gd', line: 1, error_type: 0, frames: [] },
          { timestamp: 2, type: 'Error', message: 'bang', file: 'res://b.gd', line: 2, error_type: 0, frames: [] },
        ],
      };
      mock.mockResponse(responseData);
      const result = await editorRead.execute({ action: 'get_log_messages', severity: 'error' }, ctx);
      expect(structuredOf(result)).toEqual(responseData);
    });

    it('reports "no new messages" with the cursor when reading incrementally and nothing matched', async () => {
      const ctx = createToolContext(mock);
      mock.mockResponse({ total_count: 4, match_count: 0, returned_count: 0, cursor: 4, messages: [] });
      const result = await editorRead.execute({ action: 'get_log_messages', since: 4 }, ctx);
      expect(result).toBe('No new messages since cursor 4.');
    });

    it('names the severity in the "no new messages" reply when filtering', async () => {
      const ctx = createToolContext(mock);
      mock.mockResponse({ total_count: 4, match_count: 0, returned_count: 0, cursor: 4, messages: [] });
      const result = await editorRead.execute({ action: 'get_log_messages', since: 4, severity: 'error' }, ctx);
      expect(result).toBe('No new error messages since cursor 4.');
    });

    it('surfaces a stale-project advisory alongside the messages when the addon flags it (#245)', async () => {
      const ctx = createToolContext(mock);
      const staleness = {
        stale: true,
        summary: 'project.godot was edited on disk after the editor loaded it: 1 autoload(s) added on disk (FX). Run `godot_editor_edit restart` to reload.',
        autoload: { added: ['FX'], removed: [], changed: [] },
        input: { added: [] },
      };
      mock.mockResponse({
        total_count: 1, match_count: 1, returned_count: 1, cursor: 1,
        messages: [{ timestamp: 1, type: 'Parser Error', message: 'Identifier not found: FX', file: 'res://a.gd', line: 1, error_type: 0, frames: [] }],
        staleness,
      });
      const result = await editorRead.execute({ action: 'get_log_messages' }, ctx);
      const structured = structuredOf(result);
      expect(structured.advisory).toContain('STALE PROJECT SETTINGS:');
      expect(structured.advisory).toContain('godot_editor_edit restart');
      expect(structured.staleness).toEqual(staleness);
    });

    it('appends the stale-project advisory even when no log lines matched', async () => {
      const ctx = createToolContext(mock);
      mock.mockResponse({
        total_count: 0, match_count: 0, returned_count: 0, cursor: 3, messages: [],
        staleness: { stale: true, summary: 'autoload FX added on disk.' },
      });
      const result = await editorRead.execute({ action: 'get_log_messages', since: 3 }, ctx);
      expect(result).toContain('No new messages since cursor 3.');
      expect(result).toContain('STALE PROJECT SETTINGS:');
    });

    it('adds nothing when the addon reports the project is not stale', async () => {
      const ctx = createToolContext(mock);
      const responseData = { total_count: 0, match_count: 0, returned_count: 0, cursor: 0, messages: [], staleness: { stale: false } };
      mock.mockResponse(responseData);
      const result = await editorRead.execute({ action: 'get_log_messages' }, ctx);
      expect(result).toBe('No messages (cursor 0).');
    });
  });

  describe('get_stack_trace', () => {
    it('returns "No stack trace available" when empty, JSON when present', async () => {
      const ctx = createToolContext(mock);

      mock.mockResponse({ error: '', error_type: '', file: '', line: 0, frames: [] });
      expect(await editorRead.execute({ action: 'get_stack_trace' }, ctx)).toBe('No stack trace available');

      const stackData = {
        error: 'Null instance',
        error_type: 'Runtime Error',
        file: 'res://player.gd',
        line: 42,
        frames: [{ file: 'res://player.gd', line: 42, function: '_process' }],
      };
      mock.mockResponse(stackData);
      const result = await editorRead.execute({ action: 'get_stack_trace' }, ctx);
      expect(structuredOf(result)).toEqual(stackData);
    });
  });

  describe('get_runtime_log_messages', () => {
    it('returns a compact empty message when the game produced no diagnostics', async () => {
      const ctx = createToolContext(mock);
      mock.mockResponse({ count: 0, total_count: 0, break_reason: '', messages: [] });
      expect(await editorRead.execute({ action: 'get_runtime_log_messages' }, ctx)).toBe(
        'No runtime game messages captured.'
      );
      expect(mock.calls[0]).toMatchObject({
        command: 'get_runtime_log_messages',
        params: { limit: 50 },
      });
    });

    it('returns candidate runtime errors and forwards the bounded limit', async () => {
      const ctx = createToolContext(mock);
      const responseData = {
        count: 1,
        total_count: 1,
        break_reason: 'Invalid access to property on null instance',
        messages: [
          {
            category: 'stderr',
            message: 'Invalid access to property on null instance',
            file: 'res://scripts/player.gd',
            line: 42,
            function: '_ready',
          },
        ],
      };
      mock.mockResponse(responseData);
      const result = await editorRead.execute(
        { action: 'get_runtime_log_messages', limit: 12 },
        ctx
      );
      expect(structuredOf(result)).toEqual(responseData);
      expect(mock.calls[0].params.limit).toBe(12);
    });
  });

  describe('screenshots', () => {
    it('returns a compact preview while retaining lossless evidence', async () => {
      const base64 = 'iVBORw0KGgoAAAANSUhEUg==';
      mock.mockResponse({
        image_base64: base64,
        preview_image_base64: 'JPEG',
        preview_mime_type: 'image/jpeg',
        width: 800,
        height: 600,
      });
      const ctx = createToolContext(mock);

      const result = await editorRead.execute({ action: 'screenshot_game' }, ctx);
      expect(isStructuredMultiContentResult(result)).toBe(true);
      if (!isStructuredMultiContentResult(result)) throw new Error('expected structured multi-content');
      expect(result.content).toEqual([{ type: 'image', data: 'JPEG', mimeType: 'image/jpeg' }]);
      expect(result.evidenceContent).toEqual([{ type: 'image', data: base64, mimeType: 'image/png' }]);
    });

    it('appends a mesh-integrity advisory when warnings ride the screenshot response', async () => {
      const base64 = 'iVBORw0KGgoAAAANSUhEUg==';
      mock.mockResponse({
        image_base64: base64,
        width: 800,
        height: 600,
        mesh_warnings: ['Floor surf 0: 66% of vertices unreferenced — dropped triangles'],
      });
      const ctx = createToolContext(mock);

      const result = await editorRead.execute({ action: 'screenshot_game' }, ctx);
      expect(isStructuredMultiContentResult(result)).toBe(true);
      if (!isStructuredMultiContentResult(result)) throw new Error('expected structured multi-content');
      const blocks = result.content;
      expect(blocks[0]).toEqual({ type: 'image', data: base64, mimeType: 'image/png' });
      expect(blocks[1].type).toBe('text');
      if (blocks[1].type !== 'text') throw new Error('expected warning text');
      expect(blocks[1].text).toContain('Mesh integrity');
      expect(blocks[1].text).toContain('godot_validate_meshes');
    });

    it('falls back to the PNG when an older addon supplies no preview', async () => {
      mock.mockResponse({ image_base64: 'abc', width: 8, height: 8, mesh_warnings: [] });
      const ctx = createToolContext(mock);

      const result = await editorRead.execute({ action: 'screenshot_game' }, ctx);
      expect(isStructuredMultiContentResult(result)).toBe(true);
      if (!isStructuredMultiContentResult(result)) throw new Error('expected structured multi-content');
      expect(result.content).toEqual([{ type: 'image', data: 'abc', mimeType: 'image/png' }]);
    });

    it('passes viewport and max_width params for editor screenshot', async () => {
      mock.mockResponse({ image_base64: 'abc', width: 800, height: 600 });
      const ctx = createToolContext(mock);

      await editorRead.execute({ action: 'screenshot_editor', viewport: '2d', max_width: 800 }, ctx);
      expect(mock.calls[0].params.viewport).toBe('2d');
      expect(mock.calls[0].params.max_width).toBe(800);
    });

    it('propagates errors from Godot', async () => {
      mock.mockError(new Error('Game is not running'));
      const ctx = createToolContext(mock);

      await expect(editorRead.execute({ action: 'screenshot_game' }, ctx))
        .rejects.toThrow('Game is not running');
    });
  });
});

describe('editorEdit tool', () => {
  let mock: MockGodotConnection;

  beforeEach(() => {
    mock = createMockGodot();
  });

  describe('schema validation', () => {
    it('rejects actions that belong to godot_editor_read', () => {
      expect(editorEdit.schema.safeParse({ action: 'get_state' }).success).toBe(false);
      expect(editorEdit.schema.safeParse({ action: 'get_log_messages' }).success).toBe(false);
      expect(editorEdit.schema.safeParse({ action: 'screenshot_game' }).success).toBe(false);
    });

    it('requires node_path for select action', () => {
      expect(editorEdit.schema.safeParse({ action: 'select' }).success).toBe(false);
      expect(editorEdit.schema.safeParse({ action: 'select', node_path: '/root/Test' }).success).toBe(true);
    });

    it('requires at least one param for set_viewport_2d', () => {
      expect(editorEdit.schema.safeParse({ action: 'set_viewport_2d' }).success).toBe(false);
      expect(editorEdit.schema.safeParse({ action: 'set_viewport_2d', zoom: 2.0 }).success).toBe(true);
    });

    it('accepts only project-local existing-scene syntax for inspect_scene_3d', () => {
      expect(editorEdit.schema.safeParse({
        action: 'inspect_scene_3d',
        scene_path: 'res://levels/arena.tscn',
        node_path: '/root/Arena/Player',
      }).success).toBe(true);
      for (const scenePath of [
        '/tmp/arena.tscn',
        'res://../outside.tscn',
        'res://levels/arena.gd',
      ]) {
        expect(editorEdit.schema.safeParse({
          action: 'inspect_scene_3d',
          scene_path: scenePath,
          node_path: '/root/Arena/Player',
        }).success, scenePath).toBe(false);
      }
    });
  });

  describe('select', () => {
    it('sends select_node and confirms', async () => {
      mock.mockResponse({});
      const ctx = createToolContext(mock);

      const result = await editorEdit.execute({ action: 'select', node_path: '/root/Main/Player' }, ctx);

      expect(mock.calls[0].command).toBe('select_node');
      expect(mock.calls[0].params.node_path).toBe('/root/Main/Player');
      expect(result).toBe('Selected node: /root/Main/Player');
    });
  });

  describe('run/stop', () => {
    it('returns appropriate confirmations', async () => {
      mock.mockResponse({});
      const ctx = createToolContext(mock);

      expect(await editorEdit.execute({ action: 'run' }, ctx)).toBe('Running project');
      expect(await editorEdit.execute({ action: 'run', scene_path: 'res://test.tscn' }, ctx))
        .toBe('Running scene: res://test.tscn');
      expect(await editorEdit.execute({ action: 'stop' }, ctx)).toBe('Stopped project');
    });

    it('passes frozen through to run_project and says so', async () => {
      mock.mockResponse({});
      const ctx = createToolContext(mock);

      const result = await editorEdit.execute({ action: 'run', frozen: true }, ctx);
      expect(result).toContain('frozen from frame 0');
      expect(mock.calls[0].command).toBe('run_project');
      expect(mock.calls[0].params.frozen).toBe(true);
    });

    it('gives run enough socket headroom for typed addon readiness errors', async () => {
      mock.mockResponse({});
      const ctx = createToolContext(mock);

      await editorEdit.execute({ action: 'run' }, ctx);

      expect(mock.calls[0].opts).toEqual({ timeoutMs: 65_000 });
    });
  });

  describe('restart', () => {
    it('sends restart_editor with save=true by default and confirms reconnect', async () => {
      mock.mockResponse({ restarting: true, save: true });
      const ctx = createToolContext(mock);

      const result = await editorEdit.execute({ action: 'restart' }, ctx);

      expect(mock.calls[0].command).toBe('restart_editor');
      expect(mock.calls[0].params.save).toBe(true);
      expect(result).toContain('restarting');
      expect(result).toContain('reconnect');
    });

    it('passes save=false through and says it will not save', async () => {
      mock.mockResponse({ restarting: true, save: false });
      const ctx = createToolContext(mock);

      const result = await editorEdit.execute({ action: 'restart', save: false }, ctx);

      expect(mock.calls[0].params.save).toBe(false);
      expect(result).toContain('without saving');
    });

    it('treats a dropped connection as success (fire-and-forget)', async () => {
      // The editor tears the bridge down as it restarts; sendCommand rejects
      // with "Connection closed" mid-flight. That is the expected success path.
      mock.mockError(new Error('Connection closed'));
      const ctx = createToolContext(mock);

      const result = await editorEdit.execute({ action: 'restart' }, ctx);
      expect(result).toContain('restarting');
    });

    it('rethrows a real error (e.g. command unknown to an older addon)', async () => {
      mock.mockError(new Error('Unknown command: restart_editor'));
      const ctx = createToolContext(mock);

      await expect(editorEdit.execute({ action: 'restart' }, ctx)).rejects.toThrow('Unknown command');
    });
  });

  describe('set_viewport_2d', () => {
    it('returns formatted confirmation with actual values', async () => {
      mock.mockResponse({ center: { x: 100.5, y: 200.5 }, zoom: 2.5 });
      const ctx = createToolContext(mock);

      const result = await editorEdit.execute({
        action: 'set_viewport_2d',
        center_x: 100,
        center_y: 200,
        zoom: 2.5,
      }, ctx);

      expect(result).toContain('100.5');
      expect(result).toContain('200.5');
      expect(result).toContain('2.50');
    });

    it('forwards only the params the caller set, so the addon preserves omitted axes', async () => {
      // A zoom-only call must NOT send center_x/center_y; otherwise the addon
      // can't tell "keep current center" from "recenter on 0,0" (#316).
      mock.mockResponse({ center: { x: 42, y: 99 }, zoom: 3 });
      const ctx = createToolContext(mock);

      await editorEdit.execute({ action: 'set_viewport_2d', zoom: 3 }, ctx);

      expect(mock.calls[0].command).toBe('set_2d_viewport');
      expect(mock.calls[0].params).toEqual({ zoom: 3 });
      expect('center_x' in mock.calls[0].params).toBe(false);
      expect('center_y' in mock.calls[0].params).toBe(false);
    });
  });

  describe('inspect_scene_3d', () => {
    it('uses one atomic bridge command and returns labelled image plus structured framing metadata', async () => {
      mock.mockResponse({
        image_base64: 'AAAA',
        width: 900,
        height: 506,
        scene_path: 'res://levels/arena.tscn',
        node_path: '/root/Arena/Player',
        node_type: 'CharacterBody3D',
        framing: {
          center: { x: 1, y: 2, z: 3 },
          distance: 6.5,
          projection: 'perspective',
          geometry_count: 2,
          used_fallback_bounds: false,
          bounds: {
            position: { x: 0, y: 0, z: 0 },
            size: { x: 2, y: 4, z: 2 },
            end: { x: 2, y: 4, z: 2 },
          },
        },
      });
      const ctx = createToolContext(mock);

      const result = await editorEdit.execute({
        action: 'inspect_scene_3d',
        scene_path: 'res://levels/arena.tscn',
        node_path: '/root/Arena/Player',
        max_width: 900,
      }, ctx);

      expect(mock.calls).toEqual([{
        command: 'inspect_scene_3d',
        params: {
          scene_path: 'res://levels/arena.tscn',
          node_path: '/root/Arena/Player',
          max_width: 900,
        },
        opts: undefined,
      }]);
      expect(result).toMatchObject({
        content: [
          { type: 'text' },
          { type: 'image', data: 'AAAA', mimeType: 'image/png' },
        ],
        structuredContent: {
          scene_path: 'res://levels/arena.tscn',
          node_path: '/root/Arena/Player',
          screenshot: { width: 900, height: 506 },
        },
      });
      expect(JSON.stringify((result as { structuredContent: unknown }).structuredContent))
        .not.toContain('AAAA');
    });
  });
});

describe('runtimeEditorEdit handler boundary', () => {
  it('exposes atomic 3D inspection but rejects mutation actions even when called directly', async () => {
    expect(runtimeEditorEdit.schema.safeParse({
      action: 'inspect_scene_3d',
      scene_path: 'res://main.tscn',
      node_path: '/root/Main',
    }).success).toBe(true);

    const mock = createMockGodot();
    const ctx = createToolContext(mock);
    for (const action of ['restart', 'save', 'reload', 'set_viewport_2d', 'select']) {
      await expect(runtimeEditorEdit.execute({ action } as never, ctx))
        .rejects.toThrow(/Runtime editor control rejects action/);
    }
    expect(mock.calls).toHaveLength(0);
  });
});
