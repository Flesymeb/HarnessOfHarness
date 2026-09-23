import WebSocket from 'ws';
import { EventEmitter } from 'events';
import { existsSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
import { ResponseSchema, createRequest, isSuccessResponse, isErrorResponse } from './protocol.js';
import {
  GodotConnectionError,
  GodotCommandError,
  GodotTimeoutError,
} from '../utils/errors.js';
import { getServerVersion } from '../version.js';
import { logger } from '../utils/logger.js';
import { getTargetHost, getConnectionStrategy } from '../utils/connection-strategy.js';
import { QUICK_TIMEOUT_MS } from './timeouts.js';

const DEFAULT_PORT = 6550;
const DEFAULT_HOST = 'localhost';
const HANDSHAKE_TIMEOUT_MS = 5000;
const DEFAULT_STARTUP_WAIT_MS = 45000;
const STARTUP_RETRY_DELAY_MS = 250;
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000];
const PING_INTERVAL_MS = 30000;
const PONG_TIMEOUT_MS = 10000;

const CLOSE_CODE_ALREADY_CONNECTED = 4001;
const CLOSE_CODE_STALE = 4002;
const CLOSE_CODE_REPLACED = 4003;

export type DisconnectReason =
  | 'never_connected'
  | 'rejected_another_client'
  | 'replaced_by_new_client'
  | 'connection_refused'
  | 'connection_lost'
  | 'closed_normally'
  | 'error';

export interface ConnectionDiagnostics {
  currentState: 'connected' | 'disconnected' | 'connecting' | 'reconnecting';
  lastDisconnectReason: DisconnectReason;
  rejectionCount: number;
  reconnectAttempts: number;
  lastErrorMessage: string | null;
  url: string;
  environment: 'wsl' | 'native';
}

export type HandshakeStatus = 'pending' | 'success' | 'failed' | 'timeout';

export interface HandshakeResult {
  addonVersion: string;
  godotVersion: string;
  projectPath: string;
  projectName: string;
  handshakeStatus: HandshakeStatus;
}

interface PendingRequest {
  resolve: (result: unknown) => void;
  reject: (error: Error) => void;
  timeoutId: NodeJS.Timeout;
}

export interface GodotConnectionOptions {
  host?: string;
  port?: number;
  autoReconnect?: boolean;
  /** Primarily useful for bounded startup probes and deterministic tests. */
  handshakeTimeoutMs?: number;
  /** When set, reject a bridge attached to any other Godot project. */
  expectedProjectPath?: string;
  /**
   * Bounded grace period for a first command issued while a cold editor is
   * still starting. Defaults to 45s for a candidate-bound connection and 0
   * for an ordinary standalone connection.
   */
  startupWaitMs?: number;
}

export class GodotConnection extends EventEmitter {
  private ws: WebSocket | null = null;
  private pendingRequests: Map<string, PendingRequest> = new Map();
  // The Godot addon command handlers keep one pending/result slot per command
  // family.  Sending ordinary commands concurrently can therefore cross-talk
  // even though the WebSocket response ids are distinct.  Serialize the wire
  // requests here so every MCP client is safe by construction.  Commands such
  // as watch_start return immediately and may still observe a later input or
  // game-time command while the watch remains active.
  private commandQueue: Promise<void> = Promise.resolve();
  private reconnectAttempt = 0;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private connectPromise: Promise<void> | null = null;
  private rejectConnectAttempt: ((error: Error) => void) | null = null;
  private commandGeneration = 0;
  private pingInterval: NodeJS.Timeout | null = null;
  private pongTimeout: NodeJS.Timeout | null = null;
  private isClosing = false;
  private handshakeReady = false;
  private heartbeatPending = false;
  private handshakeResult: HandshakeResult | null = null;

  private lastDisconnectReason: DisconnectReason = 'never_connected';
  private rejectionCount = 0;
  private lastErrorMessage: string | null = null;
  private currentState: 'connected' | 'disconnected' | 'connecting' | 'reconnecting' = 'disconnected';

  private readonly host: string;
  private readonly _port: number;
  private readonly autoReconnect: boolean;
  private readonly handshakeTimeoutMs: number;
  private readonly expectedProjectPath: string | null;
  private readonly startupWaitMs: number;

