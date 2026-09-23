import type {
  MultiContentResult,
  StructuredMultiContentResult,
  StructuredToolResult,
} from './types.js';

// Wrap a query payload so the tool result carries both a compact-JSON text
// rendering (the fallback for clients without structured-output support) and
// the object itself as MCP `structuredContent`.
export function structured(data: unknown): StructuredToolResult {
  return {
    text: JSON.stringify(data),
    structuredContent: data as Record<string, unknown>,
  };
}

// Pair ordered content blocks with a machine-readable receipt. The caller must
// keep binary payloads in `content`; structuredContent is metadata only so MCP
// clients do not receive duplicate base64 data.
export function structuredWithContent(
  content: MultiContentResult,
  data: unknown,
  evidenceContent?: MultiContentResult
): StructuredMultiContentResult {
  return {
    content,
    structuredContent: data as Record<string, unknown>,
    ...(evidenceContent ? { evidenceContent } : {}),
  };
}

export function isStructuredResult(value: unknown): value is StructuredToolResult {
  return (
    typeof value === 'object' &&
    value !== null &&
    'structuredContent' in value &&
    'text' in value
  );
}

export function isStructuredMultiContentResult(
  value: unknown
): value is StructuredMultiContentResult {
  return (
    typeof value === 'object' &&
    value !== null &&
    'structuredContent' in value &&
    'content' in value &&
    Array.isArray(value.content)
  );
}
