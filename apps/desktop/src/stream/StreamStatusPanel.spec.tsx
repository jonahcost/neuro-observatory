import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { emptyIntegrityCounters, type StreamMetadata } from '@neuro-observatory/protocol';
import type { EegStreamSnapshot } from './eegStreamClient';
import { StreamStatusPanel } from './StreamStatusPanel';
import { engineUrlFromEnv } from './useEegStream';

const metadata: StreamMetadata = {
  type: 'stream.metadata',
  schemaVersion: 2,
  streamId: 'stream-a',
  device: { kind: 'synthetic', model: 'neuro-observatory-synthetic-eeg', deviceId: 's0', adapterVersion: '1.0.0' },
  provenance: { kind: 'synthetic', generator: 'g', generatorVersion: '1', seed: 7, configHash: `sha256:${'a'.repeat(64)}` },
  nominalSampleRateHz: 125,
  layout: 'channel-major',
  channels: Array.from({ length: 16 }, (_, index) => ({
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
    anchor: { monotonicUs: 0, unixTimeUs: 0 },
  },
};

function snapshot(overrides: Partial<EegStreamSnapshot> = {}): EegStreamSnapshot {
  return {
    connection: 'open',
    health: 'live',
    metadata,
    engineStatus: null,
    lastBlock: { streamId: 'stream-a', blockSequence: 3, firstSampleIndex: 75, sampleCount: 25, firstSampleTimeUs: 0 },
    integrity: { ...emptyIntegrityCounters(), acquisitionGapSamples: 4, transportDroppedBlocks: 2 },
    invalidMessages: 1,
    lastProtocolError: null,
    reconnectAttempt: 0,
    listenerErrors: 2,
    ...overrides,
  };
}

describe('StreamStatusPanel', () => {
  it('labels synthetic data and shows units, rate and integrity counters', () => {
    render(<StreamStatusPanel snapshot={snapshot()} />);
    expect(screen.getByTestId('provenance').textContent).toContain('Synthetic signal');
    expect(screen.getByTestId('provenance').textContent).toContain('seed 7');
    expect(screen.getByText(/16 × µV, reference synthetic, channel-major/)).toBeTruthy();
    expect(screen.getByText(/125 Hz nominal/)).toBeTruthy();
    expect(screen.getByText('99')).toBeTruthy();
    const integrity = screen.getByTestId('integrity').textContent ?? '';
    expect(integrity).toContain('acquisition gaps 4 samples');
    expect(integrity).toContain('dropped in transport 2 blocks');
    expect(integrity).toContain('invalid messages 1');
    expect(integrity).toContain('sample consumer errors 2');
  });

  it('shows waiting, stale, reconnecting and incompatible states', () => {
    const { rerender } = render(<StreamStatusPanel snapshot={snapshot({ connection: 'connecting', health: 'waiting', metadata: null, lastBlock: null })} />);
    expect(screen.getByRole('status').textContent).toContain('Connecting');
    expect(screen.getByTestId('provenance').textContent).toBe('Unknown');

    rerender(<StreamStatusPanel snapshot={snapshot({ health: 'stale' })} />);
    expect(screen.getByRole('status').textContent).toContain('Stale');

    rerender(<StreamStatusPanel snapshot={snapshot({ connection: 'reconnecting', reconnectAttempt: 3 })} />);
    expect(screen.getByRole('status').textContent).toContain('reconnecting (attempt 3)');

    rerender(
      <StreamStatusPanel
        snapshot={snapshot({
          connection: 'incompatible',
          lastProtocolError: { kind: 'unsupported-version', detail: 'schemaVersion 1 is not supported (expected 2)' },
        })}
      />,
    );
    expect(screen.getByRole('status').textContent).toContain('Incompatible');
    expect(screen.getByRole('alert').textContent).toContain('unsupported-version');
  });

  it('labels device provenance distinctly from synthetic data', () => {
    render(<StreamStatusPanel snapshot={snapshot({ metadata: { ...metadata, provenance: { kind: 'device' } } })} />);
    expect(screen.getByTestId('provenance').textContent).toBe('Device measurement (scalp EEG)');
  });
});

describe('engineUrlFromEnv', () => {
  it('uses VITE_NEURO_ENGINE_WS_URL when set and non-empty', () => {
    expect(engineUrlFromEnv({ VITE_NEURO_ENGINE_WS_URL: 'ws://127.0.0.1:9000/ws/v2/eeg' })).toBe(
      'ws://127.0.0.1:9000/ws/v2/eeg',
    );
    expect(engineUrlFromEnv({ VITE_NEURO_ENGINE_WS_URL: '' })).toBeUndefined();
    expect(engineUrlFromEnv({})).toBeUndefined();
  });
});
