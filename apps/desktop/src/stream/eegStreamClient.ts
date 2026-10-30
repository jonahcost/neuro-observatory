import {
  StreamIntegrityTracker,
  parseServerMessage,
  type EegBlock,
  type IntegrityCounters,
  type ParseError,
  type StreamMetadata,
  type StreamStatus,
} from '@neuro-observatory/protocol';

export const DEFAULT_ENGINE_WS_URL = 'ws://127.0.0.1:8000/ws/v2/eeg';

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'incompatible' | 'stopped';
export type StreamHealth = 'waiting' | 'live' | 'stale';

export interface LastBlockInfo {
  streamId: string;
  blockSequence: number;
  firstSampleIndex: number;
  sampleCount: number;
  firstSampleTimeUs: number;
}

export interface EegStreamSnapshot {
  connection: ConnectionState;
  health: StreamHealth;
  metadata: StreamMetadata | null;
  engineStatus: StreamStatus | null;
  lastBlock: LastBlockInfo | null;
  integrity: IntegrityCounters;
  invalidMessages: number;
  lastProtocolError: ParseError | null;
  reconnectAttempt: number;
  /** `onBlock` listeners that threw; each listener is isolated from the others. */
  listenerErrors: number;
}

/** The subset of the browser WebSocket used by the client (injectable for tests). */
export interface WebSocketLike {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  close(code?: number, reason?: string): void;
}

export interface EegStreamClientOptions {
  url?: string;
  createSocket?: (url: string) => WebSocketLike;
  initialReconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
  /** Fixed stale threshold; by default 3 block durations, at least 1 s. */
  staleAfterMs?: number;
  /** Minimum interval between snapshot notifications caused by data blocks. */
  notifyIntervalMs?: number;
  random?: () => number;
}

export type BlockListener = (block: EegBlock, metadata: StreamMetadata) => void;

const CLOSE_NORMAL = 1000;
const CLOSE_PROTOCOL_ERROR = 1002;

/**
 * Validated protocol v2 stream client. Owns transport, validation, integrity
 * tracking, reconnection and staleness; independent of React and rendering.
 * Samples are delivered only through `onBlock` and never stored in snapshots.
 */
export class EegStreamClient {
  private readonly url: string;
  private readonly createSocket: (url: string) => WebSocketLike;
  private readonly initialDelayMs: number;
  private readonly maxDelayMs: number;
  private readonly fixedStaleAfterMs: number | undefined;
  private readonly notifyIntervalMs: number;
  private readonly random: () => number;

  private socket: WebSocketLike | null = null;
  private running = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private staleTimer: ReturnType<typeof setTimeout> | null = null;
  private notifyTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly tracker = new StreamIntegrityTracker();
  private readonly listeners = new Set<() => void>();
  private readonly blockListeners = new Set<BlockListener>();

  private connection: ConnectionState = 'idle';
  private health: StreamHealth = 'waiting';
  private metadata: StreamMetadata | null = null;
  private engineStatus: StreamStatus | null = null;
  private lastBlock: LastBlockInfo | null = null;
  private invalidMessages = 0;
  private lastProtocolError: ParseError | null = null;
  private reconnectAttempt = 0;
  private listenerErrors = 0;
  private snapshot: EegStreamSnapshot;

  constructor(options: EegStreamClientOptions = {}) {
    this.url = options.url ?? DEFAULT_ENGINE_WS_URL;
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    this.initialDelayMs = options.initialReconnectDelayMs ?? 500;
    this.maxDelayMs = options.maxReconnectDelayMs ?? 10_000;
    this.fixedStaleAfterMs = options.staleAfterMs;
    this.notifyIntervalMs = options.notifyIntervalMs ?? 200;
    this.random = options.random ?? Math.random;
    this.snapshot = this.buildSnapshot();
  }

  start(): void {
    if (this.running) {
      return;
    }
    this.running = true;
    this.reconnectAttempt = 0;
    this.connect();
  }

