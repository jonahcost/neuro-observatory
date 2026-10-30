import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EegBlock, StreamMetadata, StreamStatus } from '@neuro-observatory/protocol';
import { EegStreamClient, type WebSocketLike } from './eegStreamClient';

class FakeSocket implements WebSocketLike {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closedWith: number | null = null;

  constructor(readonly url: string) {}

  open(): void {
    this.onopen?.(new Event('open'));
  }

  send(message: unknown): void {
    const data = typeof message === 'string' ? message : JSON.stringify(message);
    this.onmessage?.(new MessageEvent('message', { data }));
  }

  sendRaw(data: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data }));
  }

  serverClose(code = 1006): void {
    this.onclose?.(new CloseEvent('close', { code }));
  }

  close(code?: number): void {
    this.closedWith = code ?? 1000;
    this.serverClose(code ?? 1000);
  }
}

const CHANNELS = 2;

function metadata(streamId = 'stream-a'): StreamMetadata {
  return {
    type: 'stream.metadata',
    schemaVersion: 2,
    streamId,
    device: { kind: 'synthetic', model: 'test-synth', deviceId: 'synthetic-0', adapterVersion: '1.0.0' },
    provenance: {
      kind: 'synthetic',
      generator: 'test',
      generatorVersion: '1',
      seed: 42,
      configHash: `sha256:${'0'.repeat(64)}`,
    },
    nominalSampleRateHz: 125,
    layout: 'channel-major',
    channels: Array.from({ length: CHANNELS }, (_, index) => ({
      index,
      label: `Ch${index}`,
      type: 'EEG' as const,
      unit: 'uV' as const,
      reference: 'synthetic',
    })),
    timebase: {
      clock: 'engine-monotonic',
      unit: 'us',
      timestampSource: 'synthetic-nominal',
      anchor: { monotonicUs: 1_000_000, unixTimeUs: 1_793_366_580_000_000 },
    },
  };
}

function block(blockSequence: number, firstSampleIndex: number, overrides: Partial<EegBlock> = {}): EegBlock {
  return {
    type: 'eeg.block',
    schemaVersion: 2,
    streamId: 'stream-a',
    blockSequence,
    firstSampleIndex,
    sampleCount: 5,
    firstSampleTimeUs: 1_000_000 + firstSampleIndex * 8000,
    droppedSamplesBefore: 0,
    samples: Array.from({ length: CHANNELS }, () => [1, 2, 3, 4, 5]),
    ...overrides,
  };
}

function status(state: StreamStatus['state'] = 'streaming'): StreamStatus {
  return {
    type: 'stream.status',
    schemaVersion: 2,
    streamId: 'stream-a',
    state,
    atUs: 2_000_000,
    counters: {
      samplesAcquired: 10,
      acquisitionGapSamples: 0,
      rejectedBlocks: 0,
      blocksDroppedForClient: 0,
      effectiveSampleRateHz: 125,
    },
    error: null,
  };
}

