import { describe, it, expect, beforeEach } from 'vitest';
import { createMockGodot, createToolContext, MockGodotConnection, structuredOf } from '../helpers/mock-godot.js';
import { nodeRead, nodeEdit } from '../../tools/node.js';

describe('node read tool', () => {
  let mock: MockGodotConnection;

  beforeEach(() => {
    mock = createMockGodot();
  });

  describe('schema validation', () => {
    it('requires node_path for get_properties', () => {
      expect(nodeRead.schema.safeParse({ action: 'get_properties' }).success).toBe(false);
      expect(nodeRead.schema.safeParse({
        action: 'get_properties',
        node_path: '/root/Test',
      }).success).toBe(true);
    });

    it('get_scene_tree accepts optional max_depth / max_children caps', () => {
      expect(nodeRead.schema.safeParse({ action: 'get_scene_tree' }).success).toBe(true);
      expect(nodeRead.schema.safeParse({ action: 'get_scene_tree', max_depth: 3 }).success).toBe(true);
      expect(nodeRead.schema.safeParse({ action: 'get_scene_tree', max_children: 10 }).success).toBe(true);
      // Caps must be positive integers, not zero or fractional.
      expect(nodeRead.schema.safeParse({ action: 'get_scene_tree', max_depth: 0 }).success).toBe(false);
      expect(nodeRead.schema.safeParse({ action: 'get_scene_tree', max_depth: 1.5 }).success).toBe(false);
    });

    it('find requires name_pattern and/or type', () => {
      expect(nodeRead.schema.safeParse({ action: 'find' }).success).toBe(false);
      expect(nodeRead.schema.safeParse({ action: 'find', name_pattern: '*Spawner*' }).success).toBe(true);
      expect(nodeRead.schema.safeParse({ action: 'find', type: 'Area2D' }).success).toBe(true);
    });

    it('inspect_ui bounds depth and node count', () => {
      expect(nodeRead.schema.safeParse({ action: 'inspect_ui' }).success).toBe(true);
      expect(nodeRead.schema.safeParse({ action: 'inspect_ui', max_depth: 0 }).success).toBe(false);
      expect(nodeRead.schema.safeParse({ action: 'inspect_ui', max_nodes: 513 }).success).toBe(false);
      expect(nodeRead.schema.safeParse({
        action: 'inspect_ui',
        root_path: '/root/Main/HUD',
        max_depth: 6,
        max_nodes: 80,
      }).success).toBe(true);
    });

    it('inspect_skeleton requires an exact path and bounds bones', () => {
      expect(nodeRead.schema.safeParse({ action: 'inspect_skeleton' }).success).toBe(false);
      expect(nodeRead.schema.safeParse({
        action: 'inspect_skeleton',
        node_path: '/root/Main/Rig/Skeleton3D',
      }).success).toBe(true);
      expect(nodeRead.schema.safeParse({
        action: 'inspect_skeleton',
        node_path: '/root/Main/Rig/Skeleton3D',
        max_bones: 513,
      }).success).toBe(false);
    });

    it('rejects the removed create/delete/script/signal actions', () => {
      expect(nodeRead.schema.safeParse({
        action: 'create',
        parent_path: '/root',
        node_type: 'Node2D',
        node_name: 'Test',
      }).success).toBe(false);
      expect(nodeRead.schema.safeParse({
        action: 'delete',
        node_path: '/root/Obsolete',
      }).success).toBe(false);
      expect(nodeRead.schema.safeParse({
        action: 'attach_script',
        node_path: '/root/Test',
        script_path: 'res://test.gd',
      }).success).toBe(false);
      expect(nodeRead.schema.safeParse({
        action: 'connect_signal',
        node_path: '/root/Button',
        signal_name: 'pressed',
        target_path: '/root/Main',
        method_name: '_on_pressed',
      }).success).toBe(false);
    });

    it('rejects edit actions belonging to godot_node_edit', () => {
      expect(nodeRead.schema.safeParse({
        action: 'update',
        node_path: '/root/Test',
        properties: { visible: false },
      }).success).toBe(false);
      expect(nodeRead.schema.safeParse({
        action: 'reparent',
        node_path: '/root/Test',
        new_parent_path: '/root/New',
      }).success).toBe(false);
    });
  });

  describe('get_properties', () => {
    it('returns formatted JSON properties', async () => {
      const properties = { position: { x: 100, y: 200 }, visible: true };
      mock.mockResponse({ properties });
      const ctx = createToolContext(mock);

      const result = await nodeRead.execute({ action: 'get_properties', node_path: '/root/Player' }, ctx);
      expect(structuredOf(result)).toEqual(properties);
      expect(mock.calls[0]).toMatchObject({
        command: 'get_node_properties',
        params: { node_path: '/root/Player' },
      });
    });
  });

  describe('get_scene_tree', () => {
    it('returns the full tree from the editor', async () => {
      const tree = {
        name: 'Main',
        type: 'Node2D',
        children: [{ name: 'Player', type: 'CharacterBody2D' }],
      };
      mock.mockResponse({ tree });
      const ctx = createToolContext(mock);

      const result = await nodeRead.execute({ action: 'get_scene_tree' }, ctx);
      expect(structuredOf(result)).toEqual(tree);
      expect(mock.calls[0].command).toBe('get_scene_tree');
    });

    it('forwards max_depth / max_children caps to the addon', async () => {
      mock.mockResponse({ tree: { name: 'Main', type: 'Node2D', truncated_children: 5 } });
      const ctx = createToolContext(mock);

      await nodeRead.execute({ action: 'get_scene_tree', max_depth: 2, max_children: 10 }, ctx);

      expect(mock.calls[0].command).toBe('get_scene_tree');
      expect(mock.calls[0].params.max_depth).toBe(2);
      expect(mock.calls[0].params.max_children).toBe(10);
    });
  });

  describe('inspect_ui', () => {
    it('returns structured layout and input risks', async () => {
      const inspection = {
        control_count: 1,
        input_risks: [{ path: '/root/Main/HUD', risk: 'full_viewport_stop' }],
      };
      mock.mockResponse({ inspection });
      const ctx = createToolContext(mock);

      const result = await nodeRead.execute({
        action: 'inspect_ui',
        root_path: '/root/Main/HUD',
        max_depth: 8,
        max_nodes: 100,
      }, ctx);

      expect(structuredOf(result)).toEqual(inspection);
      expect(mock.calls[0]).toMatchObject({
        command: 'inspect_ui',
        params: {
          root_path: '/root/Main/HUD',
          max_depth: 8,
          max_nodes: 100,
        },
      });
    });
  });

  describe('inspect_skeleton', () => {
    it('returns structured bones, bindings and animation drivers', async () => {
      const inspection = {
        bone_count: 2,
        bones: [{ index: 0, name: 'Root' }, { index: 1, name: 'Hand.R' }],
        bone_attachments: [{ path: '/root/Main/Rig/Skeleton3D/Grip', bone_name: 'Hand.R' }],
      };
      mock.mockResponse({ inspection });
      const ctx = createToolContext(mock);

      const result = await nodeRead.execute({
        action: 'inspect_skeleton',
        node_path: '/root/Main/Rig/Skeleton3D',
        max_bones: 64,
      }, ctx);

      expect(structuredOf(result)).toEqual(inspection);
      expect(mock.calls[0]).toMatchObject({
        command: 'inspect_skeleton',
        params: {
          node_path: '/root/Main/Rig/Skeleton3D',
          max_bones: 64,
        },
      });
    });
  });
});

