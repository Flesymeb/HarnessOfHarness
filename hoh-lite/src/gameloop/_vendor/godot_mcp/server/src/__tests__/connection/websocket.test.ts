import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { once } from 'node:events';
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { WebSocketServer, type WebSocket as WsSocket } from 'ws';
import { GodotConnection } from '../../connection/websocket.js';
import { getServerVersion } from '../../version.js';

// Keep diagnostics hermetic (no WSL detection / no child processes) and quiet.
vi.mock('../../utils/connection-strategy.js', () => ({
  getTargetHost: () => '127.0.0.1',
  getConnectionStrategy: (port: number) => ({
    environment: 'native' as const,
    targetHost: '127.0.0.1',
    wsUrl: `ws://127.0.0.1:${port}`,
  }),
}));

vi.mock('../../utils/logger.js', () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    notice: vi.fn(),
    warning: vi.fn(),
    warningRateLimited: vi.fn(),
    error: vi.fn(),
    critical: vi.fn(),
  },
}));

// Application close codes the Godot addon uses on the bridge.
const CLOSE_CODE_ALREADY_CONNECTED = 4001;
const CLOSE_CODE_REPLACED = 4003;

/**
 * Stand up a throwaway WebSocket server that plays the role of the Godot bridge.
 * The supplied handler decides what to do with each incoming client socket.
 */
async function startFakeBridge(
  onConnection: (socket: WsSocket) => void
): Promise<{ wss: WebSocketServer; port: number }> {
  const wss = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  await once(wss, 'listening');
  wss.on('connection', onConnection);
  const port = (wss.address() as AddressInfo).port;
  return { wss, port };
}

/** Resolve when `event` fires on `emitter`, reject if it doesn't within `ms`. */
function waitForEvent(emitter: GodotConnection, event: string, ms = 3000): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      emitter.off(event, handler);
      reject(new Error(`Timed out waiting for "${event}" event`));
    }, ms);
    const handler = () => {
      clearTimeout(timer);
      resolve();
    };
    emitter.once(event, handler);
  });
}

