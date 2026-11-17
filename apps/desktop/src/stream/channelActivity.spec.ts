import type { EegBlock, StreamMetadata } from '@neuro-observatory/protocol';
import { describe, expect, it } from 'vitest';
import { ACTIVITY_UPDATE_INTERVAL_MS, ChannelActivity, RMS_FULL_SCALE_UV, STALE_FADE_SECONDS } from './channelActivity';

function metadata(streamId: string, labels: readonly string[], rateHz: number): StreamMetadata {
  return {
    type: 'stream.metadata',
    schemaVersion: 2,
    streamId,
    device: { kind: 'synthetic', model: 'neuro-observatory-synthetic-eeg', deviceId: 'synthetic-0', adapterVersion: '1.0.0' },
    provenance: {
      kind: 'synthetic',
      generator: 'neuro_engine.acquisition.synthetic',
      generatorVersion: '1',
      seed: 0,
      configHash: `sha256:${'ab'.repeat(32)}`,
    },
    nominalSampleRateHz: rateHz,
    layout: 'channel-major',
    channels: labels.map((label, index) => ({ index, label, type: 'EEG', unit: 'uV', reference: 'synthetic' })),
    timebase: {
      clock: 'engine-monotonic',
      unit: 'us',
      timestampSource: 'synthetic-nominal',
      anchor: { monotonicUs: 0, unixTimeUs: 0 },
    },
  };
}

function block(streamId: string, rows: readonly (readonly number[])[], sequence: number): EegBlock {
  return {
    type: 'eeg.block',
    schemaVersion: 2,
    streamId,
    blockSequence: sequence,
    firstSampleIndex: sequence * (rows[0]?.length ?? 0),
    sampleCount: rows[0]?.length ?? 0,
    firstSampleTimeUs: 0,
    droppedSamplesBefore: 0,
    samples: rows.map((row) => [...row]),
  };
}

function fill(length: number, value: number): number[] {
  return Array.from({ length }, () => value);
}

describe('channel activity', () => {
  it('raises only the channel whose samples changed', () => {
    const labels = ['Fp1', 'Cz'];
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const meta = metadata('stream-a', labels, labels.length);
    activity.append(block('stream-a', [fill(2, 0), fill(2, 80)], 0), meta, 0);
    const display = activity.sampleDisplay(0);
    expect(display.health).toBe('live');
    expect(display.byLabel.get('Cz')?.intensity).toBe(1);
    expect(display.byLabel.get('Cz')?.rmsUv).toBeCloseTo(80);
    expect(display.byLabel.get('Fp1')?.intensity).toBe(0);
    expect(display.byLabel.get('Fp1')?.rmsUv).toBe(0);
    expect(80 / RMS_FULL_SCALE_UV).toBeGreaterThan(1);
  });

  it('interpolates between RMS snapshots and drops them when the stream id changes', () => {
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const meta = metadata('stream-a', ['Cz'], 4);
    activity.append(block('stream-a', [fill(4, 0)], 0), meta, 0);
    activity.append(block('stream-a', [fill(4, 12)], 1), meta, ACTIVITY_UPDATE_INTERVAL_MS);
    const atUpdate = activity.sampleDisplay(ACTIVITY_UPDATE_INTERVAL_MS);
    const midway = activity.sampleDisplay(ACTIVITY_UPDATE_INTERVAL_MS * 1.5);
    const settled = activity.sampleDisplay(ACTIVITY_UPDATE_INTERVAL_MS * 2);
    expect(atUpdate.byLabel.get('Cz')?.rmsUv).toBeCloseTo(0);
    expect(midway.byLabel.get('Cz')?.rmsUv).toBeCloseTo(6);
    expect(settled.byLabel.get('Cz')?.rmsUv).toBeCloseTo(12);
    expect(midway.byLabel.get('Cz')?.rmsUv).toBeGreaterThan(atUpdate.byLabel.get('Cz')?.rmsUv ?? 0);
    expect(midway.byLabel.get('Cz')?.rmsUv).toBeLessThan(settled.byLabel.get('Cz')?.rmsUv ?? 0);

    const next = metadata('stream-b', ['Cz'], 4);
    activity.append(block('stream-b', [fill(4, 0)], 0), next, 1_000);
    expect(activity.sampleDisplay(1_000).byLabel.get('Cz')?.rmsUv).toBe(0);
    expect(activity.sampleDisplay(1_000).byLabel.get('Cz')?.intensity).toBe(0);
  });

  it('fades intensity after the stream stops being live', () => {
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const meta = metadata('stream-a', ['Cz'], 2);
    activity.append(block('stream-a', [fill(2, 15)], 0), meta, 0);
    activity.noteStream({ health: 'stale', connection: 'open' }, 1_000);
    const atStale = activity.sampleDisplay(1_000).byLabel.get('Cz')?.intensity ?? 0;
    const later = activity.sampleDisplay(1_000 + STALE_FADE_SECONDS * 1000).byLabel.get('Cz')?.intensity ?? 0;
    expect(activity.sampleDisplay(1_000).health).toBe('fading');
    expect(atStale).toBeCloseTo(15 / RMS_FULL_SCALE_UV);
    expect(later).toBeCloseTo(atStale * Math.exp(-1));
    expect(later).toBeLessThan(atStale);
  });
});
