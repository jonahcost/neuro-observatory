import { describe, expect, it } from 'vitest';
import type { AssistantSnapshot, Finding, IntentResult } from '@neuro-observatory/protocol';
import { applyIntentResult, evidenceSelection } from './assistantActions';

function finding(): Finding {
  return {
    findingId: 'finding-alpha',
    sessionGeneration: 2,
    streamId: 'stream-replay',
    recordingId: 'alpha-step',
    sourceKind: 'synthetic',
    deviceId: 'replay-alpha-step',
    method: 'band-power',
    methodVersion: '1',
    band: 'alpha',
    firstSampleIndex: 2500,
    lastSampleIndex: 2749,
    firstSampleTimeUs: 20_000_000,
    lastSampleTimeUs: 21_992_000,
    nominalSampleRateHz: 125,
    channels: [
      {
        index: 14,
        label: 'O2',
        reference: 'synthetic',
        unit: 'uV',
        powerUv2: 1,
        baselineUv2: 1,
        changeDb: 9,
        rmsUv: 1,
        acceptedSampleFraction: 1,
        quality: 'good',
      },
      {
        index: 13,
        label: 'O1',
        reference: 'synthetic',
        unit: 'uV',
        powerUv2: 1,
        baselineUv2: 1,
        changeDb: 9,
        rmsUv: 1,
        acceptedSampleFraction: 1,
        quality: 'good',
      },
    ],
    quality: 'good',
    synthetic: true,
  };
}

function snapshot(source: AssistantSnapshot['source']): AssistantSnapshot {
  return {
    type: 'assistant.snapshot',
    schemaVersion: 1,
    sessionGeneration: 1,
    streamId: 'stream-a',
    source,
    recordingId: source === 'replay' ? 'alpha-step' : null,
    paused: false,
    evidence: 'ready',
    model: 'unavailable',
    classifier: 'disabled',
    analysisSamplesExpired: 0,
    findings: [finding()],
    markers: [],
    lines: ['O1 alpha power changed.'],
  };
}

describe('assistant view actions', () => {
  it('keeps one posterior primary and seeks only a replay of the same recording', () => {
    const live = evidenceSelection(snapshot('synthetic'), finding());
    expect(live.primary).toBe('O1');
    expect(live.channels).toEqual(['O2', 'O1']);
    expect(live.seek).toBe(false);
    expect(evidenceSelection(snapshot('replay'), finding()).seek).toBe(true);
  });

  it('maps a display-mode result onto the existing mode ids', () => {
    const result: IntentResult = {
      type: 'assistant.intent-result',
      schemaVersion: 1,
      ok: true,
      intent: 'set_display_mode',
      message: 'Showing Grid.',
      channels: [],
      primaryChannel: null,
      findingIds: [],
      displayMode: 'grid',
      seekSampleIndex: null,
      sessionGeneration: 1,
      streamId: 'stream-a',
    };
    expect(applyIntentResult(result).displayMode).toBe('grid');
  });
});