describe('GodotConnection contention handling (#237)', () => {
  let connection: GodotConnection | null = null;
  let wss: WebSocketServer | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(async () => {
    // Tear the client down first so its reconnect timer is cleared before the
    // bridge goes away (otherwise it would reconnect to a dead port).
    connection?.disconnect();
    connection = null;
    if (wss) {
      await new Promise<void>((resolve) => wss!.close(() => resolve()));
      wss = null;
    }
  });

  it('reconnects after being replaced by a newer client (4003), instead of latching dead', async () => {
    // Bridge replaces whoever connects: closes the socket with the REPLACED code.
    const bridge = await startFakeBridge((socket) => {
      socket.on('message', () => socket.close(CLOSE_CODE_REPLACED, 'Replaced by new client'));
    });
    wss = bridge.wss;

    connection = new GodotConnection({ host: '127.0.0.1', port: bridge.port });
    const reconnecting = waitForEvent(connection, 'reconnecting');

    await connection.connect().catch(() => {});
    // The whole point of #237: a replaced client must schedule a reconnect.
    await expect(reconnecting).resolves.toBeUndefined();
    expect(connection.getDiagnostics().lastDisconnectReason).toBe('replaced_by_new_client');
  });

  it('keeps retrying when rejected because another client is connected (4001)', async () => {
    const bridge = await startFakeBridge((socket) => {
      socket.on('message', () => socket.close(CLOSE_CODE_ALREADY_CONNECTED, 'Another client is already connected'));
    });
    wss = bridge.wss;

    connection = new GodotConnection({ host: '127.0.0.1', port: bridge.port });
    const reconnecting = waitForEvent(connection, 'reconnecting');

    await connection.connect().catch(() => {});
    await expect(reconnecting).resolves.toBeUndefined();
    expect(connection.getDiagnostics().lastDisconnectReason).toBe('rejected_another_client');
    expect(connection.getDiagnostics().rejectionCount).toBe(1);
  });

  it('no longer tells a replaced client to restart; reports automatic recovery', async () => {
    const bridge = await startFakeBridge((socket) => {
      socket.on('message', () => socket.close(CLOSE_CODE_REPLACED, 'Replaced by new client'));
    });
    wss = bridge.wss;

    connection = new GodotConnection({ host: '127.0.0.1', port: bridge.port });
    const reconnecting = waitForEvent(connection, 'reconnecting');
    await connection.connect().catch(() => {});
    await reconnecting;

    const message = connection.getDiagnosticMessage();
    expect(message).not.toMatch(/no longer active/i);
    expect(message).toMatch(/reconnect/i);
  });

  it('does not leak an unhandled rejection when the editor is temporarily absent', async () => {
    const probe = new WebSocketServer({ host: '127.0.0.1', port: 0 });
    await once(probe, 'listening');
    const port = (probe.address() as AddressInfo).port;
    await new Promise<void>((resolve) => probe.close(() => resolve()));

    connection = new GodotConnection({ host: '127.0.0.1', port, autoReconnect: false });
    connection.on('error', () => {});
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);
    try {
      await expect(connection.connect()).rejects.toThrow(/connect/i);
      await new Promise((resolve) => setImmediate(resolve));
      expect(unhandled).toEqual([]);
    } finally {
      process.off('unhandledRejection', onUnhandled);
    }
  });

  it('holds the first command until a cold editor bridge becomes ready', async () => {
    const probe = new WebSocketServer({ host: '127.0.0.1', port: 0 });
    await once(probe, 'listening');
    const port = (probe.address() as AddressInfo).port;
    await new Promise<void>((resolve) => probe.close(() => resolve()));

    connection = new GodotConnection({
      host: '127.0.0.1',
      port,
      autoReconnect: false,
      startupWaitMs: 1500,
    });
    connection.on('error', () => {});

    const bridgeReady = new Promise<void>((resolve, reject) => {
      setTimeout(() => {
        const delayedBridge = new WebSocketServer({ host: '127.0.0.1', port });
        delayedBridge.on('connection', (socket) => {
          socket.on('message', (raw) => {
            const msg = JSON.parse(raw.toString()) as { id: string; command: string };
            socket.send(JSON.stringify(
              msg.command === 'mcp_handshake'
                ? {
                    id: msg.id,
                    status: 'success',
                    result: {
                      addon_version: getServerVersion(),
                      project_path: '/tmp/project',
                    },
                  }
                : { id: msg.id, status: 'success', result: { ready: true } }
            ));
          });
        });
        once(delayedBridge, 'listening').then(() => {
          wss = delayedBridge;
          resolve();
        }, reject);
      }, 100);
    });

    const command = connection.sendCommand<{ ready: boolean }>('get_project_info');
    await bridgeReady;
    await expect(command).resolves.toEqual({ ready: true });
  });

  it('fails fast with recovery guidance before project.godot exists', async () => {
    const tempRoot = mkdtempSync(join(tmpdir(), 'godot-mcp-cold-project-'));
    const expectedProject = join(tempRoot, 'game');
    try {
      connection = new GodotConnection({
        host: '127.0.0.1',
        port: 65534,
        autoReconnect: false,
        expectedProjectPath: expectedProject,
        startupWaitMs: 1500,
      });
      connection.on('error', () => {});

      const started = Date.now();
      await expect(
        connection.sendCommand('get_project_info')
      ).rejects.toThrow(/Create the minimal project first, then retry/);
      expect(Date.now() - started).toBeLessThan(500);
    } finally {
      rmSync(tempRoot, { recursive: true, force: true });
    }
  });
});

