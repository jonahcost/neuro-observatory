import type { EegBlock, StreamMetadata } from '@neuro-observatory/protocol';
import type { ConnectionState, StreamHealth } from './eegStreamClient';

/** Trailing window on the sample clock, in seconds. */
export const ACTIVITY_WINDOW_SECONDS = 1;
/** How often a new RMS snapshot is published. */
export const ACTIVITY_UPDATE_HZ = 5;
export const ACTIVITY_UPDATE_INTERVAL_MS = 1000 / ACTIVITY_UPDATE_HZ;
/** Display full scale. Resting synthetic RMS is about 15 µV. Not a calibrated power. */
export const RMS_FULL_SCALE_UV = 30;
/** Time constant for fading highlights after the stream leaves the live state. */
export const STALE_FADE_SECONDS = 0.6;
const MAX_CHANNELS = 64;
const MAX_SAMPLES = 20_000;

export type HighlightHealth = 'waiting' | 'live' | 'fading';

export interface ChannelHighlight {
  rmsUv: number;
  intensity: number;
}

export interface ActivityDisplay {
  health: HighlightHealth;
  synthetic: boolean;
  /**
   * Index-gap slots inside the published window. They occupy time and are
   * left out of the mean. They are not stored as 0 µV.
   */
  missingSamples: number;
  /** Set when this stream is outside the highlight cap. The previous window is cleared. */
  error: string | null;
  byLabel: ReadonlyMap<string, ChannelHighlight>;
}

export interface StreamLink {
  health: StreamHealth;
  connection: ConnectionState;
}

/**
 * One-second per-channel RMS for sensor highlights.
 *
 * The window is one nominal second of the sample index, not one second of
 * received packets. An index gap takes slots and contributes no voltage.
 * A block that overlaps samples already stored contributes only its new tail.
 * `droppedSamplesBefore` does not add slots of its own: the index is the
 * position of the values (ADR-0013).
 *
 * Layout identity matches the waveform: labels, units, channel types,
 * references, nominal rate, and provenance kind. A new `streamId` or a
 * same-id clock that steps backwards by more than half a sample drops the
 * window. Two clocks are not averaged together. The waveform plot still
 * keeps its own history and restart hole.
 *
 * Samples stay out of React state. `sampleDisplay` eases between the last
 * two published RMS snapshots. A non-live stream multiplies intensity by an
 * exponential fade.
 */
export class ChannelActivity {
  private labels: string[] = [];
  private units: string[] = [];
  private types: string[] = [];
  private references: string[] = [];
  private provenanceKind: 'synthetic' | 'device' | null = null;
  private rings: Float64Array[] = [];
  private write = 0;
  private count = 0;
  private capacity = 0;
  private rateHz = 0;
  private streamId: string | null = null;
  private nextSampleIndex: number | null = null;
  private lastSampleTimeUs: number | null = null;
  private lastPublishMs: number | null = null;
  private previousRms: Float64Array | null = null;
  private currentRms: Float64Array | null = null;
  private previousAtMs = 0;
  private currentAtMs = 0;
  private missingSamples = 0;
  private previousMissing = 0;
  private error: string | null = null;
  private link: 'unknown' | 'live' | 'fading' = 'unknown';
  private fadeAnchorMs: number | null = null;
  private synthetic = false;
  private readonly listeners = new Set<() => void>();

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  noteStream(link: StreamLink, nowMs: number): void {
    const live = link.health === 'live' && link.connection === 'open';
    const next: 'unknown' | 'live' | 'fading' = live ? 'live' : this.currentRms === null ? 'unknown' : 'fading';
    if (next === this.link && (next !== 'fading' || this.fadeAnchorMs !== null)) {
      return;
    }
    this.link = next;
    if (next === 'fading') {
      this.fadeAnchorMs = this.fadeAnchorMs ?? nowMs;
    } else {
      this.fadeAnchorMs = null;
    }
    this.emit();
  }