describe('EegStreamClient', () => {
  let sockets: FakeSocket[];
  let client: EegStreamClient;

  const latest = () => sockets[sockets.length - 1];

  beforeEach(() => {
    vi.useFakeTimers();
    sockets = [];
    client = new EegStreamClient({
      url: 'ws://test/ws/v2/eeg',
      createSocket: (url) => {
        const socket = new FakeSocket(url);
        sockets.push(socket);
        return socket;
      },
      random: () => 1,
      initialReconnectDelayMs: 100,
      maxReconnectDelayMs: 1000,
      notifyIntervalMs: 50,
    });
  });

  afterEach(() => {
    client.stop();
    vi.useRealTimers();
  });

  it('connects, accepts validated metadata and blocks, and delivers samples outside snapshots', () => {
    const received: EegBlock[] = [];
    client.onBlock((b) => received.push(b));
    client.start();
    expect(client.getSnapshot().connection).toBe('connecting');
    latest().open();
    latest().send(metadata());
    latest().send(status());
    latest().send(block(0, 0));
    latest().send(block(1, 5));

    const snap = client.getSnapshot();
    expect(snap.connection).toBe('open');
    expect(snap.health).toBe('live');
    expect(snap.metadata?.streamId).toBe('stream-a');
    expect(received.map((b) => b.firstSampleIndex)).toEqual([0, 5]);
    expect(Object.keys(snap)).not.toContain('samples');

    vi.advanceTimersByTime(50);
    const later = client.getSnapshot();
    expect(later.lastBlock).toMatchObject({ blockSequence: 1, firstSampleIndex: 5, sampleCount: 5 });
    expect(later.engineStatus?.state).toBe('streaming');
    expect(later.integrity.blocksAccepted).toBe(2);
  });

  it('rejects malformed, schema-invalid and semantically invalid messages without disconnecting', () => {
    const received: EegBlock[] = [];
    client.onBlock((b) => received.push(b));
    client.start();
    latest().open();
    latest().send(metadata());
    latest().sendRaw('{not json');
    latest().send({ ...block(0, 0), samplesUv: [[0]] });
    latest().send(block(0, 0, { samples: [[1, 2, 3, 4, 5]] })); // 1 row, metadata declares 2
    latest().sendRaw(new ArrayBuffer(4));

    const snap = client.getSnapshot();
    expect(snap.invalidMessages).toBe(4);
    expect(snap.lastProtocolError?.kind).toBe('json');
    expect(received).toHaveLength(0);
    expect(latest().closedWith).toBeNull();
    expect(snap.connection).toBe('open');
  });

  it('counts acquisition gaps, transport drops, duplicates and out-of-order blocks', () => {
    const received: number[] = [];
    client.onBlock((b) => received.push(b.blockSequence));
    client.start();
    latest().open();
    latest().send(metadata());
    latest().send(block(0, 0));
    latest().send(block(1, 8, { droppedSamplesBefore: 3 }));
    latest().send(block(1, 8, { droppedSamplesBefore: 3 }));
    latest().send(block(3, 18)); // block 2 (samples 13-17) lost in transport
    latest().send(block(2, 13)); // arrives late

    vi.advanceTimersByTime(50);

    expect(received).toEqual([0, 1, 3]);
    expect(client.getSnapshot().integrity).toMatchObject({
      acquisitionGapSamples: 3,
      transportDroppedBlocks: 1,
      transportGapSamples: 5,
      duplicateBlocks: 1,
      outOfOrderBlocks: 1,
    });
  });

  it('marks the stream stale when blocks stop arriving', () => {
    client.start();
    latest().open();
    latest().send(metadata());
    latest().send(block(0, 0));
    expect(client.getSnapshot().health).toBe('live');
    vi.advanceTimersByTime(999);
    expect(client.getSnapshot().health).toBe('live');
    vi.advanceTimersByTime(1);
    expect(client.getSnapshot().health).toBe('stale');
    latest().send(block(1, 5));
    expect(client.getSnapshot().health).toBe('live');
  });

  it('reconnects with capped exponential backoff and resumes the same stream', () => {
    client.start();
    latest().open();
    latest().send(metadata());
    latest().send(status());
    latest().send(block(0, 0));

    latest().serverClose();
    let snap = client.getSnapshot();
    expect(snap.connection).toBe('reconnecting');
    expect(snap.reconnectAttempt).toBe(1);
    expect(snap.metadata).toBeNull();
    expect(snap.engineStatus).toBeNull();
    expect(sockets).toHaveLength(1);

    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(2);
    latest().serverClose();
    vi.advanceTimersByTime(199);
    expect(sockets).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(3);
    for (let i = 0; i < 5; i += 1) {
      latest().serverClose();
      vi.advanceTimersByTime(1000);
    }
    expect(sockets).toHaveLength(8); // delays capped at maxReconnectDelayMs

    latest().open();
    latest().send(metadata());
    latest().send(block(4, 20));
    vi.advanceTimersByTime(50);
    snap = client.getSnapshot();
    expect(snap.connection).toBe('open');
    expect(snap.reconnectAttempt).toBe(0);
    expect(snap.integrity.streamsStarted).toBe(1);
    expect(snap.integrity.transportDroppedBlocks).toBe(3);
  });

  it('treats new metadata as a new stream', () => {
    client.start();
    latest().open();
    latest().send(metadata('stream-a'));
    latest().send(block(0, 0));
    latest().send(metadata('stream-b'));
    latest().send(block(0, 0, { streamId: 'stream-b' }));
    vi.advanceTimersByTime(50);
    const snap = client.getSnapshot();
    expect(snap.integrity.streamsStarted).toBe(2);
    expect(snap.lastBlock?.streamId).toBe('stream-b');
  });

  it('enters the incompatible state on an unsupported protocol version and backs off', () => {
    client.start();
    latest().open();
    latest().send({ schemaVersion: 1, deviceId: 'simulated-eeg', samplesUv: [[0]] });
    const snap = client.getSnapshot();
    expect(snap.connection).toBe('incompatible');
    expect(snap.lastProtocolError?.kind).toBe('unsupported-version');
    expect(sockets[0].closedWith).toBe(1002);
    vi.advanceTimersByTime(999);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);
    expect(client.getSnapshot().connection).toBe('incompatible');
  });

  it('stop() closes the socket, cancels timers and detaches handlers; start() resumes', () => {
    const listener = vi.fn();
    client.subscribe(listener);
    client.start();
    latest().open();
    latest().send(metadata());
    latest().send(block(0, 0));
    client.stop();
    const first = sockets[0];
    expect(first.closedWith).toBe(1000);
    expect(first.onmessage).toBeNull();
    expect(client.getSnapshot().connection).toBe('stopped');
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
    expect(client.getSnapshot().health).toBe('waiting');

    client.start();
    expect(sockets).toHaveLength(2);
    expect(listener).toHaveBeenCalled();
  });

  it('retries when the socket cannot be constructed', () => {
    let attempts = 0;
    const failing = new EegStreamClient({
      createSocket: () => {
        attempts += 1;
        throw new Error('invalid url');
      },
      random: () => 1,
      initialReconnectDelayMs: 100,
    });
    failing.start();
    expect(failing.getSnapshot().connection).toBe('reconnecting');
    vi.advanceTimersByTime(100);
    expect(attempts).toBe(2);
    failing.stop();
  });
});