describe('GodotConnection handshake readiness', () => {
  let connection: GodotConnection | null = null;
  let wss: WebSocketServer | null = null;

  afterEach(async () => {
    connection?.disconnect();
    connection = null;
    if (wss) {
      await new Promise<void>((resolve) => wss!.close(() => resolve()));
      wss = null;
    }
  });

  it.each([
    [
      'a missing addon version',
      { status: 'success', result: { project_path: '/tmp/project' } },
      /addon version/i,
    ],
    [
      'an unknown addon version',
      { status: 'success', result: { addon_version: 'unknown', project_path: '/tmp/project' } },
      /addon version/i,
    ],
    [
      'a mismatched addon version',
      { status: 'success', result: { addon_version: '0.0.0', project_path: '/tmp/project' } },
      /version mismatch/i,
    ],
    [
      'an explicit handshake error',
      { status: 'error', error: { code: 'INCOMPATIBLE_ADDON', message: 'incompatible addon' } },
      /incompatible addon/i,
    ],
    ['a malformed response', { status: 'success' }, /malformed response/i],
  ])('stays unusable after %s, then permits a corrected retry', async (_label, response, errorPattern) => {
    let connectionCount = 0;
    let commandCount = 0;
    const bridge = await startFakeBridge((socket) => {
      connectionCount++;
      const thisConnection = connectionCount;
      socket.on('message', (raw) => {
        const msg = JSON.parse(raw.toString()) as { id: string; command: string };
        if (msg.command !== 'mcp_handshake') {
          commandCount++;
          socket.send(JSON.stringify({
            id: msg.id,
            status: 'success',
            result: { ok: true },
          }));
          return;
        }
        socket.send(JSON.stringify(
          thisConnection <= 2
            ? { id: msg.id, ...response }
            : {
                id: msg.id,
                status: 'success',
                result: { addon_version: getServerVersion(), project_path: '/tmp/project' },
              }
        ));
      });
    });
    wss = bridge.wss;

    connection = new GodotConnection({
      host: '127.0.0.1',
      port: bridge.port,
      autoReconnect: false,
    });
    const connected = vi.fn();
    connection.on('connected', connected);

    await expect(connection.connect()).rejects.toThrow(errorPattern);
    expect(connection.isConnected).toBe(false);
    expect(connection.getDiagnostics().currentState).not.toBe('connected');
    expect(connected).not.toHaveBeenCalled();
    expect(commandCount).toBe(0);

    // sendCommand may try to reconnect, but it must never dispatch the
    // ordinary command through another socket with an invalid handshake.
    await expect(connection.sendCommand('get_runtime_state')).rejects.toThrow(/not connected/i);
    expect(connectionCount).toBe(2);
    expect(commandCount).toBe(0);
    expect(connected).not.toHaveBeenCalled();

    await expect(connection.connect()).resolves.toBeUndefined();
    expect(connectionCount).toBe(3);
    expect(connection.isConnected).toBe(true);
    expect(connected).toHaveBeenCalledTimes(1);
    await expect(connection.sendCommand('get_runtime_state')).resolves.toEqual({ ok: true });
    expect(commandCount).toBe(1);
  });

  it('rejects a failed handshake and auto-reconnects with only the successful socket ready', async () => {
    let connectionCount = 0;
    const bridge = await startFakeBridge((socket) => {
      connectionCount++;
      const thisConnection = connectionCount;
      socket.on('message', (raw) => {
        const msg = JSON.parse(raw.toString()) as { id: string; command: string };
        if (msg.command !== 'mcp_handshake') return;
        if (thisConnection === 1) {
          socket.send(JSON.stringify({
            id: msg.id,
            status: 'error',
            error: { code: 'INCOMPATIBLE_ADDON', message: 'incompatible addon' },
          }));
          return;
        }
        socket.send(JSON.stringify({
          id: msg.id,
          status: 'success',
          result: { addon_version: getServerVersion(), project_path: '/tmp/project' },
        }));
      });
    });
    wss = bridge.wss;

    connection = new GodotConnection({ host: '127.0.0.1', port: bridge.port });
    const connected = vi.fn();
    connection.on('connected', connected);
    const recovered = waitForEvent(connection, 'connected');

    await expect(connection.connect()).rejects.toThrow(/incompatible addon/i);
    expect(connection.isConnected).toBe(false);
    expect(connected).not.toHaveBeenCalled();

    await expect(recovered).resolves.toBeUndefined();
    expect(connectionCount).toBe(2);
    expect(connection.isConnected).toBe(true);
    expect(connection.getDiagnostics().currentState).toBe('connected');
    expect(connected).toHaveBeenCalledTimes(1);
  });

  it('rejects a handshake timeout, closes the bad socket, and permits an immediate retry', async () => {
    let connectionCount = 0;
    const bridge = await startFakeBridge((socket) => {
      connectionCount++;
      const thisConnection = connectionCount;
      socket.on('message', (raw) => {
        const msg = JSON.parse(raw.toString()) as { id: string; command: string };
        if (msg.command !== 'mcp_handshake' || thisConnection === 1) return;
        socket.send(JSON.stringify({
          id: msg.id,
          status: 'success',
          result: { addon_version: getServerVersion(), project_path: '/tmp/project' },
        }));
      });
    });
    wss = bridge.wss;

    connection = new GodotConnection({
      host: '127.0.0.1',
      port: bridge.port,
      autoReconnect: false,
      handshakeTimeoutMs: 50,
    });
    const connected = vi.fn();
    connection.on('connected', connected);

    await expect(connection.connect()).rejects.toThrow(/mcp_handshake.*timed out/i);
    expect(connection.isConnected).toBe(false);
    expect(connected).not.toHaveBeenCalled();

    await expect(connection.connect()).resolves.toBeUndefined();
    expect(connectionCount).toBe(2);
    expect(connection.isConnected).toBe(true);
    expect(connected).toHaveBeenCalledTimes(1);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(connection.isConnected).toBe(true);
  });

  it('rejects a bridge attached to a different configured project realpath', async () => {
    const tempRoot = mkdtempSync(join(tmpdir(), 'godot-mcp-handshake-'));
    const expectedProject = join(tempRoot, 'expected');
    const otherProject = join(tempRoot, 'other');
    try {
      mkdirSync(expectedProject);
      mkdirSync(otherProject);

      const bridge = await startFakeBridge((socket) => {
        socket.on('message', (raw) => {
          const msg = JSON.parse(raw.toString()) as { id: string; command: string };
          if (msg.command !== 'mcp_handshake') return;
          socket.send(JSON.stringify({
            id: msg.id,
            status: 'success',
            result: {
              addon_version: getServerVersion(),
              project_path: otherProject,
            },
          }));
        });
      });
      wss = bridge.wss;

      connection = new GodotConnection({
        host: '127.0.0.1',
        port: bridge.port,
        autoReconnect: false,
        expectedProjectPath: expectedProject,
      });
      await expect(connection.connect()).rejects.toThrow(/project mismatch/i);
      expect(connection.isConnected).toBe(false);
      expect(connection.getDiagnostics().currentState).not.toBe('connected');
    } finally {
      connection?.disconnect();
      connection = null;
      if (wss) {
        await new Promise<void>((resolve) => wss!.close(() => resolve()));
        wss = null;
      }
      rmSync(tempRoot, { recursive: true, force: true });
    }
  });

  it('rejects connect when explicitly disconnected during the handshake', async () => {
    const bridge = await startFakeBridge(() => {
      // Deliberately leave the handshake unanswered until the client closes.
    });
    wss = bridge.wss;
    connection = new GodotConnection({
      host: '127.0.0.1',
      port: bridge.port,
      autoReconnect: false,
      handshakeTimeoutMs: 5000,
    });

    const attempt = connection.connect();
    await new Promise((resolve) => setTimeout(resolve, 20));
    connection.disconnect();

    await expect(attempt).rejects.toThrow(/connection closed/i);
    expect(connection.isConnected).toBe(false);
    expect(connection.getDiagnostics().currentState).toBe('disconnected');
  });

  it('rejects connect when immediately disconnected during TCP connection setup', async () => {
    const bridge = await startFakeBridge((socket) => {
      socket.on('message', (raw) => {
        const msg = JSON.parse(raw.toString()) as { id: string; command: string };
        if (msg.command !== 'mcp_handshake') return;
        socket.send(JSON.stringify({
          id: msg.id,
          status: 'success',
          result: { addon_version: getServerVersion(), project_path: '/tmp/project' },
        }));
      });
    });
    wss = bridge.wss;
    connection = new GodotConnection({
      host: '127.0.0.1',
      port: bridge.port,
      autoReconnect: false,
    });

    const attempt = connection.connect();
    connection.disconnect();

    await expect(attempt).rejects.toThrow(/closed|connect|socket/i);
    expect(connection.isConnected).toBe(false);
    expect(connection.getDiagnostics().currentState).toBe('disconnected');

    // The rejected attempt must have released connectPromise so a later
    // corrected call can establish a fresh, usable socket.
    await expect(connection.connect()).resolves.toBeUndefined();
    expect(connection.isConnected).toBe(true);
  });
});

