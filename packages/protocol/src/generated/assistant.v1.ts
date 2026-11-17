/**
 * GENERATED FILE - DO NOT EDIT.
 * Source: packages/protocol/schemas/assistant.v1.schema.json
 * Regenerate: yarn nx run @neuro-observatory/protocol:generate-types
 */

/**
 * Neuro Observatory assistant contract v1. Findings and commands are separate from EEG stream v2. A finding stores summaries, not raw samples (ADR-0016).
 */
export type AssistantDocument = AssistantSnapshot | IntentResult;
export type SchemaVersion = 1;
export type Counter = number;
export type Id = string;
export type ShortText = string;
export type Signed = number;
export type Line = string;

export interface AssistantSnapshot {
  type: 'assistant.snapshot';
  schemaVersion: SchemaVersion;
  sessionGeneration: Counter;
  streamId: string | null;
  source: 'synthetic' | 'replay';
  recordingId: string | null;
  paused: boolean;
  evidence: 'waiting' | 'warming' | 'baseline-unlocked' | 'ready' | 'insufficient' | 'stale';
  model: 'unavailable' | 'ready' | 'starting';
  classifier: 'disabled';
  analysisSamplesExpired: Counter;
  /**
   * @maxItems 200
   */
  findings: Finding[];
  /**
   * @maxItems 100
   */
  markers: Marker[];
  /**
   * @maxItems 20
   */
  lines: Line[];
}
export interface Finding {
  findingId: Id;
  sessionGeneration: Counter;
  streamId: Id;
  recordingId: string | null;
  sourceKind: 'synthetic' | 'device';
  deviceId: ShortText;
  method: 'band-power' | 'blink-heuristic';
  methodVersion: '1';
  band: 'theta' | 'alpha' | 'beta' | 'none';
  firstSampleIndex: Counter;
  lastSampleIndex: Counter;
  firstSampleTimeUs: Counter;
  lastSampleTimeUs: Counter;
  nominalSampleRateHz: number;
  /**
   * @minItems 1
   * @maxItems 64
   */
  channels: ChannelMeasurement[];
  quality: 'good' | 'insufficient' | 'stale';
  synthetic: boolean;
}
export interface ChannelMeasurement {
  index: Counter;
  label: ShortText;
  reference: ShortText;
  unit: 'uV';
  powerUv2: Signed;
  baselineUv2: Signed;
  changeDb: Signed;
  rmsUv: Signed;
  acceptedSampleFraction: number;
  quality: 'good' | 'insufficient' | 'stale';
}
export interface Marker {
  markerId: Id;
  sessionGeneration: Counter;
  streamId: Id;
  sampleIndex: Counter;
  label: ShortText;
}
export interface IntentResult {
  type: 'assistant.intent-result';
  schemaVersion: SchemaVersion;
  ok: boolean;
  intent:
    | 'emphasize_channels'
    | 'seek_to_finding'
    | 'add_marker'
    | 'lock_baseline'
    | 'set_display_mode'
    | 'answer'
    | 'clarify'
    | 'cancelled';
  message: Line;
  /**
   * @maxItems 64
   */
  channels: ShortText[];
  primaryChannel: string | null;
  /**
   * @maxItems 8
   */
  findingIds: Id[];
  displayMode: 'pial' | 'white' | 'inflated' | 'holographic' | 'grid' | null;
  seekSampleIndex: number | null;
  sessionGeneration: Counter;
  streamId: string | null;
}
