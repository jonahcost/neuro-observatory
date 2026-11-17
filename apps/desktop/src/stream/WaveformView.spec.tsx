import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { emptyIntegrityCounters, type EegBlock, type StreamMetadata } from '@neuro-observatory/protocol';
import type { EegStreamSnapshot } from './eegStreamClient';
import { WaveformView } from './WaveformView';
import { WaveformBuffer } from './waveformBuffer';

const LABELS = ['Fp1', 'Fp2', 'F3', 'F4', 'F7', 'F8', 'C3', 'C4', 'Cz', 'P3', 'P4', 'T7', 'T8', 'O1', 'O2', 'Pz'];

function metadata(labels: string[], streamId = 'stream-a'): StreamMetadata {
  return {
    type: 'stream.metadata',
    schemaVersion: 2,
    streamId,
    device: { kind: 'synthetic', model: 'neuro-observatory-synthetic-eeg', deviceId: 'synthetic-0', adapterVersion: '1.0.0' },
    provenance: {
      kind: 'synthetic',
      generator: 'test',
      generatorVersion: '1',
      seed: 0,
      configHash: `sha256:${'cd'.repeat(32)}`,
    },
    nominalSampleRateHz: 125,
    layout: 'channel-major',
    channels: labels.map((label, index) => ({ index, label, type: 'EEG' as const, unit: 'uV' as const, reference: 'synthetic' })),
    timebase: {
      clock: 'engine-monotonic',
      unit: 'us',
      timestampSource: 'synthetic-nominal',
      anchor: { monotonicUs: 0, unixTimeUs: 0 },
    },
  };
}

function block(meta: StreamMetadata, firstSampleIndex: number, samples: number[][], overrides: Partial<EegBlock> = {}): EegBlock {
  return {
    type: 'eeg.block',
    schemaVersion: 2,
    streamId: meta.streamId,
    blockSequence: 0,
    firstSampleIndex,
    sampleCount: samples[0]?.length ?? 0,
    firstSampleTimeUs: firstSampleIndex * 8_000,
    droppedSamplesBefore: 0,
    samples,
    ...overrides,
  };
}

function snapshot(overrides: Partial<EegStreamSnapshot> = {}): EegStreamSnapshot {
  return {
    connection: 'open',
    health: 'live',
    metadata: metadata(LABELS),
    engineStatus: null,
    lastBlock: null,
    integrity: emptyIntegrityCounters(),
    invalidMessages: 0,
    lastProtocolError: null,
    reconnectAttempt: 0,
    listenerErrors: 0,
    ...overrides,
  };
}