  append(block: EegBlock, metadata: StreamMetadata, nowMs: number): void {
    if (block.streamId !== metadata.streamId || block.sampleCount < 1 || block.samples.length !== metadata.channels.length) {
      return;
    }
    if (block.samples.some((row) => row.length !== block.sampleCount)) {
      return;
    }
    const rate = metadata.nominalSampleRateHz;
    if (!Number.isFinite(rate) || rate <= 0) {
      return;
    }
    const labels = metadata.channels.map((channel) => channel.label);
    const units = metadata.channels.map((channel) => channel.unit);
    const types = metadata.channels.map((channel) => channel.type);
    const references = metadata.channels.map((channel) => channel.reference);
    const provenanceKind = metadata.provenance.kind;
    const capacity = Math.ceil(rate * ACTIVITY_WINDOW_SECONDS);
    if (labels.length === 0 || labels.length > MAX_CHANNELS || capacity > MAX_SAMPLES) {
      const reason =
        labels.length === 0
          ? 'The stream has no channels, so no sensor highlight is shown.'
          : `This stream is ${labels.length} channels at ${rate} Hz (${capacity} samples in ${ACTIVITY_WINDOW_SECONDS} s). ` +
            `The highlight limit is ${MAX_CHANNELS} channels and ${MAX_SAMPLES} samples per channel, so no sensor highlight is shown.`;
      this.fail(reason);
      return;
    }

    const newStream = this.streamId !== null && this.streamId !== metadata.streamId;
    if (newStream || !this.sameLayout(labels, units, types, references, rate, provenanceKind)) {
      this.allocate(labels, units, types, references, rate, capacity, provenanceKind, metadata.streamId);
      this.ingest(block, nowMs);
      return;
    }

    const periodUs = 1_000_000 / this.rateHz;
    const clockJumpedBack =
      this.lastSampleTimeUs !== null && block.firstSampleTimeUs < this.lastSampleTimeUs - periodUs / 2;
    if (clockJumpedBack) {
      this.allocate(labels, units, types, references, rate, capacity, provenanceKind, metadata.streamId);
      this.ingest(block, nowMs);
      return;
    }

    if (this.nextSampleIndex !== null && block.firstSampleIndex < this.nextSampleIndex) {
      const skip = Math.min(block.sampleCount, this.nextSampleIndex - block.firstSampleIndex);
      if (skip >= block.sampleCount) {
        return;
      }
      this.pushRange(block, skip, block.sampleCount);
      this.finish(block, nowMs);
      return;
    }

    if (this.nextSampleIndex !== null) {
      const indexGap = block.firstSampleIndex - this.nextSampleIndex;
      if (indexGap > 0) {
        this.pushGap(Math.min(indexGap, this.capacity));
      }
    }
    this.pushRange(block, 0, block.sampleCount);
    this.finish(block, nowMs);
  }

  sampleDisplay(nowMs: number): ActivityDisplay {
    const byLabel = new Map<string, ChannelHighlight>();
    const fade = this.fadeFactor(nowMs);
    const blend = this.blend(nowMs);
    for (let index = 0; index < this.labels.length; index += 1) {
      const previous = this.previousRms?.[index] ?? this.currentRms?.[index] ?? 0;
      const current = this.currentRms?.[index] ?? 0;
      const rmsUv = previous + (current - previous) * blend;
      const intensity = Math.min(1, Math.max(0, rmsUv / RMS_FULL_SCALE_UV)) * fade;
      byLabel.set(this.labels[index] as string, { rmsUv, intensity });
    }
    return {
      health: this.health(),
      synthetic: this.synthetic,
      missingSamples: blend >= 1 ? this.missingSamples : this.previousMissing,
      error: this.error,
      byLabel,
    };
  }

  private health(): HighlightHealth {
    if (this.currentRms === null) {
      return 'waiting';
    }
    return this.link === 'fading' ? 'fading' : 'live';
  }

  private fadeFactor(nowMs: number): number {
    if (this.link !== 'fading' || this.fadeAnchorMs === null) {
      return 1;
    }
    const ageMs = Math.max(0, nowMs - this.fadeAnchorMs);
    return Math.exp(-ageMs / (STALE_FADE_SECONDS * 1000));
  }

