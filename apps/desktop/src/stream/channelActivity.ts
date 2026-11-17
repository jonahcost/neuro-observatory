import type { EegBlock, StreamMetadata } from '@neuro-observatory/protocol';
import type { ConnectionState, StreamHealth } from './eegStreamClient';

/** Trailing window of accepted samples, in seconds. */
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
  byLabel: ReadonlyMap<string, ChannelHighlight>;
}

export interface StreamLink {
  health: StreamHealth;
  connection: ConnectionState;
}

/**
 * One-second per-channel RMS for sensor highlights.
 *
 * Fed by the same `onBlock` path as `WaveformBuffer`, with its own ring.
 * Samples stay out of React state. `sampleDisplay` interpolates the last
 * two published RMS snapshots so the render loop does not recompute them.
 * A non-live stream multiplies intensity by an exponential fade.
 */
export class ChannelActivity {
  private labels: string[] = [];
  private rings: Float64Array[] = [];
  private write = 0;
  private count = 0;
  private capacity = 0;
  private streamId: string | null = null;
  private lastPublishMs: number | null = null;
  private previousRms: Float64Array | null = null;
  private currentRms: Float64Array | null = null;
  private previousAtMs = 0;
  private currentAtMs = 0;
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
    const capacity = Math.ceil(rate * ACTIVITY_WINDOW_SECONDS);
    if (labels.length === 0 || labels.length > MAX_CHANNELS || capacity > MAX_SAMPLES) {
      return;
    }
    const layoutChanged =
      this.streamId !== metadata.streamId ||
      capacity !== this.capacity ||
      labels.length !== this.labels.length ||
      labels.some((label, index) => label !== this.labels[index]);
    if (layoutChanged) {
      this.labels = labels;
      this.capacity = capacity;
      this.rings = labels.map(() => new Float64Array(capacity));
      this.write = 0;
      this.count = 0;
      this.streamId = metadata.streamId;
      this.previousRms = null;
      this.currentRms = null;
      this.lastPublishMs = null;
    }
    this.synthetic = metadata.provenance.kind === 'synthetic';
    this.push(block);
    if (this.lastPublishMs === null || nowMs - this.lastPublishMs >= ACTIVITY_UPDATE_INTERVAL_MS) {
      this.publish(nowMs);
    }
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
    return { health: this.health(), synthetic: this.synthetic, byLabel };
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

  private push(block: EegBlock): void {
    for (let sample = 0; sample < block.sampleCount; sample += 1) {
      for (let channel = 0; channel < this.rings.length; channel += 1) {
        const value = block.samples[channel]?.[sample];
        const ring = this.rings[channel] as Float64Array;
        ring[this.write] = typeof value === 'number' && Number.isFinite(value) ? value : Number.NaN;
      }
      this.write = (this.write + 1) % this.capacity;
      this.count = Math.min(this.capacity, this.count + 1);
    }
  }

  private publish(nowMs: number): void {
    const rms = new Float64Array(this.labels.length);
    for (let channel = 0; channel < this.rings.length; channel += 1) {
      const ring = this.rings[channel] as Float64Array;
      let sum = 0;
      let n = 0;
      const occupied = this.count;
      const start = this.count === this.capacity ? this.write : 0;
      for (let step = 0; step < occupied; step += 1) {
        const value = ring[(start + step) % this.capacity] as number;
        if (Number.isFinite(value)) {
          sum += value * value;
          n += 1;
        }
      }
      rms[channel] = n === 0 ? 0 : Math.sqrt(sum / n);
    }
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