describe('WaveformView', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Reflect.deleteProperty(HTMLCanvasElement.prototype, 'clientWidth');
    Reflect.deleteProperty(HTMLCanvasElement.prototype, 'clientHeight');
  });

  it('shows stream-order labels, synthetic provenance, and the connection state', () => {
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const buffer = new WaveformBuffer();
    const meta = metadata(LABELS);
    buffer.append(
      block(
        meta,
        0,
        meta.channels.map(() => [0]),
      ),
      meta,
      0,
    );

    render(<WaveformView buffer={buffer} snapshot={snapshot()} />);

    const region = screen.getByRole('region', { name: 'EEG waveforms' });
    const labels = [...region.querySelectorAll('li')].map((item) => item.textContent).filter((text) => text);
    expect(labels).toEqual(LABELS);
    expect(region.textContent).toContain('Synthetic signal — generated, not measured from a person.');
    expect(region.querySelector('details')?.textContent ?? '').not.toContain('not measured');
    expect(region.textContent).toContain('±100 µV');
    expect(screen.getByRole('status').textContent).toContain('Connected');
    expect(screen.getByRole('status').textContent).toContain('Live');

    render(<WaveformView buffer={buffer} snapshot={snapshot({ connection: 'reconnecting', reconnectAttempt: 2, health: 'waiting' })} />);
    expect(screen.getAllByRole('status').some((node) => node.textContent?.includes('Disconnected — reconnecting (attempt 2)'))).toBe(true);
  });

  it('starts a new stroke after a gap instead of drawing across it', () => {
    const ops: string[] = [];
    let pending: FrameRequestCallback | null = null;
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      pending = callback;
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {
      pending = null;
    });
    Object.defineProperty(HTMLCanvasElement.prototype, 'clientWidth', { configurable: true, get: () => 800 });
    Object.defineProperty(HTMLCanvasElement.prototype, 'clientHeight', { configurable: true, get: () => 480 });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => {
      return {
        setTransform() {
          return undefined;
        },
        clearRect() {
          return undefined;
        },
        save() {
          return undefined;
        },
        restore() {
          return undefined;
        },
        beginPath() {
          return undefined;
        },
        rect() {
          return undefined;
        },
        clip() {
          return undefined;
        },
        moveTo() {
          ops.push('move');
        },
        lineTo() {
          ops.push('line');
        },
        stroke() {
          ops.push('stroke');
        },
        fillRect() {
          return undefined;
        },
        fillText() {
          return undefined;
        },
        strokeStyle: '',
        fillStyle: '',
        lineWidth: 1,
        font: '',
      } as unknown as CanvasRenderingContext2D;
    });

    const buffer = new WaveformBuffer();
    const meta = metadata(['Fp1']);
    buffer.append(block(meta, 0, [[1, 1]]), meta, 0);
    buffer.append(block(meta, 3, [[2, 2]], { blockSequence: 1, droppedSamplesBefore: 1 }), meta, 24);

    const { unmount } = render(<WaveformView buffer={buffer} snapshot={snapshot({ metadata: meta })} />);
    act(() => {
      pending?.(0);
    });

    expect(ops).toEqual(['move', 'line', 'move', 'line', 'stroke']);
    unmount();
  });

  it('draws a one-sample run and names a new stream separately from a backwards source clock', () => {
    const ops: string[] = [];
    let pending: FrameRequestCallback | null = null;
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      pending = callback;
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {
      pending = null;
    });
    Object.defineProperty(HTMLCanvasElement.prototype, 'clientWidth', { configurable: true, get: () => 800 });
    Object.defineProperty(HTMLCanvasElement.prototype, 'clientHeight', { configurable: true, get: () => 480 });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => {
      return {
        setTransform() {
          return undefined;
        },
        clearRect() {
          return undefined;
        },
        save() {
          return undefined;
        },
        restore() {
          return undefined;
        },
        beginPath() {
          return undefined;
        },
        rect() {
          return undefined;
        },
        clip() {
          return undefined;
        },
        moveTo() {
          ops.push('move');
        },
        lineTo() {
          ops.push('line');
        },
        stroke() {
          ops.push('stroke');
        },
        fillRect() {
          return undefined;
        },
        fillText() {
          return undefined;
        },
        strokeStyle: '',
        fillStyle: '',
        lineWidth: 1,
        font: '',
      } as unknown as CanvasRenderingContext2D;
    });

    const buffer = new WaveformBuffer();
    const meta = metadata(['Fp1']);
    buffer.append(block(meta, 0, [[4]], { firstSampleTimeUs: 1_000_000 }), meta, 0);
    const restarted = metadata(['Fp1'], 'stream-b');
    buffer.append(block(restarted, 0, [[9]], { firstSampleTimeUs: 0 }), restarted, 0);

    const { unmount } = render(<WaveformView buffer={buffer} snapshot={snapshot({ metadata: restarted })} />);
    const restartedRegion = screen.getByRole('region', { name: 'EEG waveforms' });
    expect(restartedRegion.textContent).toContain('Engine clock restarted (new stream).');
    expect(restartedRegion.querySelector('details')?.textContent ?? '').not.toContain('Engine clock restarted');

    const same = metadata(['Fp1']);
    const clockBuffer = new WaveformBuffer();
    clockBuffer.append(block(same, 0, [[4]], { firstSampleTimeUs: 1_000_000 }), same, 0);
    clockBuffer.append(block(same, 1, [[9]], { blockSequence: 1, firstSampleTimeUs: 0 }), same, 1_000);
    render(<WaveformView buffer={clockBuffer} snapshot={snapshot({ metadata: same })} />);
    const captions = screen.getAllByRole('region', { name: 'EEG waveforms' }).map((node) => node.textContent ?? '');
    expect(captions.some((text) => text.includes('Source clock moved backwards on this stream.'))).toBe(true);
    expect(captions.some((text) => text.includes('Source clock moved backwards') && text.includes('new stream'))).toBe(false);

    unmount();
    ops.length = 0;
    const single = new WaveformBuffer();
    single.append(block(meta, 0, [[3]]), meta, 0);
    render(<WaveformView buffer={single} snapshot={snapshot({ metadata: meta })} />);
    act(() => {
      pending?.(0);
    });
    expect(ops).toEqual(['move', 'line', 'stroke']);
  });

  it('selects a channel with a pressed state that is not only a color', () => {
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const buffer = new WaveformBuffer();
    const meta = metadata(LABELS);
    buffer.append(
      block(
        meta,
        0,
        meta.channels.map(() => [0]),
      ),
      meta,
      0,
    );
    const onSelect = vi.fn();
    const { rerender } = render(<WaveformView buffer={buffer} snapshot={snapshot()} onSelectChannel={onSelect} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cz' }));
    expect(onSelect).toHaveBeenCalledWith('Cz');
    rerender(<WaveformView buffer={buffer} snapshot={snapshot()} selectedChannel="Cz" onSelectChannel={onSelect} />);
    const selected = screen.getByRole('button', { name: 'Cz' });
    expect(selected.getAttribute('aria-pressed')).toBe('true');
    expect(selected.className).not.toBe('');
    expect(screen.getByRole('button', { name: 'Fp1' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('clears the selection when layout identity changes and the labels stay', () => {
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const buffer = new WaveformBuffer();
    const meta = metadata(LABELS);
    buffer.append(
      block(
        meta,
        0,
        meta.channels.map(() => [0]),
      ),
      meta,
      0,
    );
    const onSelect = vi.fn();
    render(<WaveformView buffer={buffer} snapshot={snapshot()} selectedChannel="Cz" onSelectChannel={onSelect} />);
    const next = metadata(LABELS, 'stream-b');
    next.channels = next.channels.map((channel) => ({ ...channel, reference: 'SRB2' }));
    act(() => {
      buffer.append(
        block(
          next,
          0,
          next.channels.map(() => [1]),
        ),
        next,
        500,
      );
    });
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it('keeps the selection when a new stream reuses the layout', () => {
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const buffer = new WaveformBuffer();
    const meta = metadata(LABELS);
    buffer.append(
      block(
        meta,
        0,
        meta.channels.map(() => [0]),
        { firstSampleTimeUs: 1_000_000 },
      ),
      meta,
      0,
    );
    const onSelect = vi.fn();
    render(<WaveformView buffer={buffer} snapshot={snapshot()} selectedChannel="Cz" onSelectChannel={onSelect} />);
    const restarted = metadata(LABELS, 'stream-b');
    act(() => {
      buffer.append(
        block(
          restarted,
          0,
          restarted.channels.map(() => [1]),
          { firstSampleTimeUs: 0 },
        ),
        restarted,
        1_000,
      );
    });
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Cz' }).getAttribute('aria-pressed')).toBe('true');
  });
});
