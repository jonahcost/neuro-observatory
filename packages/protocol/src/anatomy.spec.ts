import { readdirSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  parseAnatomyAsset,
  parseAnatomyCatalog,
  parseAnatomyDocument,
  surfaceGeometryIssue,
  vertexLabelsIssue,
} from './anatomy';
import type { AnatomyAsset, Parcellation, SurfaceMesh } from './generated/anatomy-asset.v1';
import { ANATOMY_FIXTURE_ROOT, manifestCases, readFixtureJson, readFixtureText } from './testing/fixtures';

describe('anatomy v1 contract fixtures', () => {
  const cases = manifestCases(ANATOMY_FIXTURE_ROOT);

  it('covers every outcome kind and every fixture file', () => {
    expect([...new Set(cases.map((c) => c.expect))].sort()).toEqual([
      'json',
      'schema',
      'semantic',
      'unsupported-version',
      'valid',
    ]);
    const onDisk = ['valid', 'invalid'].flatMap((dir) =>
      readdirSync(`${ANATOMY_FIXTURE_ROOT}/${dir}`).map((name) => `${dir}/${name}`),
    );
    expect(onDisk.sort()).toEqual(cases.map((c) => c.file).sort());
  });

  it.each(cases.map((c) => [c.file, c] as const))('%s', (_file, testCase) => {
    const result = parseAnatomyDocument(readFixtureText(testCase.file, ANATOMY_FIXTURE_ROOT));
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

describe('typed anatomy parsers', () => {
  it('reject a document of the other type', () => {
    const catalog = readFixtureText('valid/catalog-one-asset.json', ANATOMY_FIXTURE_ROOT);
    const asset = readFixtureText('valid/asset-tetrahedra.json', ANATOMY_FIXTURE_ROOT);
    expect(parseAnatomyCatalog(catalog).ok).toBe(true);
    expect(parseAnatomyAsset(asset).ok).toBe(true);
    expect(parseAnatomyAsset(catalog)).toMatchObject({ ok: false, error: { kind: 'schema' } });
    expect(parseAnatomyCatalog(asset)).toMatchObject({ ok: false, error: { kind: 'schema' } });
  });

  it('never throws on garbage', () => {
    for (const raw of ['', 'null', '42', '[]', '{}', '"anatomy.asset"']) {
      expect(parseAnatomyDocument(raw).ok).toBe(false);
    }
  });
});

describe('surfaceGeometryIssue', () => {
  const asset = readFixtureJson<AnatomyAsset>('valid/asset-tetrahedra.json', ANATOMY_FIXTURE_ROOT);
  const lhPial = asset.surfaces[0] as SurfaceMesh;
  // Tetrahedron inside lh pial bounds: x in [-20, -10], y and z in [0, 10].
  const positions = () => new Float32Array([-20, 0, 0, -10, 0, 0, -20, 10, 0, -20, 0, 10]);
  const indices = () => new Uint32Array([0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3]);

  it('accepts buffers matching the manifest', () => {
    expect(surfaceGeometryIssue(lhPial, positions(), indices())).toBeNull();
  });

  it('rejects wrong lengths', () => {
    expect(surfaceGeometryIssue(lhPial, positions().subarray(3), indices())).toMatch(/positions has 9/);
    expect(surfaceGeometryIssue(lhPial, positions(), indices().subarray(3))).toMatch(/indices has 9/);
  });

  it('rejects non-finite coordinates and coordinates outside the bounds', () => {
    const nan = positions();
    nan[4] = Number.NaN;
    expect(surfaceGeometryIssue(lhPial, nan, indices())).toMatch(/position 1 is not finite/);
    const outside = positions();
    outside[0] = -25;
    expect(surfaceGeometryIssue(lhPial, outside, indices())).toMatch(/outside the declared bounds/);
  });

  it('rejects out-of-range triangle indices', () => {
    const bad = indices();
    bad[11] = 4;
    expect(surfaceGeometryIssue(lhPial, positions(), bad)).toMatch(/triangle 3 references a vertex outside 0..3/);
  });
});

describe('vertexLabelsIssue', () => {
  const asset = readFixtureJson<AnatomyAsset>('valid/asset-tetrahedra.json', ANATOMY_FIXTURE_ROOT);
  const parcellation = asset.parcellations[0] as Parcellation;

  it('accepts declared labels and -1 for unlabelled vertices', () => {
    expect(vertexLabelsIssue(parcellation, new Int32Array([0, 1, 1, -1]))).toBeNull();
  });

  it('rejects wrong lengths and undeclared labels', () => {
    expect(vertexLabelsIssue(parcellation, new Int32Array([0, 1, 1]))).toMatch(/has 3 values/);
    expect(vertexLabelsIssue(parcellation, new Int32Array([0, 1, 7, -1]))).toMatch(/vertex 2 has undeclared label 7/);
  });
});
