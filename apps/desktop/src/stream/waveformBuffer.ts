import type { EegBlock, StreamMetadata } from '@neuro-observatory/protocol';

/** Seconds of nominal samples retained per channel. */
export const WINDOW_SECONDS = 10;
/** Viewer allocation cap. A larger stream is refused rather than truncated. */
export const MAX_PLOT_CHANNELS = 64;
export const MAX_SAMPLES_PER_CHANNEL = 20_000;
/** Shortest hole inserted when the source clock domain changes. */
export const MIN_RESTART_GAP_SECONDS = 0.25;
/** Fixed half-range of each lane, in the channel unit (µV for this protocol). */
export const LANE_HALF_RANGE_UV = 100;
/** Pixels reserved under the lanes for the time-axis labels. */
export const TIME_AXIS_PX = 22;

const TRACE_COLOR = '#7dd3fc';

/** Why a clock-domain hole is still inside the window. */
export type RestartCause = 'new-stream' | 'source-clock';

export interface WaveformChrome {
  labels: readonly string[];
  unit: string;
  rateHz: number;
  capacity: number;
  error: string | null;
  /** True while a restart hole from `restartCause` is still inside the window. */
  clockRestarted: boolean;
  /** `new-stream` only when `streamId` changed. A same-id backwards clock is `source-clock`. */
  restartCause: RestartCause | null;
  synthetic: boolean;
}

export interface WaveformRead extends WaveformChrome {
  /** Oldest to newest. `null` is an empty slot and must break the stroke. */
  values: readonly (readonly (number | null)[])[];
  /** Slots occupied, including empty gap slots. */
  length: number;
}

export interface FiniteRun {
  /** Inclusive start index in the oldest-to-newest window. */
  start: number;
  /** Exclusive end index. */
  end: number;
}

const EMPTY_CHROME: WaveformChrome = {
  labels: [],
  unit: '',
  rateHz: 0,
  capacity: 0,
  error: null,
  clockRestarted: false,
  restartCause: null,
  synthetic: false,
};

/**
 * Ten-second live view of accepted EEG blocks.
 *
 * Slots are one nominal sample apart. Empty slots break the trace.
 * A new stream id, or a same-id clock that jumps backwards by more than
 * half a sample, is a new clock domain: the hole is the time since the
 * last accepted sample (at least 250 ms, at most the window) and stays
 * visible when the next block is longer than the remaining window.
 * Source timestamps from the new domain are not placed on the previous clock.
 * Inside one stream, empty slots follow the sample index. A block that
 * overlaps samples already stored appends only the new tail.
 * Provenance, reference, and channel type are part of the layout: a change
 * clears the rings so the synthetic sentence matches the samples on screen.
 * Samples stay out of React state; `paint` is called from the display loop.
 * Chrome listeners fire when labels, the error, the clock-domain caption,
 * or the synthetic sentence change.
 */
export class WaveformBuffer {
  private channels: Float64Array[] = [];
  private capacity = 0;
  private write = 0;
  private count = 0;
  private labels: string[] = [];
  private units: string[] = [];
  private unit = '';
  private rateHz = 0;
  private streamId: string | null = null;
  private nextSampleIndex: number | null = null;
  private lastSampleTimeUs: number | null = null;
  private lastAppendMs: number | null = null;
  private types: string[] = [];
  private references: string[] = [];
  private provenanceKind: 'synthetic' | 'device' | null = null;
  private error: string | null = null;
  private clockRestarted = false;
  private restartCause: RestartCause | null = null;
  /** Further slots that must be written before the restart hole leaves the window. */
  private slotsUntilRestartClears: number | null = null;
  private synthetic = false;
  private chrome: WaveformChrome = EMPTY_CHROME;
  private readonly listeners = new Set<() => void>();

