import { describe, expect, it } from 'vitest';
import type { EegBlock, StreamMetadata } from '@neuro-observatory/protocol';
import { MAX_PLOT_CHANNELS, MAX_SAMPLES_PER_CHANNEL, WINDOW_SECONDS, WaveformBuffer } from './waveformBuffer';

const LABELS = ['Fp1', 'Fp2', 'F3', 'F4', 'F7', 'F8', 'C3', 'C4', 'Cz', 'P3', 'P4', 'T7', 'T8', 'O1', 'O2', 'Pz'];
const RATE = 125;

function metadata(overrides: Partial<StreamMetadata> = {}, labels = LABELS): StreamMetadata {
  return {
    type: 'stream.metadata',
    schemaVersion: 2,
    streamId: 'stream-a',
    device: { kind: 'synthetic', model: 'neuro-observatory-synthetic-eeg', deviceId: 'synthetic-0', adapterVersion: '1.0.0' },
    provenance: {
      kind: 'synthetic',
      generator: 'neuro_engine.acquisition.synthetic',
      generatorVersion: '1',
      seed: 0,
      configHash: `sha256:${'ab'.repeat(32)}`,
    },
    nominalSampleRateHz: RATE,
    layout: 'channel-major',
    channels: labels.map((label, index) => ({
      index,
      label,
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
    ...overrides,
  };
}

function block(
  meta: StreamMetadata,
  firstSampleIndex: number,
  values: number[][],
  overrides: Partial<EegBlock> = {},
): EegBlock {
  return {
    type: 'eeg.block',
    schemaVersion: 2,
    streamId: meta.streamId,
    blockSequence: 0,
    firstSampleIndex,
    sampleCount: values[0]?.length ?? 0,
    firstSampleTimeUs: firstSampleIndex * (1_000_000 / meta.nominalSampleRateHz),
    droppedSamplesBefore: 0,
    samples: values,
    ...overrides,
  };
}

function column(meta: StreamMetadata, valueForChannel: (channel: number) => number): number[][] {
  return meta.channels.map((_, channel) => [valueForChannel(channel)]);
}

describe('WaveformBuffer', () => {
  it('keeps metadata channel order, including Fp1 at row 0 and Pz at row 15', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata();
    buffer.append(
      block(
        meta,
        0,
        meta.channels.map((_, channel) => [channel * 1000, channel * 1000 + 1]),
      ),
      meta,
      0,
    );

    const read = buffer.read();
    expect(read.labels).toEqual(LABELS);
    expect(read.unit).toBe('uV');
    expect(read.rateHz).toBe(RATE);
    expect(read.capacity).toBe(RATE * WINDOW_SECONDS);
    expect(read.values[0]).toEqual([0, 1]);
    expect(read.values[15]).toEqual([15000, 15001]);
    expect(read.clockRestarted).toBe(false);
    expect(read.synthetic).toBe(true);
  });

  it('rolls over at 10 seconds and drops the oldest samples', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata();
    const capacity = RATE * WINDOW_SECONDS;
    const total = capacity + 100;
    const blockSize = 25;
    for (let index = 0; index < total; index += blockSize) {
      const count = Math.min(blockSize, total - index);
      const samples = meta.channels.map(() => Array.from({ length: count }, (_, offset) => index + offset));
      buffer.append(block(meta, index, samples, { blockSequence: index / blockSize }), meta, index);
    }

    const row = buffer.read().values[0];
    expect(row).toHaveLength(capacity);
    expect(row[0]).toBe(100);
    expect(row[row.length - 1]).toBe(total - 1);
    expect(buffer.read().values[15][0]).toBe(100);
  });

  it('inserts one empty slot per missing sample inside a stream and splits the trace', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata();
    buffer.append(block(meta, 0, column(meta, () => 1).map((row) => row.concat([1, 1, 1, 1]))), meta, 0);
    buffer.append(
      block(meta, 15, column(meta, () => 2).map((row) => row.concat([2, 2, 2, 2])), {
        blockSequence: 1,
        droppedSamplesBefore: 10,
      }),
      meta,
      200,
    );

    const read = buffer.read();
    expect(read.values[0].filter((value) => value === null)).toHaveLength(10);
    expect(buffer.segments(0)).toEqual([
      { start: 0, end: 5 },
      { start: 15, end: 20 },
    ]);
    expect(read.clockRestarted).toBe(false);
  });

  it('keeps a one-sample acquisition gap one sample wide', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata({ nominalSampleRateHz: RATE }, ['Fp1']);
    buffer.append(block(meta, 0, [[3]]), meta, 0);
    buffer.append(block(meta, 2, [[5]], { blockSequence: 1, droppedSamplesBefore: 1 }), meta, 16);

    expect(buffer.read().values[0]).toEqual([3, null, 5]);
    expect(buffer.read().clockRestarted).toBe(false);
  });

  it('inserts the observed outage when a new stream resets the source clock', () => {
    const buffer = new WaveformBuffer();
    const first = metadata();
    buffer.append(block(first, 0, column(first, () => 4), { firstSampleTimeUs: 1_000_000 }), first, 0);

    const restarted = metadata({ streamId: 'stream-b' });
    buffer.append(block(restarted, 0, column(restarted, () => 9), { firstSampleTimeUs: 5_000 }), restarted, 1_500);

    const row = buffer.read().values[0];
    const holes = row.filter((value) => value === null).length;
    expect(holes).toBe(Math.round(1.5 * RATE));
    expect(row[0]).toBe(4);
    expect(row[1]).toBeNull();
    expect(row[row.length - 1]).toBe(9);
    expect(row[row.length - 2]).toBeNull();
    expect(buffer.segments(0)).toEqual([
      { start: 0, end: 1 },
      { start: holes + 1, end: holes + 2 },
    ]);
    expect(buffer.read().clockRestarted).toBe(true);
    expect(buffer.read().restartCause).toBe('new-stream');
    expect(buffer.read().synthetic).toBe(true);
  });

  it('uses the 250 ms floor when the restart is faster than that', () => {
    const buffer = new WaveformBuffer();
    const first = metadata({}, ['Fp1']);
    buffer.append(block(first, 0, [[4]], { firstSampleTimeUs: 1_000_000 }), first, 0);
    const restarted = metadata({ streamId: 'stream-b' }, ['Fp1']);
    buffer.append(block(restarted, 0, [[9]], { firstSampleTimeUs: 5_000 }), restarted, 0);

    const holes = buffer.read().values[0].filter((value) => value === null).length;
    expect(holes).toBe(Math.round(0.25 * RATE));
    expect(buffer.read().values[0][0]).toBe(4);
  });

  it('treats a backwards source clock on the same stream id as a new clock domain', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata({}, ['Fp1']);
    buffer.append(block(meta, 0, [[4]], { firstSampleTimeUs: 1_000_000 }), meta, 0);
    buffer.append(block(meta, 0, [[9]], { blockSequence: 1, firstSampleTimeUs: 5_000 }), meta, 1_500);

    expect(buffer.read().values[0].filter((value) => value === null)).toHaveLength(Math.round(1.5 * RATE));
    expect(buffer.read().clockRestarted).toBe(true);
    expect(buffer.read().restartCause).toBe('source-clock');
  });

  it('caps a long outage at the window instead of joining the reset monotonic clock', () => {
    const buffer = new WaveformBuffer();
    const first = metadata({}, ['Fp1']);
    buffer.append(block(first, 0, [[4]], { firstSampleTimeUs: 1_000_000 }), first, 0);
    const restarted = metadata({ streamId: 'stream-b' }, ['Fp1']);
    buffer.append(block(restarted, 0, [[9]], { firstSampleTimeUs: 5_000 }), restarted, 30_000);

    const row = buffer.read().values[0];
    expect(row).toHaveLength(RATE * WINDOW_SECONDS);
    expect(row.filter((value) => value === null)).toHaveLength(RATE * WINDOW_SECONDS - 1);
    expect(row[row.length - 1]).toBe(9);
    expect(row).not.toContain(4);
  });

  it('clears samples when the channel layout changes', () => {
    const buffer = new WaveformBuffer();
    const first = metadata({}, ['Fp1']);
    buffer.append(block(first, 0, [[1]]), first, 0);
    const next = metadata({ streamId: 'stream-b' }, ['Oz']);
    buffer.append(block(next, 0, [[7]]), next, 500);

    const read = buffer.read();
    expect(read.labels).toEqual(['Oz']);
    expect(read.values).toEqual([[7]]);
    expect(read.clockRestarted).toBe(false);
  });

  it('refuses a stream above the allocation cap without keeping a truncated plot', () => {
    const buffer = new WaveformBuffer();
    const ok = metadata({}, ['Fp1']);
    buffer.append(block(ok, 0, [[1]]), ok, 0);

    const tooMany = metadata({}, Array.from({ length: MAX_PLOT_CHANNELS + 1 }, (_, index) => `Ch${index}`));
    buffer.append(block(tooMany, 0, tooMany.channels.map(() => [1])), tooMany, 10);

    const read = buffer.read();
    expect(read.error).toMatch(/viewer limit/);
    expect(read.values).toEqual([]);
    expect(read.labels).toEqual([]);

    const tooFast = metadata({ nominalSampleRateHz: MAX_SAMPLES_PER_CHANNEL / WINDOW_SECONDS + 1 }, ['Fp1']);
    buffer.append(block(tooFast, 0, [[1]]), tooFast, 20);
    expect(buffer.read().error).toMatch(new RegExp(String(MAX_SAMPLES_PER_CHANNEL)));
    expect(buffer.read().values).toEqual([]);
  });

  it('does not notify chrome listeners for a contiguous block', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata({}, ['Fp1']);
    let notices = 0;
    buffer.subscribe(() => {
      notices += 1;
    });
    buffer.append(block(meta, 0, [[1, 1]]), meta, 0);
    buffer.append(block(meta, 2, [[2, 2]], { blockSequence: 1 }), meta, 16);
    expect(notices).toBe(1);
    expect(buffer.read().values[0]).toEqual([1, 1, 2, 2]);
  });

  it('clears samples and the synthetic sentence when a device stream reuses the montage', () => {
    const buffer = new WaveformBuffer();
    const synthetic = metadata({}, ['Fp1']);
    buffer.append(block(synthetic, 0, [[4]]), synthetic, 0);
    const device = metadata({ streamId: 'stream-device', provenance: { kind: 'device' } }, ['Fp1']);
    buffer.append(block(device, 0, [[8]], { firstSampleTimeUs: 0 }), device, 500);

    const read = buffer.read();
    expect(read.synthetic).toBe(false);
    expect(read.values).toEqual([[8]]);
    expect(read.clockRestarted).toBe(false);
  });

  it('restores the synthetic sentence when a generated stream follows a device stream', () => {
    const buffer = new WaveformBuffer();
    const device = metadata({ provenance: { kind: 'device' } }, ['Fp1']);
    buffer.append(block(device, 0, [[8]]), device, 0);
    const synthetic = metadata({ streamId: 'stream-synthetic' }, ['Fp1']);
    buffer.append(block(synthetic, 0, [[4]], { firstSampleTimeUs: 0 }), synthetic, 500);

    const read = buffer.read();
    expect(read.synthetic).toBe(true);
    expect(read.values).toEqual([[4]]);
  });

  it('clears samples when the electrical reference changes', () => {
    const buffer = new WaveformBuffer();
    const first = metadata({}, ['Fp1']);
    buffer.append(block(first, 0, [[1]]), first, 0);
    const next = metadata({ streamId: 'stream-b' }, ['Fp1']);
    next.channels = [{ ...next.channels[0], reference: 'SRB2' }];
    buffer.append(block(next, 0, [[7]]), next, 500);

    expect(buffer.read().values).toEqual([[7]]);
    expect(buffer.read().synthetic).toBe(true);
  });

  it('clears samples when a channel type changes', () => {
    const buffer = new WaveformBuffer();
    const first = metadata({}, ['Fp1']);
    buffer.append(block(first, 0, [[1]]), first, 0);
    const next = metadata({ streamId: 'stream-b' }, ['Fp1']);
    next.channels = [{ ...next.channels[0], type: 'EOG' }];
    buffer.append(block(next, 0, [[7]]), next, 500);

    expect(buffer.read().values).toEqual([[7]]);
  });

  it('places samples by index when droppedSamplesBefore is larger than the index gap', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata({}, ['Fp1']);
    buffer.append(block(meta, 0, [[1, 1]]), meta, 0);
    buffer.append(block(meta, 2, [[2]], { blockSequence: 1, droppedSamplesBefore: 10, firstSampleTimeUs: 16_000 }), meta, 16);

    expect(buffer.read().values[0]).toEqual([1, 1, 2]);
  });

  it('keeps a visible restart hole when the next block fills the window', () => {
    const buffer = new WaveformBuffer();
    const capacity = RATE * WINDOW_SECONDS;
    const first = metadata({}, ['Fp1']);
    buffer.append(block(first, 0, [[4]], { firstSampleTimeUs: 1_000_000 }), first, 0);
    const restarted = metadata({ streamId: 'stream-b' }, ['Fp1']);
    const samples = [Array.from({ length: capacity }, (_, index) => 100 + index)];
    buffer.append(block(restarted, 0, samples, { firstSampleTimeUs: 0 }), restarted, 0);

    const row = buffer.read().values[0];
    const holes = Math.round(0.25 * RATE);
    expect(row.filter((value) => value === null)).toHaveLength(holes);
    expect(row[holes]).toBe(100 + holes);
    expect(row[row.length - 1]).toBe(100 + capacity - 1);
    expect(row).not.toContain(4);
    expect(buffer.read().restartCause).toBe('new-stream');
  });

  it('appends only the new tail when a later block overlaps stored samples', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata({}, ['Fp1']);
    buffer.append(block(meta, 0, [[1, 2, 3]], { firstSampleTimeUs: 0 }), meta, 0);
    buffer.append(block(meta, 1, [[9, 8, 7]], { blockSequence: 1, firstSampleTimeUs: 24_000 }), meta, 40);

    expect(buffer.read().values[0]).toEqual([1, 2, 3, 7]);
    expect(buffer.read().clockRestarted).toBe(false);
  });

  it('ignores a block whose indexes are already stored', () => {
    const buffer = new WaveformBuffer();
    const meta = metadata({}, ['Fp1']);
    buffer.append(block(meta, 0, [[1, 2, 3]], { firstSampleTimeUs: 0 }), meta, 0);
    buffer.append(block(meta, 0, [[9, 8, 7]], { blockSequence: 1, firstSampleTimeUs: 24_000 }), meta, 40);

    expect(buffer.read().values[0]).toEqual([1, 2, 3]);
  });

  it('clears the restart caption once later samples push the hole out of the window', () => {
    const buffer = new WaveformBuffer();
    const capacity = RATE * WINDOW_SECONDS;
    const first = metadata({}, ['Fp1']);
    buffer.append(block(first, 0, [[4]], { firstSampleTimeUs: 1_000_000 }), first, 0);
    const restarted = metadata({ streamId: 'stream-b' }, ['Fp1']);
    buffer.append(block(restarted, 0, [[9]], { firstSampleTimeUs: 0 }), restarted, 0);
    expect(buffer.read().clockRestarted).toBe(true);

    const follow = Array.from({ length: capacity - 1 }, () => 6);
    buffer.append(block(restarted, 1, [follow], { blockSequence: 1 }), restarted, 1_000);

    expect(buffer.read().clockRestarted).toBe(false);
    expect(buffer.read().restartCause).toBeNull();
  });
});