  private blend(nowMs: number): number {
    if (this.previousRms === null || this.currentRms === null) {
      return 1;
    }
    const span = Math.max(1, this.currentAtMs - this.previousAtMs);
    return Math.min(1, Math.max(0, (nowMs - this.currentAtMs) / span));
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
    streamId: string,
  ): void {
    this.labels = labels.slice();
    this.units = units.slice();
    this.types = types.slice();
    this.references = references.slice();
    this.provenanceKind = provenanceKind;
    this.rateHz = rate;
    this.capacity = capacity;
    this.rings = labels.map(() => new Float64Array(capacity));
    this.write = 0;
    this.count = 0;
    this.streamId = streamId;
    this.nextSampleIndex = null;
    this.lastSampleTimeUs = null;
    this.lastPublishMs = null;
    this.previousRms = null;
    this.currentRms = null;
    this.missingSamples = 0;
    this.previousMissing = 0;
    this.error = null;
    this.synthetic = provenanceKind === 'synthetic';
  }

  private fail(message: string): void {
    this.labels = [];
    this.units = [];
    this.types = [];
    this.references = [];
    this.provenanceKind = null;
    this.rings = [];
    this.write = 0;
    this.count = 0;
    this.capacity = 0;
    this.rateHz = 0;
    this.streamId = null;
    this.nextSampleIndex = null;
    this.lastSampleTimeUs = null;
    this.lastPublishMs = null;
    this.previousRms = null;
    this.currentRms = null;
    this.missingSamples = 0;
    this.previousMissing = 0;
    this.synthetic = false;
    this.error = message;
    this.emit();
  }

  private ingest(block: EegBlock, nowMs: number): void {
    this.pushRange(block, 0, block.sampleCount);
    this.finish(block, nowMs);
  }

  private pushGap(slots: number): void {
    for (let slot = 0; slot < slots; slot += 1) {
      for (const ring of this.rings) {
        ring[this.write] = Number.NaN;
      }
      this.advance();
    }
  }

  private pushRange(block: EegBlock, fromSample: number, toSample: number): void {
    for (let sample = fromSample; sample < toSample; sample += 1) {
      for (let channel = 0; channel < this.rings.length; channel += 1) {
        const value = block.samples[channel]?.[sample];
        const ring = this.rings[channel] as Float64Array;
        ring[this.write] = typeof value === 'number' && Number.isFinite(value) ? value : Number.NaN;
      }
      this.advance();
    }
  }

  private advance(): void {
    this.write = (this.write + 1) % this.capacity;
    this.count = Math.min(this.capacity, this.count + 1);
  }

  private finish(block: EegBlock, nowMs: number): void {
    const periodUs = 1_000_000 / this.rateHz;
    this.streamId = block.streamId;
    this.nextSampleIndex = block.firstSampleIndex + block.sampleCount;
    this.lastSampleTimeUs = block.firstSampleTimeUs + (block.sampleCount - 1) * periodUs;
    if (this.lastPublishMs === null || nowMs - this.lastPublishMs >= ACTIVITY_UPDATE_INTERVAL_MS) {
      this.publish(nowMs);
    }
  }

  private publish(nowMs: number): void {
    const rms = new Float64Array(this.labels.length);
    let missing = 0;
    const occupied = this.count;
    const start = this.count === this.capacity ? this.write : 0;
    for (let channel = 0; channel < this.rings.length; channel += 1) {
      const ring = this.rings[channel] as Float64Array;
      let sum = 0;
      let n = 0;
      let gaps = 0;
      for (let step = 0; step < occupied; step += 1) {
        const value = ring[(start + step) % this.capacity] as number;
        if (Number.isFinite(value)) {
          sum += value * value;
          n += 1;
        } else {
          gaps += 1;
        }
      }
      rms[channel] = n === 0 ? 0 : Math.sqrt(sum / n);
      missing = gaps;
    }
    this.previousMissing = this.currentRms === null ? missing : this.missingSamples;
    this.missingSamples = missing;
    this.previousRms = this.currentRms ?? rms;
    this.previousAtMs = this.currentRms === null ? nowMs : this.currentAtMs;
    this.currentRms = rms;
    this.currentAtMs = nowMs;
    this.lastPublishMs = nowMs;
    this.emit();
  }

  private emit(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }
}
