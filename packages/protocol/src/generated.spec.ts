import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { generateTypes, schemas } from '../scripts/generate-types.mjs';

describe('generated protocol types', () => {
  it.each(schemas.map((entry) => [entry.name, entry] as const))('%s matches its canonical JSON Schema', async (_name, entry) => {
    const committed = readFileSync(entry.outputPath, 'utf8');
    expect(committed).toBe(await generateTypes(entry));
  });
});