describe('GodotConnection per-request timeout (#276)', () => {
  let connection: GodotConnection | null = null;
  let wss: WebSocketServer | null = null;

  afterEach(async () => {
    connection?.disconnect();
    connection = null;
    if (wss) {
      await new Promise<void>((resolve) => wss!.close(() => resolve()));
      wss = null;
    }
  });

  // Reply to the handshake (so connect() resolves immediately and without a
  // version-mismatch), then let the supplied handler deal with real commands.
  async function bridgeAfterHandshake(
    onCommand: (socket: WsSocket, msg: { id: string; command: string }) => void
  ): Promise<{ wss: WebSocketServer; port: number }> {
    return startFakeBridge((socket) => {
      socket.on('message', (raw) => {
        let msg: { id: string; command: string } | undefined;
        try {
          msg = JSON.parse(raw.toString());
        } catch {
          return;
        }
        if (!msg) return;
        if (msg.command === 'mcp_handshake') {
          socket.send(JSON.stringify({ id: msg.id, status: 'success', result: { addon_version: getServerVersion() } }));
          return;
        }
        onCommand(socket, msg);
      });
    });
  }

  it('rejects after opts.timeoutMs when the bridge never answers the command', async () => {
    // Drop every non-handshake command on the floor.
    const bridge = await bridgeAfterHandshake(() => {});
    wss = bridge.wss;
    connection = new GodotConnection({ host: '127.0.0.1', port: bridge.port, autoReconnect: false });
    await connection.connect();

    const start = Date.now();
    await expect(connection.sendCommand('get_runtime_state', {}, { timeoutMs: 150 })).rejects.toThrow();
    const elapsed = Date.now() - start;
    expect(elapsed).toBeGreaterThanOrEqual(120);
    expect(elapsed).toBeLessThan(2000);
  });

  it('does not fire early when given a generous opts.timeoutMs', async () => {
    // Answer the command after a short delay; a 1s budget must not trip on it.
    const bridge = await bridgeAfterHandshake((socket, msg) => {
      setTimeout(() => socket.send(JSON.stringify({ id: msg.id, status: 'success', result: { ok: true } })), 100);
    });
    wss = bridge.wss;
    connection = new GodotConnection({ host: '127.0.0.1', port: bridge.port, autoReconnect: false });
    await connection.connect();

    const result = await connection.sendCommand<{ ok: boolean }>('get_runtime_state', {}, { timeoutMs: 1000 });
    expect(result.ok).toBe(true);
  });

  it('serializes concurrent commands so single-slot addon handlers cannot cross-talk', async () => {
    const received: Array<{ id: string; command: string }> = [];
    let firstSocket: WsSocket | null = null;
    const bridge = await bridgeAfterHandshake((socket, msg) => {
      received.push(msg);
      if (received.length === 1) {
        firstSocket = socket;
        return;
      }
      socket.send(JSON.stringify({
        id: msg.id,
        status: 'success',
        result: { command: msg.command },
      }));
    });
    wss = bridge.wss;
    connection = new GodotConnection({ host: '127.0.0.1', port: bridge.port, autoReconnect: false });
    await connection.connect();

    const first = connection.sendCommand<{ command: string }>('find_nodes', { pattern: '*Weapon*' });
    const second = connection.sendCommand<{ command: string }>('get_runtime_state', {});
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(received.map((item) => item.command)).toEqual(['find_nodes']);
    firstSocket!.send(JSON.stringify({
      id: received[0].id,
      status: 'success',
      result: { command: received[0].command },
    }));

    await expect(first).resolves.toEqual({ command: 'find_nodes' });
    await expect(second).resolves.toEqual({ command: 'get_runtime_state' });
    expect(received.map((item) => item.command)).toEqual([
      'find_nodes',
      'get_runtime_state',
    ]);
  });

  it('cancels queued commands on disconnect without a hidden reconnect or late dispatch', async () => {
    let connections = 0;
    const commands: string[] = [];
    const bridge = await startFakeBridge((socket) => {
      connections++;
      socket.on('message', (raw) => {
        const msg = JSON.parse(raw.toString()) as { id: string; command: string };
        commands.push(msg.command);
        if (msg.command === 'mcp_handshake') {
          socket.send(JSON.stringify({
            id: msg.id,
            status: 'success',
            result: { addon_version: getServerVersion(), project_path: '/tmp/project' },
          }));
        }
        // Keep ordinary commands pending until disconnect tears them down.
      });
    });
    wss = bridge.wss;
    connection = new GodotConnection({
      host: '127.0.0.1',
      port: bridge.port,
      autoReconnect: false,
    });
    await connection.connect();

    const first = connection.sendCommand('first_stateful');
    const second = connection.sendCommand('second_stateful');
    await new Promise((resolve) => setTimeout(resolve, 30));
    connection.disconnect();

    await expect(first).rejects.toThrow(/connection closed/i);
    await expect(second).rejects.toThrow(/generation closed/i);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(connections).toBe(1);
    expect(commands).toEqual(['mcp_handshake', 'first_stateful']);
    expect(connection.isConnected).toBe(false);
  });
});
