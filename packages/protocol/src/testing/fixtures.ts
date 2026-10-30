import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ParseErrorKind } from '../validate';

export const FIXTURE_ROOT = resolve(import.meta.dirname, '../../fixtures/v2');
export const ANATOMY_FIXTURE_ROOT = resolve(import.meta.dirname, '../../fixtures/anatomy-v1');

export interface ManifestCase {
  file: string;
  expect: 'valid' | ParseErrorKind;
  description: string;
  context?: string;
}

export function readFixtureText(relativePath: string, root = FIXTURE_ROOT): string {
  return readFileSync(resolve(root, relativePath), 'utf8');
}

export function readFixtureJson<T>(relativePath: string, root = FIXTURE_ROOT): T {
  return JSON.parse(readFixtureText(relativePath, root)) as T;
}

export function manifestCases(root = FIXTURE_ROOT): ManifestCase[] {
  return readFixtureJson<{ cases: ManifestCase[] }>('manifest.json', root).cases;
}