  stop(): void {
    this.running = false;
    this.clearTimer('reconnectTimer');
    this.clearTimer('staleTimer');
    this.clearTimer('notifyTimer');
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      this.detach(socket);
      socket.close(CLOSE_NORMAL, 'client stopped');
    }
    this.connection = 'stopped';
    this.metadata = null;
    this.engineStatus = null;
    this.health = 'waiting';
    this.notifyNow();
  }

  getSnapshot = (): EegStreamSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  onBlock(listener: BlockListener): () => void {
    this.blockListeners.add(listener);
    return () => this.blockListeners.delete(listener);
  }

  private connect(): void {
    this.connection = this.reconnectAttempt === 0 ? 'connecting' : this.connection;
    this.notifyNow();
    let socket: WebSocketLike;
    try {
      socket = this.createSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      this.connection = 'open';
      this.notifyNow();
    };
    socket.onmessage = (event) => this.handleMessage(event.data);
    socket.onerror = () => undefined; // a close event always follows
    socket.onclose = () => {
      this.detach(socket);
      if (this.socket === socket) {
        this.socket = null;
      }
      this.metadata = null;
      this.engineStatus = null;
      this.health = 'waiting';
      this.clearTimer('staleTimer');
      this.scheduleReconnect();
    };
  }

  private detach(socket: WebSocketLike): void {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
  }

  private scheduleReconnect(): void {
    if (!this.running) {
      return;
    }
    this.reconnectAttempt += 1;
    if (this.connection !== 'incompatible') {
      this.connection = 'reconnecting';
    }
    const base =
      this.connection === 'incompatible'
        ? this.maxDelayMs
        : Math.min(this.maxDelayMs, this.initialDelayMs * 2 ** (this.reconnectAttempt - 1));
    const delay = base * (0.5 + 0.5 * this.random());
    this.clearTimer('reconnectTimer');
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
    this.notifyNow();
  }

  private handleMessage(data: unknown): void {
    if (typeof data !== 'string') {
      this.recordInvalid({ kind: 'json', detail: 'binary frames are not part of protocol v2' });
      return;
    }
    const result = parseServerMessage(data, { metadata: this.metadata });
    if (!result.ok) {
      this.recordInvalid(result.error);
      if (result.error.kind === 'unsupported-version') {
        this.connection = 'incompatible';
        this.socket?.close(CLOSE_PROTOCOL_ERROR, 'unsupported protocol version');
      }
      return;
    }
    const message = result.message;
    switch (message.type) {
      case 'stream.metadata':
        this.tracker.onMetadata(message);
        this.metadata = message;
        this.connection = 'open';
        this.reconnectAttempt = 0;
        this.notifyNow();
        return;
      case 'stream.status':
        this.engineStatus = message;
        this.scheduleNotify();
        return;
      case 'eeg.block':
        this.handleBlock(message);
        return;
    }
  }

  private handleBlock(block: EegBlock): void {
    const metadata = this.metadata;
    if (this.tracker.onBlock(block) !== 'accepted' || metadata === null) {
      this.scheduleNotify();
      return;
    }
    this.lastBlock = {
      streamId: block.streamId,
      blockSequence: block.blockSequence,
      firstSampleIndex: block.firstSampleIndex,
      sampleCount: block.sampleCount,
      firstSampleTimeUs: block.firstSampleTimeUs,
    };
    const becameLive = this.health !== 'live';
    this.health = 'live';
    this.armStaleTimer(block, metadata);
    for (const listener of this.blockListeners) {
      try {
        listener(block, metadata);
      } catch (error) {
        this.listenerErrors += 1;
        console.error('EegStreamClient: an onBlock listener threw', error);
      }
    }
    if (becameLive) {
      this.notifyNow();
    } else {
      this.scheduleNotify();
    }
  }

  private armStaleTimer(block: EegBlock, metadata: StreamMetadata): void {
    const blockDurationMs = (block.sampleCount / metadata.nominalSampleRateHz) * 1000;
    const staleAfterMs = this.fixedStaleAfterMs ?? Math.max(1000, 3 * blockDurationMs);
    this.clearTimer('staleTimer');
    this.staleTimer = setTimeout(() => {
      this.staleTimer = null;
      this.health = 'stale';
      this.notifyNow();
    }, staleAfterMs);
  }

  private recordInvalid(error: ParseError): void {
    this.invalidMessages += 1;
    this.lastProtocolError = error;
    this.notifyNow();
  }

  private clearTimer(name: 'reconnectTimer' | 'staleTimer' | 'notifyTimer'): void {
    const timer = this[name];
    if (timer !== null) {
      clearTimeout(timer);
      this[name] = null;
    }
  }

  private scheduleNotify(): void {
    if (this.notifyTimer !== null) {
      return;
    }
    this.notifyTimer = setTimeout(() => {
      this.notifyTimer = null;
      this.notifyNow();
    }, this.notifyIntervalMs);
  }

  private notifyNow(): void {
    this.clearTimer('notifyTimer');
    this.snapshot = this.buildSnapshot();
    for (const listener of this.listeners) {
      listener();
    }
  }

  private buildSnapshot(): EegStreamSnapshot {
    return {
      connection: this.connection,
      health: this.health,
      metadata: this.metadata,
      engineStatus: this.engineStatus,
      lastBlock: this.lastBlock,
      integrity: this.tracker.snapshot(),
      invalidMessages: this.invalidMessages,
      lastProtocolError: this.lastProtocolError,
      reconnectAttempt: this.reconnectAttempt,
      listenerErrors: this.listenerErrors,
    };
  }
}
