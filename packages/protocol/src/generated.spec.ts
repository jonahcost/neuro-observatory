import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { generateTypes, outputPath } from '../scripts/generate-types.mjs';

describe('generated protocol types', () => {
  it('match the canonical JSON Schema', async () => {
    const committed = readFileSync(outputPath, 'utf8');
    expect(committed).toBe(await generateTypes());
  });
});