  constructor(options: GodotConnectionOptions = {}) {
    super();
    this.host = options.host ?? DEFAULT_HOST;
    this._port = options.port ?? DEFAULT_PORT;
    this.autoReconnect = options.autoReconnect ?? true;
    this.handshakeTimeoutMs = options.handshakeTimeoutMs ?? HANDSHAKE_TIMEOUT_MS;
    this.expectedProjectPath = options.expectedProjectPath ?? null;
    this.startupWaitMs = Math.max(
      0,
      options.startupWaitMs
        ?? (this.expectedProjectPath ? DEFAULT_STARTUP_WAIT_MS : 0)
    );
  }

  get isConnected(): boolean {
    return this.handshakeReady && this.ws?.readyState === WebSocket.OPEN;
  }

  get url(): string {
    return `ws://${this.host}:${this._port}`;
  }

  get port(): number {
    return this._port;
  }

  get addonVersion(): string | null {
    return this.handshakeResult?.addonVersion ?? null;
  }

  get projectPath(): string | null {
    return this.handshakeResult?.projectPath ?? null;
  }

  get projectName(): string | null {
    return this.handshakeResult?.projectName ?? null;
  }

  get godotVersion(): string | null {
    return this.handshakeResult?.godotVersion ?? null;
  }

  get serverVersion(): string {
    return getServerVersion();
  }

  get versionsMatch(): boolean {
    if (!this.handshakeResult) return false;
    return this.handshakeResult.addonVersion === this.serverVersion;
  }

  getDiagnostics(): ConnectionDiagnostics {
    const strategy = getConnectionStrategy(this._port);
    return {
      currentState: this.currentState,
      lastDisconnectReason: this.lastDisconnectReason,
      rejectionCount: this.rejectionCount,
      reconnectAttempts: this.reconnectAttempt,
      lastErrorMessage: this.lastErrorMessage,
      url: this.url,
      environment: strategy.environment,
    };
  }

  getDiagnosticMessage(): string {
    const diag = this.getDiagnostics();
    const lines: string[] = [];

    switch (diag.lastDisconnectReason) {
      case 'rejected_another_client':
        lines.push('Status: Another client is already connected to Godot');
        if (diag.rejectionCount > 1) {
          lines.push(`Details: ${diag.rejectionCount} connection attempts rejected`);
        }
        lines.push('Suggestion: Only one client can drive the Godot bridge at a time.');
        lines.push('  This client keeps retrying and will connect once the other disconnects.');
        lines.push('  If you did not expect another client, check for duplicate godot-mcp processes:');
        lines.push('    macOS/Linux: ps aux | grep godot-mcp');
        lines.push('    Windows: Get-Process -Name node | ? CommandLine -Like "*godot-mcp*"');
        break;

      case 'replaced_by_new_client':
        lines.push('Status: Another client took over the Godot bridge');
        lines.push('Suggestion: Reconnecting automatically; this recovers once the other client disconnects.');
        break;

      case 'connection_refused':
        lines.push(`Status: Cannot reach Godot at ${diag.url}`);
        lines.push('Suggestion: Ensure Godot is running with the MCP addon enabled.');
        if (diag.environment === 'wsl') {
          lines.push('  Running in WSL: 127.0.0.1 does not cross to the Windows host.');
          lines.push('  In the Godot MCP panel set Bind mode: WSL (not Localhost), or set GODOT_HOST.');
        }
        break;

      case 'connection_lost':
        lines.push('Status: Connection to Godot was lost');
        if (diag.reconnectAttempts > 0) {
          lines.push(`Details: ${diag.reconnectAttempts} reconnection attempts made`);
        }
        lines.push('Suggestion: Check if Godot is still running.');
        break;

      case 'never_connected':
        lines.push(`Status: Never successfully connected to Godot at ${diag.url}`);
        lines.push('Suggestion: Ensure Godot is running with the MCP addon enabled.');
        if (diag.environment === 'wsl') {
          lines.push('  Running in WSL: 127.0.0.1 does not cross to the Windows host.');
          lines.push('  In the Godot MCP panel set Bind mode: WSL (not Localhost), or set GODOT_HOST.');
        }
        break;

      case 'error':
        lines.push('Status: Connection error');
        if (diag.lastErrorMessage) {
          lines.push(`Details: ${diag.lastErrorMessage}`);
        }
        break;

      default:
        lines.push(`Status: Disconnected (${diag.lastDisconnectReason})`);
    }

    return lines.join('\n');
  }