describe('node edit tool', () => {
  let mock: MockGodotConnection;

  beforeEach(() => {
    mock = createMockGodot();
  });

  describe('schema validation', () => {
    it('requires node_path and properties for update', () => {
      expect(nodeEdit.schema.safeParse({ action: 'update' }).success).toBe(false);
      // properties is required: the addon rejects an empty update outright
      expect(nodeEdit.schema.safeParse({
        action: 'update',
        node_path: '/root/Test',
      }).success).toBe(false);
      expect(nodeEdit.schema.safeParse({
        action: 'update',
        node_path: '/root/Test',
        properties: { visible: false },
      }).success).toBe(true);
    });

    it('requires new_parent_path for reparent', () => {
      expect(nodeEdit.schema.safeParse({
        action: 'reparent',
        node_path: '/root/Test',
      }).success).toBe(false);
      expect(nodeEdit.schema.safeParse({
        action: 'reparent',
        node_path: '/root/Test',
        new_parent_path: '/root/New',
      }).success).toBe(true);
    });

    it('rejects read actions belonging to godot_node_read', () => {
      expect(nodeEdit.schema.safeParse({
        action: 'get_properties',
        node_path: '/root/Test',
      }).success).toBe(false);
      expect(nodeEdit.schema.safeParse({ action: 'get_scene_tree' }).success).toBe(false);
      expect(nodeEdit.schema.safeParse({
        action: 'find',
        name_pattern: '*Spawner*',
      }).success).toBe(false);
    });
  });

  describe('update/reparent', () => {
    it('returns appropriate confirmations', async () => {
      const ctx = createToolContext(mock);

      mock.mockResponse({});
      expect(await nodeEdit.execute({
        action: 'update',
        node_path: '/root/Player',
        properties: { health: 100 },
      }, ctx)).toBe('Updated node: /root/Player');

      mock.mockResponse({ new_path: '/root/New/Node' });
      expect(await nodeEdit.execute({
        action: 'reparent',
        node_path: '/root/Old/Node',
        new_parent_path: '/root/New',
      }, ctx)).toBe('Reparented node to: /root/New/Node');
    });
  });
});
