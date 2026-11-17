import { readdirSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parseAssistantDocument } from './assistant';
import { ASSISTANT_FIXTURE_ROOT, manifestCases, readFixtureText } from './testing/fixtures';

describe('assistant v1 contract fixtures', () => {
  const cases = manifestCases(ASSISTANT_FIXTURE_ROOT);

  it('covers every outcome kind and every fixture file', () => {
    expect([...new Set(cases.map((entry) => entry.expect))].sort()).toEqual([
      'json',
      'schema',
      'semantic',
      'unsupported-version',
      'valid',
    ]);
    const onDisk = ['valid', 'invalid'].flatMap((dir) =>
      readdirSync(`${ASSISTANT_FIXTURE_ROOT}/${dir}`).map((name) => `${dir}/${name}`),
    );
    expect(onDisk.sort()).toEqual(cases.map((entry) => entry.file).sort());
  });

  it.each(cases.map((entry) => [entry.file, entry] as const))('%s', (_file, testCase) => {
    const result = parseAssistantDocument(readFixtureText(testCase.file, ASSISTANT_FIXTURE_ROOT));
    if (testCase.expect === 'valid') {
      expect(result.ok).toBe(true);
      if (result.ok) {
        expect(JSON.stringify(result.document)).not.toContain('"samples"');
      }
      return;
    }
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe(testCase.expect);
      expect(result.error.detail.length).toBeGreaterThan(0);
    }
  });
});