  async connect(): Promise<void> {
    if (this.isConnected) {
      return;
    }

    // A role may start the Godot editor after the MCP process has already
    // started.  Coalesce an in-flight handshake so the first real tool call
    // can recover the connection instead of immediately returning
    // "Not connected" while the background reconnect is still pending.
    if (this.connectPromise) {
      return this.connectPromise;
    }

    const attempt = new Promise<void>((resolve, reject) => {
      this.rejectConnectAttempt = reject;
      this.isClosing = false;
      this.handshakeReady = false;
      this.currentState = this.reconnectAttempt > 0 ? 'reconnecting' : 'connecting';
      const socket = new WebSocket(this.url);
      this.ws = socket;

      socket.on('open', async () => {
        try {
          await this.performHandshake(socket);
        } catch (error) {
          // A manual disconnect or a newer attempt may have superseded this
          // socket while its handshake was pending.  Reject this attempt, but
          // never let the stale completion overwrite the active connection's
          // readiness, diagnostics, or transport.
          if (this.ws !== socket) {
            reject(
              error instanceof Error
                ? error
                : new GodotConnectionError('Superseded handshake failed')
            );
            return;
          }
          const errorMessage = error instanceof Error ? error.message : String(error);
          logger.error('Handshake failed; rejecting socket', { error: errorMessage });
          this.emit('handshake_failed', { error: errorMessage });
          this.lastErrorMessage = errorMessage;
          if (
            this.lastDisconnectReason !== 'rejected_another_client' &&
            this.lastDisconnectReason !== 'replaced_by_new_client'
          ) {
            this.lastDisconnectReason = 'error';
          }
          this.handshakeReady = false;

          // An open WebSocket is not a usable Godot connection until the
          // application handshake succeeds.  Dispose this socket so a later
          // manual call or the reconnect timer starts from a clean transport.
          if (this.ws === socket && socket.readyState !== WebSocket.CLOSED) {
            socket.terminate();
          }
          reject(error instanceof Error ? error : new GodotConnectionError(errorMessage));
          return;
        }

        if (this.ws !== socket || socket.readyState !== WebSocket.OPEN || this.isClosing) {
          reject(new GodotConnectionError('Connection closed during handshake'));
          return;
        }

        this.handshakeReady = true;
        this.reconnectAttempt = 0;
        this.currentState = 'connected';
        if (this.reconnectTimeout) {
          clearTimeout(this.reconnectTimeout);
          this.reconnectTimeout = null;
        }
        this.startPingInterval();

        this.emit('connected');
        resolve();
      });

      socket.on('message', (data) => {
        this.handleMessage(data.toString());
      });

      socket.on('pong', () => {
        this.clearPongTimeout();
      });

      socket.on('close', (code, reason) => {
        // A failed attempt can finish closing after a caller has already
        // started a fresh one.  Its late close must not tear down that newer
        // socket or reject the newer attempt's pending requests.
        if (this.ws !== socket) {
          return;
        }

        const wasConnected = this.currentState === 'connected';
        this.handshakeReady = false;
        this.currentState = 'disconnected';

        if (code === CLOSE_CODE_ALREADY_CONNECTED) {
          this.lastDisconnectReason = 'rejected_another_client';
          this.rejectionCount++;
          // Back off in proportion to how many times we've been rejected so a
          // lingering second client doesn't busy-loop reconnecting every second
          // (each brief 'open' resets reconnectAttempt before this close fires).
          this.reconnectAttempt = Math.min(this.rejectionCount - 1, RECONNECT_DELAYS.length - 1);
          const reasonStr = reason?.toString() || 'Another client is already connected';
          logger.warningRateLimited(
            'rejected-another-client',
            'Another client holds the Godot bridge; will keep retrying',
            {
              reason: reasonStr,
              rejectionCount: this.rejectionCount,
            }
          );
        } else if (code === CLOSE_CODE_REPLACED) {
          // A newer client took over the bridge. Don't latch this connection
          // dead - keep reconnecting so it recovers automatically once the
          // other client disconnects (or is itself replaced).
          this.lastDisconnectReason = 'replaced_by_new_client';
          const reasonStr = reason?.toString() || 'Replaced by new client';
          logger.warningRateLimited(
            'replaced-by-new-client',
            'Connection was replaced by another client; will attempt to reconnect',
            {
              reason: reasonStr,
              suggestion: 'This client reconnects when the Godot bridge is free again.',
            }
          );
        } else if (code === CLOSE_CODE_STALE) {
          this.lastDisconnectReason = 'connection_lost';
          const reasonStr = reason?.toString() || 'Connection timed out (no activity)';
          logger.warning('Godot closed stale connection, will reconnect', {
            reason: reasonStr,
          });
        } else if (wasConnected) {
          this.lastDisconnectReason = 'connection_lost';
        } else if (this.lastDisconnectReason === 'never_connected') {
          this.lastDisconnectReason = 'connection_refused';
        }

        this.cleanup();
        this.ws = null;
        this.emit('disconnected');
        if (!wasConnected) {
          reject(new GodotConnectionError('Connection closed before handshake completed'));
        }
        if (this.autoReconnect && !this.isClosing) {
          this.scheduleReconnect();
        }
      });

      socket.on('error', (error) => {
        if (this.ws !== socket) {
          return;
        }
        this.lastErrorMessage = error.message;
        if (error.message.includes('ECONNREFUSED')) {
          this.lastDisconnectReason = 'connection_refused';
        } else {
          this.lastDisconnectReason = 'error';
        }
        this.emit('error', error);
        if (!this.isConnected) {
          reject(new GodotConnectionError(`Failed to connect: ${error.message}`));
        }
      });
    });
    this.connectPromise = attempt;
    const clearConnectPromise = () => {
      if (this.connectPromise === attempt) {
        this.connectPromise = null;
        this.rejectConnectAttempt = null;
      }
    };
    // Do not use an unobserved Promise.finally() here.  Its derived promise
    // rejects whenever the socket attempt rejects, which Node treats as an
    // unhandled rejection and can terminate the entire MCP stdio transport
    // exactly when the Godot editor is temporarily restarting.
    void attempt.then(clearConnectPromise, clearConnectPromise);
    return attempt;
  }

