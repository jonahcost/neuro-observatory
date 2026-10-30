import { readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { FIXTURE_ROOT, readFixtureJson } from './testing/fixtures';
import { StreamIntegrityTracker, sampleTimeUs, type IntegrityCounters } from './integrity';
import { validateServerMessage } from './validate';
import type { EegBlock, ServerMessage, StreamMetadata } from './generated/eeg-stream.v2';

interface Scenario {
  description: string;
  steps: { message: ServerMessage; expect: string }[];
  expectedCounters: IntegrityCounters;
}

const scenarioFiles = readdirSync(resolve(FIXTURE_ROOT, 'integrity')).filter((f) => f.endsWith('.json'));

describe('StreamIntegrityTracker shared scenarios', () => {
  it('has scenarios to run', () => {
    expect(scenarioFiles.length).toBeGreaterThanOrEqual(7);
  });

  it.each(scenarioFiles)('%s', (file) => {
    const scenario = readFixtureJson<Scenario>(`integrity/${file}`);
    const tracker = new StreamIntegrityTracker();
    for (const step of scenario.steps) {
      expect(validateServerMessage(step.message).ok).toBe(true);
      const verdict =
        step.message.type === 'stream.metadata'
          ? tracker.onMetadata(step.message)
          : step.message.type === 'eeg.block'
            ? tracker.onBlock(step.message)
            : 'ignored';
      expect(verdict).toBe(step.expect);
    }
    expect(tracker.snapshot()).toEqual(scenario.expectedCounters);
  });
});

describe('sampleTimeUs', () => {
  it('derives per-sample times from the first-sample time and nominal rate', () => {
    const metadata = readFixtureJson<StreamMetadata>('valid/metadata-synthetic-16ch.json');
    const block = readFixtureJson<EegBlock>('valid/block-16ch.json');
    expect(sampleTimeUs(block, metadata, 0)).toBe(block.firstSampleTimeUs);
    expect(sampleTimeUs(block, metadata, 4)).toBe(block.firstSampleTimeUs + 32_000);
  });
});
