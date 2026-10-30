// Generates src/generated/eeg-stream.v2.ts from the canonical JSON Schema.
// Usage: node scripts/generate-types.mjs [--check]
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { compileFromFile } from 'json-schema-to-typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const schemaPath = resolve(root, 'schemas/eeg-stream.v2.schema.json');
export const outputPath = resolve(root, 'src/generated/eeg-stream.v2.ts');

const BANNER = `/**
 * GENERATED FILE - DO NOT EDIT.
 * Source: packages/protocol/schemas/eeg-stream.v2.schema.json
 * Regenerate: yarn nx run @neuro-observatory/protocol:generate-types
 */`;

export async function generateTypes() {
  return compileFromFile(schemaPath, {
    bannerComment: BANNER,
    cwd: resolve(root, 'schemas'),
    additionalProperties: false,
    ignoreMinAndMaxItems: true,
    unreachableDefinitions: false,
    style: { singleQuote: true },
  });
}

async function main() {
  const generated = await generateTypes();
  if (process.argv.includes('--check')) {
    const current = await readFile(outputPath, 'utf8').catch(() => '');
    if (current !== generated) {
      console.error(`${outputPath} is out of date. Run generate-types.`);
      process.exit(1);
    }
    console.log('Generated protocol types are up to date.');
    return;
  }
  await writeFile(outputPath, generated);
  console.log(`Wrote ${outputPath}`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await main();
}
