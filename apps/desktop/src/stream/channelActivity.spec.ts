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

function block(
  streamId: string,
  rows: readonly (readonly number[])[],
  sequence: number,
  overrides: Partial<Pick<EegBlock, 'firstSampleIndex' | 'firstSampleTimeUs' | 'droppedSamplesBefore'>> = {},
): EegBlock {
  const sampleCount = rows[0]?.length ?? 0;
  const firstSampleIndex = overrides.firstSampleIndex ?? sequence * sampleCount;
  return {
    type: 'eeg.block',
    schemaVersion: 2,
    streamId,
    blockSequence: sequence,
    firstSampleIndex,
    sampleCount,
    firstSampleTimeUs: overrides.firstSampleTimeUs ?? firstSampleIndex * 1_000_000,
    droppedSamplesBefore: overrides.droppedSamplesBefore ?? 0,
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

  it('lets an index gap age samples out of the one-second window', () => {
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const meta = metadata('stream-a', ['Cz'], 125);
    activity.append(block('stream-a', [fill(100, 50)], 0, { firstSampleIndex: 0 }), meta, 0);
    activity.append(
      block('stream-a', [fill(25, 0)], 1, { firstSampleIndex: 200, droppedSamplesBefore: 100 }),
      meta,
      1_000,
    );
    const atPublish = activity.sampleDisplay(1_000);
    const settled = activity.sampleDisplay(2_000);
    expect(atPublish.byLabel.get('Cz')?.rmsUv).toBeCloseTo(50);
    expect(atPublish.missingSamples).toBe(0);
    expect(settled.byLabel.get('Cz')?.rmsUv).toBe(0);
    expect(settled.missingSamples).toBe(100);
    expect(settled.health).toBe('live');
    expect(settled.error).toBeNull();
  });

  it('does not invent time when droppedSamplesBefore exceeds the index gap', () => {
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const meta = metadata('stream-a', ['Cz'], 4);
    activity.append(block('stream-a', [[10, 10, 10, 10]], 0), meta, 0);
    activity.append(block('stream-a', [[0]], 1, { firstSampleIndex: 4, droppedSamplesBefore: 10 }), meta, ACTIVITY_UPDATE_INTERVAL_MS);
    const settled = activity.sampleDisplay(ACTIVITY_UPDATE_INTERVAL_MS * 2);
    expect(settled.missingSamples).toBe(0);
    expect(settled.byLabel.get('Cz')?.rmsUv).toBeCloseTo(Math.sqrt(75));
  });

  it('keeps only the unseen tail of an overlapping block', () => {
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const meta = metadata('stream-a', ['Cz'], 4);
    activity.append(block('stream-a', [[10, 10, 10, 30]], 0), meta, 0);
    activity.append(block('stream-a', [[1, 1, 0, 0]], 1, { firstSampleIndex: 2 }), meta, ACTIVITY_UPDATE_INTERVAL_MS);
    const settled = activity.sampleDisplay(ACTIVITY_UPDATE_INTERVAL_MS * 2);
    expect(settled.byLabel.get('Cz')?.rmsUv).toBeCloseTo(Math.sqrt(250));
    expect(settled.missingSamples).toBe(0);
  });

  it('drops the window when the reference or provenance changes', () => {
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const first = metadata('stream-a', ['Cz'], 4);
    activity.append(block('stream-a', [[10, 10]], 0), first, 0);
    const next = metadata('stream-a', ['Cz'], 4);
    next.channels[0] = { index: 0, label: 'Cz', type: 'EEG', unit: 'uV', reference: 'linked-ears' };
    next.provenance = { kind: 'device' };
    activity.append(block('stream-a', [[0, 0]], 1, { firstSampleIndex: 2 }), next, 1_000);
    const display = activity.sampleDisplay(1_000);
    expect(display.synthetic).toBe(false);
    expect(display.byLabel.get('Cz')?.rmsUv).toBe(0);
    expect(display.missingSamples).toBe(0);
  });

  it('clears the window when the source clock jumps backwards', () => {
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const meta = metadata('stream-a', ['Cz'], 4);
    activity.append(block('stream-a', [[10, 10, 10, 10]], 0, { firstSampleTimeUs: 1_000_000 }), meta, 0);
    activity.append(block('stream-a', [[0, 0]], 1, { firstSampleIndex: 0, firstSampleTimeUs: 0 }), meta, 1_000);
    const display = activity.sampleDisplay(1_000);
    expect(display.byLabel.get('Cz')?.rmsUv).toBe(0);
    expect(display.synthetic).toBe(true);
  });

  it('clears the previous highlight when the stream exceeds the viewer cap', () => {
    const activity = new ChannelActivity();
    activity.noteStream({ health: 'live', connection: 'open' }, 0);
    const meta = metadata('stream-a', ['Cz'], 4);
    activity.append(block('stream-a', [[40, 40, 40, 40]], 0), meta, 0);
    const labels = Array.from({ length: 80 }, (_, index) => `Ch${index}`);
    const big = metadata('stream-b', labels, 4);
    activity.append(block('stream-b', labels.map(() => [1, 1, 1, 1]), 0), big, 1_000);
    const display = activity.sampleDisplay(1_000);
    expect(display.health).toBe('waiting');
    expect(display.byLabel.size).toBe(0);
    expect(display.error).toMatch(/80 channels/);
    expect(display.missingSamples).toBe(0);
  });
});