  disconnect(): void {
    this.isClosing = true;
    this.commandGeneration++;
    this.lastDisconnectReason = 'closed_normally';
    this.currentState = 'disconnected';
    this.cleanup();
    this.rejectConnectAttempt?.(
      new GodotConnectionError('Connection closed by caller before handshake completed')
    );
    if (this.ws) {
      const socket = this.ws;
      // Keep identity until the close callback finishes transport teardown.
      // The caller promise was rejected explicitly above, so this is also safe
      // while CONNECTING and cannot leave connectPromise pending forever.
      socket.close();
    }
  }

  // Long-running commands (game_time step, input sequence) pass an explicit
  // opts.timeoutMs derived from their in-game budget (see timeouts.ts); every
  // other command falls back to the quick default.
  async sendCommand<T = unknown>(
    command: string,
    params: Record<string, unknown> = {},
    opts: { timeoutMs?: number } = {}
  ): Promise<T> {
    const generation = this.commandGeneration;
    const queued = this.commandQueue.then(
      () => this.sendCommandForGeneration<T>(generation, command, params, opts),
      () => this.sendCommandForGeneration<T>(generation, command, params, opts)
    );
    // A rejected command must not poison the tail; the next caller is allowed
    // to reconnect and proceed after the failure has been observed.
    this.commandQueue = queued.then(
      () => undefined,
      () => undefined
    );
    return queued;
  }

  private async sendCommandForGeneration<T>(
    generation: number,
    command: string,
    params: Record<string, unknown>,
    opts: { timeoutMs?: number }
  ): Promise<T> {
    if (generation !== this.commandGeneration) {
      throw new GodotConnectionError(
        'Command was cancelled because the Godot connection generation closed'
      );
    }
    return this.sendCommandNow<T>(command, params, opts);
  }

