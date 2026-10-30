import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ParseErrorKind } from '../validate';

export const FIXTURE_ROOT = resolve(import.meta.dirname, '../../fixtures/v2');

export interface ManifestCase {
  file: string;
  expect: 'valid' | ParseErrorKind;
  description: string;
  context?: string;
}

export function readFixtureText(relativePath: string): string {
  return readFileSync(resolve(FIXTURE_ROOT, relativePath), 'utf8');
}

export function readFixtureJson<T>(relativePath: string): T {
  return JSON.parse(readFixtureText(relativePath)) as T;
}

export function manifestCases(): ManifestCase[] {
  return readFixtureJson<{ cases: ManifestCase[] }>('manifest.json').cases;
}
