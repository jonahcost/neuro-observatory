import { describe, expect, it } from 'vitest';
import type { EEGFrame } from '@neuro-observatory/protocol';

describe('EEG protocol', () => {
  it('represents a 16-channel EEG frame', () => {
    const frame: EEGFrame = {
      schemaVersion: 1,
      deviceId: 'simulated-eeg',
      sequence: 0,
      timestampMs: 0,
      sampleRateHz: 125,
      channelLabels: Array.from({ length: 16 }, (_, i) => `Ch${i + 1}`),
      samplesUv: Array.from({ length: 16 }, () => [0]),
    };

    expect(frame.channelLabels).toHaveLength(16);
    expect(frame.samplesUv).toHaveLength(16);
    expect(frame.sampleRateHz).toBe(125);
  });
});
