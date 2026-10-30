import { describe, expect, it } from 'vitest';
import { manifestCases, readFixtureJson, readFixtureText } from './testing/fixtures';
import { parseServerMessage, validateServerMessage } from './validate';
import type { EegBlock, StreamMetadata } from './generated/eeg-stream.v2';

describe('protocol v2 contract fixtures', () => {
  const cases = manifestCases();

  it('covers every outcome kind', () => {
    const kinds = new Set(cases.map((c) => c.expect));
    expect([...kinds].sort()).toEqual(['json', 'schema', 'semantic', 'unsupported-version', 'valid']);
  });

  it.each(cases.map((c) => [c.file, c] as const))('%s', (_file, testCase) => {
    const metadata = testCase.context ? readFixtureJson<StreamMetadata>(testCase.context) : undefined;
    const result = parseServerMessage(readFixtureText(testCase.file), { metadata });
    if (testCase.expect === 'valid') {
      expect(result).toMatchObject({ ok: true });
    } else {
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.error.kind).toBe(testCase.expect);
        expect(result.error.detail.length).toBeGreaterThan(0);
      }
    }
  });
});

describe('parseServerMessage', () => {
  const metadata = readFixtureJson<StreamMetadata>('valid/metadata-synthetic-16ch.json');
  const block = readFixtureJson<EegBlock>('valid/block-16ch.json');

  it('returns the typed message for valid input', () => {
    const result = parseServerMessage(JSON.stringify(block), { metadata });
    expect(result.ok && result.message.type).toBe('eeg.block');
  });

  it('accepts a block without metadata context (stream checks are skipped)', () => {
    expect(parseServerMessage(JSON.stringify(block)).ok).toBe(true);
  });

  it('never echoes sample values in error details', () => {
    const bad = { ...block, samples: [[123456.789, 'x']] };
    const result = validateServerMessage(bad);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.detail).not.toContain('123456.789');
    }
  });

  it('does not throw on non-string-like garbage', () => {
    for (const raw of ['', 'null', '42', '"text"', '{}', '[]']) {
      const result = parseServerMessage(raw);
      expect(result.ok).toBe(false);
    }
  });

  it('round-trips float64 values exactly through JSON', () => {
    const values = [0.1 + 0.2, -1e-12, 123.456789012345, Number.MIN_VALUE, 2 ** 52 + 0.5];
    const exact = { ...block, samples: block.samples.map(() => values), sampleCount: values.length };
    const result = parseServerMessage(JSON.stringify(exact), { metadata });
    expect(result.ok).toBe(true);
    if (result.ok && result.message.type === 'eeg.block') {
      expect(result.message.samples[0]).toEqual(values);
    }
  });
});
