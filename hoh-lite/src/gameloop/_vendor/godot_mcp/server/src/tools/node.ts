import { z } from 'zod';
import { defineTool } from '../core/define-tool.js';
import { structured } from '../core/structured.js';
import type { AnyToolDefinition } from '../core/types.js';

const NodeReadSchema = z
  .discriminatedUnion('action', [
    z.object({
      action: z.literal('get_properties').describe('Get a node\'s properties'),
      node_path: z.string().describe('Path to the node'),
    }),
    z.object({
      action: z
        .literal('get_scene_tree')
        .describe(
          'Full hierarchy of the open scene as the editor sees it, including children inside instanced sub-scenes (a .tscn file read cannot show those). Deep or wide scenes can be large — cap the result with max_depth and/or max_children; any node whose children are cut off carries "truncated_children": <count of omitted direct children> instead of (or alongside) "children".'
        ),
      max_depth: z
        .number()
        .int()
        .positive()
        .optional()
        .describe('Cap recursion depth (root = depth 1). Omit for the full tree.'),
      max_children: z
        .number()
        .int()
        .positive()
        .optional()
        .describe('Cap how many children are listed per node. Omit to list every child.'),
    }),
    z.object({
      action: z
        .literal('find')
        .describe(
          'Find nodes by name and/or type. Searches the RUNNING game\'s live tree when a game is playing (spawned entities included); otherwise searches the scene open in the editor.'
        ),
      name_pattern: z
        .string()
        .optional()
        .describe('Glob pattern to match node names, e.g. "*Spawner*", "Turret?"'),
      type: z
        .string()
        .optional()
        .describe('Filter by node type, e.g. "CharacterBody2D", "Area2D"'),
      root_path: z
        .string()
        .optional()
        .describe('Path to start search from (defaults to scene root)'),
    }),
    z.object({
      action: z
        .literal('inspect_ui')
        .describe(
          'Inspect bounded Control layout and input behavior in the running game, or in the editor-open scene when stopped. Returns global rectangles, anchors, offsets, clipping, z-order, focus, mouse_filter and explicit full-screen input risks.'
        ),
      root_path: z
        .string()
        .optional()
        .describe('Optional subtree root. Defaults to the current scene root.'),
      max_depth: z
        .number()
        .int()
        .min(1)
        .max(32)
        .optional()
        .describe('Maximum descendant depth to inspect (default 12).'),
      max_nodes: z
        .number()
        .int()
        .min(1)
        .max(512)
        .optional()
        .describe('Maximum Control nodes to return (default 128).'),
    }),
    z.object({
      action: z
        .literal('inspect_skeleton')
        .describe(
          'Inspect a Skeleton3D live pose, hierarchy, BoneAttachment3D/Marker3D bindings and nearby AnimationPlayer/AnimationTree state. Use a path returned by find(type="Skeleton3D").'
        ),
      node_path: z.string().describe('Exact Skeleton3D path.'),
      max_bones: z
        .number()
        .int()
        .min(1)
        .max(512)
        .optional()
        .describe('Maximum bones to return (default 128).'),
    }),
  ])
  // Constraints a discriminated union can't express on its own, so they live here:
  .refine(
    (data) => (data.action === 'find' ? !!data.name_pattern || !!data.type : true),
    { message: 'find requires name_pattern and/or type' }
  );

type NodeReadArgs = z.infer<typeof NodeReadSchema>;

const NodeEditSchema = z.discriminatedUnion('action', [
  z.object({
    action: z.literal('update').describe('Update a node\'s properties'),
    node_path: z.string().describe('Path to the node'),
    // Required: the addon rejects an empty update, so publishing this as
    // optional would invite a guaranteed-failure call shape.
    properties: z.record(z.string(), z.unknown()).describe('Properties to set on the node'),
  }),
  z.object({
    action: z.literal('reparent').describe('Move a node to a new parent'),
    node_path: z.string().describe('Path to the node'),
    new_parent_path: z.string().describe('Path to the new parent node'),
  }),
]);

type NodeEditArgs = z.infer<typeof NodeEditSchema>;

export const nodeRead = defineTool({
  name: 'godot_node_read',
  annotations: {
    title: 'Node (read)',
    readOnlyHint: true,
    destructiveHint: false,
    openWorldHint: false,
  },
  description:
    'Inspect scene nodes: while a game is running, get_properties, find, inspect_ui and inspect_skeleton query the live runtime tree (including spawned nodes); otherwise they query the scene open in the editor. inspect_ui exposes Control geometry and input interception; inspect_skeleton exposes real bone pose/socket/animation bindings that screenshots or synthetic marker telemetry cannot prove. get_scene_tree always reports the editor-open scene, including children inside instanced sub-scenes. Use exact paths returned by find in the same run. It cannot modify anything; to update properties or reparent a node, use godot_node_edit.',
  schema: NodeReadSchema,
  async execute(args: NodeReadArgs, { godot }) {
    switch (args.action) {
      case 'get_properties': {
        const result = await godot.sendCommand<{
          properties: Record<string, unknown>;
        }>('get_node_properties', { node_path: args.node_path });
        return structured(result.properties);
      }

      case 'get_scene_tree': {
        const result = await godot.sendCommand<{ tree: unknown }>('get_scene_tree', {
          max_depth: args.max_depth,
          max_children: args.max_children,
        });
        return structured(result.tree as Record<string, unknown>);
      }

      case 'find': {
        const result = await godot.sendCommand<{
          matches: Array<{ path: string; type: string }>;
          count: number;
        }>('find_nodes', {
          name_pattern: args.name_pattern,
          type: args.type,
          root_path: args.root_path,
        });
        if (result.count === 0) {
          return 'No matching nodes found';
        }
        const lines = result.matches.map((m) => `${m.path} (${m.type})`);
        return `Found ${result.count} nodes:\n${lines.join('\n')}`;
      }

      case 'inspect_ui': {
        const result = await godot.sendCommand<{
          inspection: Record<string, unknown>;
        }>('inspect_ui', {
          root_path: args.root_path,
          max_depth: args.max_depth,
          max_nodes: args.max_nodes,
        });
        return structured(result.inspection);
      }

      case 'inspect_skeleton': {
        const result = await godot.sendCommand<{
          inspection: Record<string, unknown>;
        }>('inspect_skeleton', {
          node_path: args.node_path,
          max_bones: args.max_bones,
        });
        return structured(result.inspection);
      }
    }
  },
});

export const nodeEdit = defineTool({
  name: 'godot_node_edit',
  annotations: {
    title: 'Node (edit)',
    readOnlyHint: false,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
  description:
    'Modify scene nodes in the editor: update a node\'s properties, or reparent it (the editor rewrites child paths and signal connections correctly; hand-editing .tscn for a reparent does not). Use it to change existing nodes in the open scene. To inspect properties, the scene tree, or search for nodes, use godot_node_read; to add or remove nodes, or attach scripts and connect signals, edit the .tscn file directly, then verify with godot_node_read\'s get_scene_tree.',
  schema: NodeEditSchema,
  async execute(args: NodeEditArgs, { godot }) {
    switch (args.action) {
      case 'update': {
        await godot.sendCommand('update_node', {
          node_path: args.node_path,
          properties: args.properties,
        });
        return `Updated node: ${args.node_path}`;
      }

      case 'reparent': {
        const result = await godot.sendCommand<{ new_path: string }>('reparent_node', {
          node_path: args.node_path,
          new_parent_path: args.new_parent_path,
        });
        return `Reparented node to: ${result.new_path}`;
      }
    }
  },
});

export const nodeTools = [nodeRead, nodeEdit] as AnyToolDefinition[];