  private async sendCommandNow<T = unknown>(
    command: string,
    params: Record<string, unknown>,
    opts: { timeoutMs?: number }
  ): Promise<T> {
    if (
      !this.isConnected
      && this.expectedProjectPath
      && !existsSync(join(this.expectedProjectPath, 'project.godot'))
    ) {
      throw new GodotConnectionError(
        `Candidate project is not ready: ${join(this.expectedProjectPath, 'project.godot')} `
        + 'does not exist. Create the minimal project first, then retry this MCP call. '
        + 'The Runtime is waiting to install the addon and launch the bound editor; '
        + 'this expected bootstrap state does not mean MCP is unavailable.'
      );
    }
    if (!this.isConnected) {
      await this.waitForStartupConnection();
    }
    if (!this.isConnected) {
      const diagnosticMessage = this.getDiagnosticMessage();
      throw new GodotConnectionError(`Not connected to Godot\n${diagnosticMessage}`);
    }

    const request = createRequest(command, params);
    const timeoutMs = opts.timeoutMs ?? QUICK_TIMEOUT_MS;

    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.pendingRequests.delete(request.id);
        reject(new GodotTimeoutError(command, timeoutMs));
      }, timeoutMs);

      this.pendingRequests.set(request.id, {
        resolve: resolve as (result: unknown) => void,
        reject,
        timeoutId,
      });

      this.ws!.send(JSON.stringify(request));
    });
  }

  /**
   * A GameLoop MCP process deliberately exposes its stdio tools before a cold
   * candidate has created project.godot and before the Runtime can launch the
   * bound editor. Keep that first real tool call pending for a finite period
   * instead of teaching the model that MCP is permanently unavailable after a
   * single ECONNREFUSED. Definitive handshake/configuration failures still
   * return immediately, and every later failure remains bounded by the same
   * deadline.
   */
  private async waitForStartupConnection(): Promise<void> {
    const deadline = Date.now() + this.startupWaitMs;
    do {
      try {
        await this.connect();
      } catch {
        // The diagnostic state below decides whether this is a recoverable
        // cold-start condition or a definitive handshake/configuration error.
      }
      if (this.isConnected || !this.isRecoverableStartupDisconnect()) {
        return;
      }
      const remainingMs = deadline - Date.now();
      if (remainingMs <= 0) {
        return;
      }
      await new Promise((resolve) => {
        setTimeout(resolve, Math.min(STARTUP_RETRY_DELAY_MS, remainingMs));
      });
    } while (!this.isConnected);
  }

  private isRecoverableStartupDisconnect(): boolean {
    return this.lastDisconnectReason === 'never_connected'
      || this.lastDisconnectReason === 'connection_refused'
      || this.lastDisconnectReason === 'connection_lost'
      || this.lastDisconnectReason === 'rejected_another_client'
      || this.lastDisconnectReason === 'replaced_by_new_client';
  }

  private async performHandshake(socket: WebSocket): Promise<void> {
    const request = createRequest('mcp_handshake', {
      server_version: this.serverVersion,
    });

    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.pendingRequests.delete(request.id);
        if (this.ws === socket) {
          this.handshakeResult = {
            addonVersion: 'unknown',
            godotVersion: 'unknown',
            projectPath: '',
            projectName: '',
            handshakeStatus: 'timeout',
          };
        }
        reject(new GodotTimeoutError('mcp_handshake', this.handshakeTimeoutMs));
      }, this.handshakeTimeoutMs);

      this.pendingRequests.set(request.id, {
        resolve: (result: unknown) => {
          try {
            if (typeof result !== 'object' || result === null) {
              throw new GodotConnectionError('Handshake returned no metadata object');
            }
            const data = result as Record<string, unknown>;
            const addonVersion =
              typeof data.addon_version === 'string' ? data.addon_version.trim() : '';
            const projectPath =
              typeof data.project_path === 'string' ? data.project_path.trim() : '';

            if (!addonVersion || addonVersion === 'unknown') {
              throw new GodotConnectionError('Handshake did not provide a valid addon version');
            }
            if (addonVersion !== this.serverVersion) {
              if (this.ws === socket) {
                this.handshakeResult = {
                  addonVersion,
                  godotVersion:
                    typeof data.godot_version === 'string' ? data.godot_version : 'unknown',
                  projectPath,
                  projectName: typeof data.project_name === 'string' ? data.project_name : '',
                  handshakeStatus: 'failed',
                };
                this.emit('version_mismatch', {
                  serverVersion: this.serverVersion,
                  addonVersion,
                  projectPath,
                });
              }
              throw new GodotConnectionError(
                `Godot addon version mismatch: expected ${this.serverVersion}, received ${addonVersion}`
              );
            }

            if (this.expectedProjectPath) {
              if (!projectPath) {
                throw new GodotConnectionError(
                  'Handshake did not provide a project path required by this session'
                );
              }
              let expectedRealPath: string;
              let actualRealPath: string;
              try {
                expectedRealPath = realpathSync(this.expectedProjectPath);
                actualRealPath = realpathSync(projectPath);
              } catch (error) {
                const message = error instanceof Error ? error.message : String(error);
                throw new GodotConnectionError(`Could not resolve handshake project path: ${message}`);
              }
              if (actualRealPath !== expectedRealPath) {
                throw new GodotConnectionError(
                  `Godot project mismatch: expected ${expectedRealPath}, received ${actualRealPath}`
                );
              }
            }

            if (this.ws === socket) {
              this.handshakeResult = {
                addonVersion,
                godotVersion:
                  typeof data.godot_version === 'string' ? data.godot_version : 'unknown',
                projectPath,
                projectName: typeof data.project_name === 'string' ? data.project_name : '',
                handshakeStatus: 'success',
              };
            }
            resolve();
          } catch (error) {
            reject(
              error instanceof Error
                ? error
                : new GodotConnectionError(`Invalid handshake response: ${String(error)}`)
            );
          }
        },
        reject,
        timeoutId,
      });

      socket.send(JSON.stringify(request));
    });
  }

  private handleMessage(data: string): void {
    let parsed: unknown;
    let responseId: string | undefined;

    try {
      parsed = JSON.parse(data);
      if (typeof parsed === 'object' && parsed !== null && 'id' in parsed) {
        responseId = String((parsed as Record<string, unknown>).id);
      }
    } catch {
      this.emit('error', new Error(`Invalid JSON from Godot: ${data}`));
      return;
    }

    const validationResult = ResponseSchema.safeParse(parsed);
    if (!validationResult.success) {
      const pending = responseId ? this.pendingRequests.get(responseId) : undefined;
      if (pending) {
        this.pendingRequests.delete(responseId!);
        clearTimeout(pending.timeoutId);
        pending.reject(new GodotConnectionError(`Malformed response: ${validationResult.error.message}`));
      } else {
        this.emit('error', new Error(`Invalid response (no matching request): ${data}`));
      }
      return;
    }

    const response = validationResult.data;
    const pending = this.pendingRequests.get(response.id);
    if (!pending) {
      return;
    }

    this.pendingRequests.delete(response.id);
    clearTimeout(pending.timeoutId);

    if (isSuccessResponse(response)) {
      pending.resolve(response.result);
    } else if (isErrorResponse(response)) {
      pending.reject(new GodotCommandError(response.error.code, response.error.message));
    }
  }

  private startPingInterval(): void {
    this.stopPingInterval();
    this.pingInterval = setInterval(() => {
      if (this.isConnected) {
        this.ws!.ping();
        this.pongTimeout = setTimeout(() => {
          this.emit('error', new Error('Pong timeout - connection may be dead'));
          this.ws?.terminate();
        }, PONG_TIMEOUT_MS);

        // Send application-level heartbeat so Godot can track activity
        // and detect stale connections from its side too
        if (!this.heartbeatPending) {
          this.heartbeatPending = true;
          // Heartbeats bypass the ordinary command queue.  A legitimate
          // game-time/input call may occupy that queue for up to 60 seconds,
          // while the addon declares a connection stale after 45 seconds of
          // application-level silence.  The heartbeat handler is immediate
          // and owns no shared per-command result slot, so this overlap keeps
          // the transport alive without reintroducing payload cross-talk.
          this.sendCommandNow('heartbeat', {}, { timeoutMs: QUICK_TIMEOUT_MS }).catch(() => {
            // Heartbeat failures are expected during disconnect - ignore
          }).finally(() => {
            this.heartbeatPending = false;
          });
        }
      }
    }, PING_INTERVAL_MS);
  }

  private stopPingInterval(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
    this.clearPongTimeout();
  }

  private clearPongTimeout(): void {
    if (this.pongTimeout) {
      clearTimeout(this.pongTimeout);
      this.pongTimeout = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return;
    }

    const delay = RECONNECT_DELAYS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS.length - 1)];
    this.reconnectAttempt++;

    this.emit('reconnecting', { attempt: this.reconnectAttempt, delay });

    this.reconnectTimeout = setTimeout(async () => {
      this.reconnectTimeout = null;
      try {
        await this.connect();
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        logger.warningRateLimited('reconnect-fail', 'Reconnection attempt failed', {
          attempt: this.reconnectAttempt,
          error: errorMessage,
        });
      }
    }, delay);
  }

  private cleanup(): void {
    this.stopPingInterval();
    this.handshakeReady = false;
    this.handshakeResult = null;

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    for (const pending of this.pendingRequests.values()) {
      clearTimeout(pending.timeoutId);
      pending.reject(new GodotConnectionError('Connection closed'));
    }
    this.pendingRequests.clear();
  }
}