  getChrome = (): WaveformChrome => this.chrome;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  append(block: EegBlock, metadata: StreamMetadata, nowMs: number): void {
    if (block.streamId !== metadata.streamId || block.sampleCount < 1) {
      return;
    }
    const labels = metadata.channels.map((channel) => channel.label);
    const units = metadata.channels.map((channel) => channel.unit);
    const types = metadata.channels.map((channel) => channel.type);
    const references = metadata.channels.map((channel) => channel.reference);
    const provenanceKind = metadata.provenance.kind;
    const rate = metadata.nominalSampleRateHz;
    if (!Number.isFinite(rate) || rate <= 0 || labels.length === 0) {
      this.fail('The stream has no positive sample rate or no channels, so nothing was plotted.');
      return;
    }
    const capacity = Math.ceil(rate * WINDOW_SECONDS);
    if (labels.length > MAX_PLOT_CHANNELS || capacity > MAX_SAMPLES_PER_CHANNEL) {
      this.fail(
        `This stream is ${labels.length} channels at ${rate} Hz (${capacity} samples in ${WINDOW_SECONDS} s). ` +
          `The viewer limit is ${MAX_PLOT_CHANNELS} channels and ${MAX_SAMPLES_PER_CHANNEL} samples per channel, so nothing was plotted.`,
      );
      return;
    }
    if (block.samples.length !== labels.length) {
      return;
    }

    const layoutChanged = !this.sameLayout(labels, units, types, references, rate, provenanceKind);
    if (layoutChanged) {
      this.allocate(labels, units, types, references, rate, capacity, provenanceKind);
      this.appendSamples(block);
      this.finishAppend(block, nowMs);
      this.publish();
      return;
    }

    const periodUs = 1_000_000 / this.rateHz;
    const clockJumpedBack =
      this.lastSampleTimeUs !== null && block.firstSampleTimeUs < this.lastSampleTimeUs - periodUs / 2;
    if (this.streamId !== block.streamId || clockJumpedBack) {
      const cause: RestartCause = this.streamId !== block.streamId ? 'new-stream' : 'source-clock';
      this.appendAcrossClockDomain(block, nowMs, cause);
      this.publish();
      return;
    }

    if (this.nextSampleIndex !== null && block.firstSampleIndex < this.nextSampleIndex) {
      const skip = Math.min(block.sampleCount, this.nextSampleIndex - block.firstSampleIndex);
      if (skip >= block.sampleCount) {
        return;
      }
      this.appendSampleRange(block, skip, block.sampleCount);
      this.noteSlotsWritten(block.sampleCount - skip);
      this.finishAppend(block, nowMs);
      this.publish();
      return;
    }

    let written = 0;
    if (this.nextSampleIndex !== null) {
      const indexGap = block.firstSampleIndex - this.nextSampleIndex;
      if (indexGap > 0) {
        written = Math.min(indexGap, this.capacity);
        this.pushEmpty(written);
      }
    }
    this.appendSamples(block);
    written += block.sampleCount;
    this.noteSlotsWritten(written);
    this.finishAppend(block, nowMs);
    this.publish();
  }

  read(): WaveformRead {
    const values = this.channels.map(() => [] as (number | null)[]);
    if (this.count > 0) {
      const oldest = this.oldestIndex();
      for (let i = 0; i < this.count; i += 1) {
        const slot = (oldest + i) % this.capacity;
        for (let channel = 0; channel < this.channels.length; channel += 1) {
          const value = this.channels[channel][slot];
          values[channel].push(Number.isFinite(value) ? value : null);
        }
      }
    }
    return { ...this.chrome, values, length: this.count };
  }

  /** Finite runs for one channel, oldest to newest. A gap splits runs. */
  segments(channel: number): FiniteRun[] {
    const row = this.read().values[channel] ?? [];
    const runs: FiniteRun[] = [];
    let start: number | null = null;
    for (let index = 0; index < row.length; index += 1) {
      if (row[index] !== null) {
        if (start === null) {
          start = index;
        }
      } else if (start !== null) {
        runs.push({ start, end: index });
        start = null;
      }
    }
    if (start !== null) {
      runs.push({ start, end: row.length });
    }
    return runs;
  }

