// Generates src/generated/*.ts from the canonical JSON Schemas.
// Usage: node scripts/generate-types.mjs [--check]
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { compileFromFile } from 'json-schema-to-typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export const schemas = ['eeg-stream.v2', 'anatomy-asset.v1'].map((name) => ({
  name,
  schemaPath: resolve(root, `schemas/${name}.schema.json`),
  outputPath: resolve(root, `src/generated/${name}.ts`),
}));

function banner(name) {
  return `/**
 * GENERATED FILE - DO NOT EDIT.
 * Source: packages/protocol/schemas/${name}.schema.json
 * Regenerate: yarn nx run @neuro-observatory/protocol:generate-types
 */`;
}

export async function generateTypes(entry) {
  return compileFromFile(entry.schemaPath, {
    bannerComment: banner(entry.name),
    cwd: resolve(root, 'schemas'),
    additionalProperties: false,
    ignoreMinAndMaxItems: true,
    unreachableDefinitions: false,
    style: { singleQuote: true },
  });
}

async function main() {
  const check = process.argv.includes('--check');
  let stale = false;
  for (const entry of schemas) {
    const generated = await generateTypes(entry);
    if (check) {
      const current = await readFile(entry.outputPath, 'utf8').catch(() => '');
      if (current !== generated) {
        console.error(`${entry.outputPath} is out of date. Run generate-types.`);
        stale = true;
      }
    } else {
      await writeFile(entry.outputPath, generated);
      console.log(`Wrote ${entry.outputPath}`);
    }
  }
  if (stale) {
    process.exit(1);
  }
  if (check) {
    console.log('Generated protocol types are up to date.');
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await main();
}
