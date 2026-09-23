import { describe, it, expect, beforeAll } from 'vitest';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { registry } from '../../core/registry.js';
import { registerAllTools } from '../../tools/index.js';
import {
  isStructuredMultiContentResult,
  isStructuredResult,
  structured,
  structuredWithContent,
} from '../../core/structured.js';
import {
  isRuntimeTeardownCall,
  persistCallEvidence,
  successfulCallLimit,
  toCallToolResponse,
  toEvidenceCallToolResponse,
} from '../../index.js';
import { resource } from '../../tools/resource.js';
import { createMockGodot, createToolContext } from '../helpers/mock-godot.js';

describe('structured tool output', () => {
  beforeAll(() => {
    registerAllTools();
  });

  const byName = () => new Map(registry.getToolList().map((t) => [t.name, t]));

  it('hard-bounds successful Runtime QA calls and leaves Developer calls unlimited', () => {
    const previous = process.env.GAMELOOP_MCP_MAX_SUCCESSFUL_CALLS;
    try {
      process.env.GAMELOOP_MCP_MAX_SUCCESSFUL_CALLS = '17';
      expect(successfulCallLimit(true)).toBe(17);
      expect(successfulCallLimit(false)).toBeNull();
      process.env.GAMELOOP_MCP_MAX_SUCCESSFUL_CALLS = 'invalid';
      expect(successfulCallLimit(true)).toBe(30);
    } finally {
      if (previous === undefined) delete process.env.GAMELOOP_MCP_MAX_SUCCESSFUL_CALLS;
      else process.env.GAMELOOP_MCP_MAX_SUCCESSFUL_CALLS = previous;
    }
  });

  it('always permits an explicit runtime stop after the QA observation budget', () => {
    expect(isRuntimeTeardownCall('godot_editor_edit', { action: 'stop' })).toBe(true);
    expect(isRuntimeTeardownCall('godot_editor_edit', { action: 'run' })).toBe(false);
    expect(isRuntimeTeardownCall('godot_editor_read', { action: 'screenshot_game' })).toBe(false);
  });

  it('structured() renders compact JSON text alongside the object', () => {
    const data = { a: 1, b: { c: 2 } };
    const result = structured(data);
    expect(result.text).toBe('{"a":1,"b":{"c":2}}');
    expect(result.structuredContent).toEqual(data);
  });

  it('isStructuredResult recognizes a structured result', () => {
    expect(isStructuredResult(structured({ x: 1 }))).toBe(true);
  });

  it('isStructuredResult rejects a plain string result', () => {
    expect(isStructuredResult('Opened scene: res://main.tscn')).toBe(false);
  });

  it('isStructuredResult rejects text and image content items', () => {
    expect(isStructuredResult({ type: 'text', text: 'hi' })).toBe(false);
    expect(isStructuredResult({ type: 'image', data: 'x', mimeType: 'image/png' })).toBe(false);
  });

  it('structuredWithContent preserves blocks and adds metadata without duplicating image data', () => {
    const content = [
      { type: 'text' as const, text: 'captured' },
      { type: 'image' as const, data: 'BASE64_ONLY_HERE', mimeType: 'image/png' },
    ];
    const result = structuredWithContent(content, {
      completed: true,
      captures: [{ requested_ms: 10, ok: true }],
    });

    expect(isStructuredMultiContentResult(result)).toBe(true);
    expect(result.content).toBe(content);
    expect(JSON.stringify(result.structuredContent)).not.toContain('BASE64_ONLY_HERE');
  });

  it('serializes a structured multi-content result to both MCP response fields', () => {
    const result = structuredWithContent(
      [{ type: 'image', data: 'AAAA', mimeType: 'image/png' }],
      { completed: true, captures: [{ requested_ms: 0, ok: true }] }
    );

    expect(toCallToolResponse(result)).toEqual({
      content: [{ type: 'image', data: 'AAAA', mimeType: 'image/png' }],
      structuredContent: {
        completed: true,
        captures: [{ requested_ms: 0, ok: true }],
      },
    });
  });

  it('keeps lossless evidence blocks out of the model-facing response', () => {
    const result = structuredWithContent(
      [{ type: 'image', data: 'JPEG_PREVIEW', mimeType: 'image/jpeg' }],
      { screenshot: { width: 1280, height: 720 } },
      [{ type: 'image', data: 'PNG_EVIDENCE', mimeType: 'image/png' }]
    );
    const response = toCallToolResponse(result);

    expect(JSON.stringify(response)).toContain('JPEG_PREVIEW');
    expect(JSON.stringify(response)).not.toContain('PNG_EVIDENCE');
    expect(toEvidenceCallToolResponse(result, response)).toEqual({
      ...response,
      content: [{ type: 'image', data: 'PNG_EVIDENCE', mimeType: 'image/png' }],
    });
  });

  it('persists image files and a compact structured receipt before client truncation', () => {
    const root = mkdtempSync(join(tmpdir(), 'godot-mcp-evidence-'));
    const previous = process.env.GAMELOOP_MCP_EVIDENCE_DIR;
    process.env.GAMELOOP_MCP_EVIDENCE_DIR = root;
    try {
      const png = Buffer.alloc(24);
      Buffer.from('89504e470d0a1a0a', 'hex').copy(png, 0);
      png.write('IHDR', 12, 'ascii');
      png.writeUInt32BE(1280, 16);
      png.writeUInt32BE(720, 20);
      const response = toCallToolResponse(
        structuredWithContent(
          [{ type: 'image', data: png.toString('base64'), mimeType: 'image/png' }],
          { completed: true, actions_executed: 1, report: { moved: true } }
        )
      );

      persistCallEvidence(
        'godot_input',
        { action: 'sequence', screenshot_at_ms: [100] },
        response
      );

      const files = readdirSync(root);
      const receiptPath = join(root, files.find((name) => name.endsWith('.json'))!);
      const receipt = JSON.parse(readFileSync(receiptPath, 'utf8'));
      expect(receipt.completed).toBe(true);
      expect(receipt.tool).toBe('godot_input');
      expect(receipt.structured_content.completed).toBe(true);
      expect(receipt.images).toHaveLength(1);
      expect(receipt.images[0]).toMatchObject({ width: 1280, height: 720, bytes: 24 });
      expect(readFileSync(join(root, receipt.images[0].path))).toEqual(png);
      expect(readFileSync(receiptPath, 'utf8')).not.toContain(png.toString('base64'));
    } finally {
      if (previous === undefined) delete process.env.GAMELOOP_MCP_EVIDENCE_DIR;
      else process.env.GAMELOOP_MCP_EVIDENCE_DIR = previous;
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('persists compact receipts for successful non-image calls', () => {
    const root = mkdtempSync(join(tmpdir(), 'godot-mcp-evidence-'));
    const previous = process.env.GAMELOOP_MCP_EVIDENCE_DIR;
    process.env.GAMELOOP_MCP_EVIDENCE_DIR = root;
    try {
      persistCallEvidence(
        'godot_project',
        { action: 'get_info' },
        toCallToolResponse(structured({ path: '/candidate/game' }))
      );

      const receiptPath = join(
        root,
        readdirSync(root).find((name) => name.endsWith('.json'))!
      );
      const receipt = JSON.parse(readFileSync(receiptPath, 'utf8'));
      expect(receipt).toMatchObject({
        completed: true,
        tool: 'godot_project',
        arguments: { action: 'get_info' },
        structured_content: { path: '/candidate/game' },
        images: [],
      });
    } finally {
      if (previous === undefined) delete process.env.GAMELOOP_MCP_EVIDENCE_DIR;
      else process.env.GAMELOOP_MCP_EVIDENCE_DIR = previous;
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('no tool advertises outputSchema (policy: structuredContent + text fallback only)', () => {
    // Declaring outputSchema creates a MUST-conform contract and has broken
    // whole tools on schema-strict clients; GitHub's and Playwright's MCP
    // servers skip it too. structuredContent still ships on every query tool.
    for (const tool of byName().values()) {
      expect(tool, tool.name).not.toHaveProperty('outputSchema');
    }
  });

  it('resource get_info returns a structured result, not a string', async () => {
    const mock = createMockGodot();
    mock.mockResponse({ resource_path: 'res://x.tres', resource_type: 'Resource' });
    const result = await resource.execute(
      { action: 'get_info', resource_path: 'res://x.tres' },
      createToolContext(mock)
    );
    expect(isStructuredResult(result)).toBe(true);
  });

  it('resource get_info structuredContent matches the Godot payload', async () => {
    const mock = createMockGodot();
    const payload = { resource_path: 'res://x.tres', resource_type: 'Texture2D', properties: { width: 64 } };
    mock.mockResponse(payload);
    const result = await resource.execute(
      { action: 'get_info', resource_path: 'res://x.tres' },
      createToolContext(mock)
    );
    expect(isStructuredResult(result) && result.structuredContent).toEqual(payload);
  });

  it('resource get_info text fallback is compact JSON of the payload', async () => {
    const mock = createMockGodot();
    const payload = { resource_path: 'res://x.tres', resource_type: 'Resource' };
    mock.mockResponse(payload);
    const result = await resource.execute(
      { action: 'get_info', resource_path: 'res://x.tres' },
      createToolContext(mock)
    );
    expect(isStructuredResult(result) && result.text).toBe(JSON.stringify(payload));
  });
});