  paint(
    ctx: CanvasRenderingContext2D,
    width: number,
    height: number,
    emphasis?: { index: number; color: string } | null,
  ): void {
    if (this.error || this.channels.length === 0 || this.count === 0 || width <= 0 || height <= 0) {
      return;
    }
    const plotHeight = Math.max(0, height - TIME_AXIS_PX);
    const laneHeight = plotHeight / this.channels.length;
    const half = LANE_HALF_RANGE_UV;
    const oldest = this.oldestIndex();

    ctx.save();
    ctx.lineWidth = 1.25;
    ctx.font = '11px system-ui, sans-serif';
    ctx.fillStyle = 'rgba(148, 163, 184, 0.35)';
    for (let channel = 0; channel < this.channels.length; channel += 1) {
      const laneTop = channel * laneHeight;
      ctx.fillRect(0, laneTop + laneHeight / 2, width, 1);
    }

    for (let channel = 0; channel < this.channels.length; channel += 1) {
      const laneTop = channel * laneHeight;
      ctx.strokeStyle = emphasis?.index === channel ? emphasis.color : TRACE_COLOR;
      const row = this.channels[channel];
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, laneTop, width, laneHeight);
      ctx.clip();
      ctx.beginPath();
      let drawing = false;
      let runPoints = 0;
      let lastX = 0;
      let lastY = 0;
      const closeRun = () => {
        if (drawing && runPoints === 1) {
          const nudge = lastX + 1 <= width ? 1 : -1;
          ctx.lineTo(lastX + nudge, lastY);
        }
        drawing = false;
        runPoints = 0;
      };
      for (let i = 0; i < this.count; i += 1) {
        const value = row[(oldest + i) % this.capacity];
        if (!Number.isFinite(value)) {
          closeRun();
          continue;
        }
        const slotFromLeft = this.capacity - this.count + i;
        const x = ((slotFromLeft + 0.5) / this.capacity) * width;
        const clipped = Math.min(half, Math.max(-half, value));
        const y = laneTop + ((half - clipped) / (2 * half)) * laneHeight;
        if (!drawing) {
          ctx.moveTo(x, y);
          drawing = true;
          runPoints = 1;
        } else {
          ctx.lineTo(x, y);
          runPoints += 1;
        }
        lastX = x;
        lastY = y;
      }
      closeRun();
      ctx.stroke();
      ctx.restore();
    }