let globalConnection: GodotConnection | null = null;

function parsePortEnv(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const port = parseInt(value, 10);
  if (Number.isNaN(port) || port < 1 || port > 65535) {
    logger.warning('Invalid GODOT_PORT, using default', { value, default: DEFAULT_PORT });
    return undefined;
  }
  return port;
}

function parseStartupWaitEnv(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const duration = Number(value);
  if (!Number.isFinite(duration) || duration < 0) {
    logger.warning('Invalid GODOT_MCP_STARTUP_WAIT_MS, using candidate-bound default', {
      value,
      default: DEFAULT_STARTUP_WAIT_MS,
    });
    return undefined;
  }
  return Math.min(duration, 180000);
}

export function getGodotConnection(): GodotConnection {
  if (!globalConnection) {
    const host = getTargetHost();
    const port = parsePortEnv(process.env.GODOT_PORT);
    globalConnection = new GodotConnection({
      host,
      port,
      expectedProjectPath: process.env.GODOT_MCP_EXPECTED_PROJECT,
      startupWaitMs: parseStartupWaitEnv(process.env.GODOT_MCP_STARTUP_WAIT_MS),
    });
  }
  return globalConnection;
}

export async function initializeConnection(): Promise<void> {
  const connection = getGodotConnection();
  const strategy = getConnectionStrategy(connection.port);

  // Log connection strategy at startup
  logger.info('Godot connection strategy', {
    environment: strategy.environment,
    targetHost: strategy.targetHost,
    wsUrl: strategy.wsUrl,
  });

  connection.on('connected', () => {
    logger.info('Connected to Godot');
  });

  connection.on('disconnected', () => {
    logger.warning('Disconnected from Godot');
  });

  connection.on('reconnecting', ({ attempt, delay }) => {
    logger.warningRateLimited('reconnect', 'Reconnecting to Godot', { attempt, delayMs: delay });
  });

  connection.on('error', (error) => {
    logger.error('Connection error', { error: error.message });
  });

  connection.on('version_mismatch', ({ serverVersion, addonVersion, projectPath }) => {
    console.error(`[godot-mcp] Version mismatch: server=${serverVersion}, addon=${addonVersion}`);
    console.error(`[godot-mcp] Update addon with: npx @satelliteoflove/godot-mcp --install-addon "${projectPath}"`);
    logger.notice('Version mismatch detected', {
      serverVersion,
      addonVersion,
      suggestion: 'Run: npx @satelliteoflove/godot-mcp --install-addon <project-path>',
    });
  });

  connection.on('handshake_failed', ({ error }) => {
    logger.error('Handshake failed', {
      error,
      advisory: 'The socket was rejected and will reconnect; update the addon or correct the expected project binding.',
    });
  });

  try {
    await connection.connect();
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    logger.warning('Initial connection failed, will retry', { error: errorMessage });
  }
}