    ctx.fillStyle = '#94a3b8';
    const seconds = Math.floor(WINDOW_SECONDS);
    for (let second = 0; second <= seconds; second += 1) {
      const samplesFromRight = second * this.rateHz;
      if (samplesFromRight > this.capacity) {
        continue;
      }
      const x = width - (samplesFromRight / this.capacity) * width;
      ctx.fillRect(x, plotHeight, 1, 4);
      const label = second === 0 ? '0' : `-${second}s`;
      ctx.fillText(label, Math.min(width - 28, Math.max(0, x - (second === 0 ? 4 : 12))), height - 6);
    }
    ctx.restore();
  }

  private sameLayout(
    labels: string[],
    units: string[],
    types: string[],
    references: string[],
    rate: number,
    provenanceKind: 'synthetic' | 'device',
  ): boolean {
    if (
      this.capacity === 0 ||
      this.rateHz !== rate ||
      this.provenanceKind !== provenanceKind ||
      this.labels.length !== labels.length
    ) {
      return false;
    }
    for (let index = 0; index < labels.length; index += 1) {
      if (
        this.labels[index] !== labels[index] ||
        this.units[index] !== units[index] ||
        this.types[index] !== types[index] ||
        this.references[index] !== references[index]
      ) {
        return false;
      }
    }
    return true;
  }

  private allocate(
    labels: string[],
    units: string[],
    types: string[],
    references: string[],
    rate: number,
    capacity: number,
    provenanceKind: 'synthetic' | 'device',
  ): void {
    this.labels = labels.slice();
    this.units = units.slice();
    this.types = types.slice();
    this.references = references.slice();
    this.provenanceKind = provenanceKind;
    this.unit = units[0] ?? 'uV';
    this.rateHz = rate;
    this.capacity = capacity;
    this.channels = labels.map(() => new Float64Array(capacity));
    this.write = 0;
    this.count = 0;
    this.streamId = null;
    this.nextSampleIndex = null;
    this.lastSampleTimeUs = null;
    this.lastAppendMs = null;
    this.error = null;
    this.clockRestarted = false;
    this.restartCause = null;
    this.slotsUntilRestartClears = null;
    this.synthetic = provenanceKind === 'synthetic';
  }

  private fail(message: string): void {
    this.channels = [];
    this.capacity = 0;
    this.write = 0;
    this.count = 0;
    this.labels = [];
    this.units = [];
    this.types = [];
    this.references = [];
    this.provenanceKind = null;
    this.unit = '';
    this.rateHz = 0;
    this.streamId = null;
    this.nextSampleIndex = null;
    this.lastSampleTimeUs = null;
    this.lastAppendMs = null;
    this.clockRestarted = false;
    this.restartCause = null;
    this.slotsUntilRestartClears = null;
    this.synthetic = false;
    this.error = message;
    this.publish();
  }

  /**
   * Keep the observed hole, then the newest samples that still fit.
   * A block longer than the window used to overwrite the hole it was meant to follow.
   */
  private appendAcrossClockDomain(block: EegBlock, nowMs: number, cause: RestartCause): void {
    const elapsedSec = this.lastAppendMs === null ? MIN_RESTART_GAP_SECONDS : Math.max(0, (nowMs - this.lastAppendMs) / 1000);
    const gapSlots = Math.min(
      this.capacity,
      Math.max(1, Math.round(MIN_RESTART_GAP_SECONDS * this.rateHz), Math.round(elapsedSec * this.rateHz)),
    );
    const visibleGap = this.capacity <= 1 ? 0 : Math.min(gapSlots, this.capacity - 1);
    const visibleNew = Math.min(block.sampleCount, this.capacity - visibleGap);
    const priorKeep = Math.min(this.count, this.capacity - visibleGap - visibleNew);
    this.count = priorKeep;
    if (visibleGap > 0) {
      this.pushEmpty(visibleGap);
    }
    if (visibleNew > 0) {
      this.appendSampleRange(block, block.sampleCount - visibleNew, block.sampleCount);
    }
    this.restartCause = visibleGap > 0 ? cause : null;
    this.clockRestarted = this.restartCause !== null;
    this.slotsUntilRestartClears = this.clockRestarted ? this.capacity - visibleNew : null;
    this.finishAppend(block, nowMs);
  }

  private noteSlotsWritten(slots: number): void {
    if (this.slotsUntilRestartClears === null || slots <= 0) {
      return;
    }
    this.slotsUntilRestartClears -= slots;
    if (this.slotsUntilRestartClears <= 0) {
      this.slotsUntilRestartClears = null;
      this.restartCause = null;
      this.clockRestarted = false;
    }
  }

  private pushEmpty(slots: number): void {
    for (let i = 0; i < slots; i += 1) {
      for (const row of this.channels) {
        row[this.write] = Number.NaN;
      }
      this.advance();
    }
  }

  private appendSamples(block: EegBlock): void {
    this.appendSampleRange(block, 0, block.sampleCount);
  }

  private appendSampleRange(block: EegBlock, fromSample: number, toSample: number): void {
    for (let sample = fromSample; sample < toSample; sample += 1) {
      for (let channel = 0; channel < this.channels.length; channel += 1) {
        const value = block.samples[channel]?.[sample];
        this.channels[channel][this.write] = typeof value === 'number' && Number.isFinite(value) ? value : Number.NaN;
      }
      this.advance();
    }
  }

  private advance(): void {
    this.write = (this.write + 1) % this.capacity;
    if (this.count < this.capacity) {
      this.count += 1;
    }
  }

  private finishAppend(block: EegBlock, nowMs: number): void {
    const periodUs = 1_000_000 / this.rateHz;
    this.streamId = block.streamId;
    this.nextSampleIndex = block.firstSampleIndex + block.sampleCount;
    this.lastSampleTimeUs = block.firstSampleTimeUs + (block.sampleCount - 1) * periodUs;
    this.lastAppendMs = nowMs;
  }

  private oldestIndex(): number {
    return (this.write - this.count + this.capacity) % this.capacity;
  }

  private publish(): void {
    const next: WaveformChrome = {
      labels: this.labels.slice(),
      unit: this.unit,
      rateHz: this.rateHz,
      capacity: this.capacity,
      error: this.error,
      clockRestarted: this.clockRestarted,
      restartCause: this.restartCause,
      synthetic: this.synthetic,
    };
    const prev = this.chrome;
    const sameLabels =
      prev.labels.length === next.labels.length && prev.labels.every((label, index) => label === next.labels[index]);
    if (
      sameLabels &&
      prev.unit === next.unit &&
      prev.rateHz === next.rateHz &&
      prev.capacity === next.capacity &&
      prev.error === next.error &&
      prev.clockRestarted === next.clockRestarted &&
      prev.restartCause === next.restartCause &&
      prev.synthetic === next.synthetic
    ) {
      return;
    }
    this.chrome = next;
    for (const listener of this.listeners) {
      listener();
    }
  }
}
