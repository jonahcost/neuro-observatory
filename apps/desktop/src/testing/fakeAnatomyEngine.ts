import type { AnatomyAsset, AnatomyCatalog, AnatomyKind, SurfaceKind } from '@neuro-observatory/protocol';

/** Test-only: small contract-valid assets and an in-memory engine (no network, no real data). */

export type Hash = (bytes: Uint8Array) => string;

export interface FakeAsset {
  asset: AnatomyAsset;
  files: Map<string, Uint8Array>;
}

function bytes(array: Float32Array | Uint32Array | Int32Array): Uint8Array {
  return new Uint8Array(array.buffer.slice(0));
}

function tetrahedron(xMin: number): Float32Array {
  return new Float32Array([xMin, 0, 0, xMin + 10, 0, 0, xMin, 10, 0, xMin, 0, 10]);
}

const TETRA_FACES = new Uint32Array([0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3]);

export function makeFakeAsset(options: {
  assetId: string;
  kind: AnatomyKind;
  displayName: string;
  hash: Hash;
  surfaces?: SurfaceKind[];
  atlas?: boolean;
}): FakeAsset {
  const files = new Map<string, Uint8Array>();
  const ref = (file: string, dtype: 'float32' | 'uint32' | 'int32', data: Uint8Array) => {
    files.set(file, data);
    return { file, dtype, byteLength: data.byteLength, sha256: options.hash(data) };
  };
  const surfaces = (options.surfaces ?? ['pial', 'inflated']).flatMap((surface) =>
    (['lh', 'rh'] as const).map((hemisphere) => {
      const xMin = hemisphere === 'lh' ? -20 : 10;
      return {
        hemisphere,
        surface,
        vertexCount: 4,
        triangleCount: 4,
        positions: ref(`${hemisphere}.${surface}.positions.f32`, 'float32', bytes(tetrahedron(xMin))),
        indices: ref(`${hemisphere}.${surface}.indices.u32`, 'uint32', bytes(TETRA_FACES)),
        boundsMm: { min: [xMin, 0, 0], max: [xMin + 10, 10, 10] },
      };
    }),
  );
  const parcellations = options.atlas
    ? (['lh', 'rh'] as const).map((hemisphere) => ({
        atlas: 'aparc',
        description: 'Desikan-Killiany cortical atlas (FreeSurfer aparc)',
        hemisphere,
        vertexCount: 4,
        labels: [
          { index: 0, name: 'unknown', rgba: [25, 5, 25, 255] },
          { index: 1, name: 'precentral', rgba: [60, 20, 220, 255] },
        ],
        vertexLabels: ref(`${hemisphere}.aparc.labels.i32`, 'int32', bytes(new Int32Array([-1, 0, 1, 1]))),
      }))
    : [];
  const asset: AnatomyAsset = {
    type: 'anatomy.asset',
    schemaVersion: 1,
    assetId: options.assetId,
    subject: {
      datasetId: options.kind === 'template' ? 'fsaverage' : 'ds000248',
      datasetVersion: '1',
      subjectId: options.kind === 'template' ? 'fsaverage' : 'sub-01',
      sessionId: null,
      displayName: options.displayName,
    },
    anatomyKind: options.kind,
    acquisition:
      options.kind === 'template'
        ? { fieldStrengthTesla: null, sequence: null, scanner: null, source: 'not-applicable' }
        : { fieldStrengthTesla: 1.5, sequence: 'MPRAGE', scanner: 'Siemens Sonata 1.5T', source: 'dataset-readme' },
    coordinateFrame: 'freesurfer-surface-ras',
    units: 'mm',
    transforms: [],
    surfaces,
    parcellations,
    provenance: {
      pipeline: 'neuro-engine.anatomy.prepare',
      pipelineVersion: '1',
      preparedAtUtc: '2026-10-30T12:00:00Z',
      tools: [],
      sources: [{ path: 'raw/synthetic/surf/lh.pial', bytes: 1, sha256: '0'.repeat(64) }],
    },
    license: { id: 'CC0-1.0', url: 'https://creativecommons.org/publicdomain/zero/1.0/', attribution: 'Synthetic test asset.' },
  };
  return { asset, files };
}

export function catalogFor(assets: FakeAsset[], defaultAssetId: string | null): AnatomyCatalog {
  return {
    type: 'anatomy.catalog',
    schemaVersion: 1,
    defaultAssetId,
    assets: assets.map(({ asset }) => ({
      assetId: asset.assetId,
      subject: asset.subject,
      anatomyKind: asset.anatomyKind,
      surfaces: [...new Set(asset.surfaces.map((s) => s.surface))],
      atlases: [...new Set(asset.parcellations.map((p) => p.atlas))],
      licenseId: asset.license.id,
    })),
  };
}

export interface FakeEngine {
  fetchImpl: typeof fetch;
  requests: string[];
  /** Replace a response body (raw JSON text or bytes) by path, e.g. to inject corruption. */
  override: Map<string, { status?: number; body: string | Uint8Array }>;
}

export function fakeAnatomyEngine(baseUrl: string, catalog: AnatomyCatalog | string, assets: FakeAsset[]): FakeEngine {
  const requests: string[] = [];
  const override = new Map<string, { status?: number; body: string | Uint8Array }>();
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).slice(baseUrl.length);
    requests.push(path);
    if (init?.signal?.aborted) {
      throw new DOMException('aborted', 'AbortError');
    }
    const custom = override.get(path);
    if (custom) {
      return new Response(custom.body as BodyInit, { status: custom.status ?? 200 });
    }
    if (path === '/catalog') {
      return new Response(typeof catalog === 'string' ? catalog : JSON.stringify(catalog));
    }
    const match = /^\/assets\/([^/]+)\/(manifest\.json|files\/([^/]+))$/.exec(path);
    const fake = assets.find((a) => a.asset.assetId === decodeURIComponent(match?.[1] ?? ''));
    if (match && fake) {
      if (match[2] === 'manifest.json') {
        return new Response(JSON.stringify(fake.asset));
      }
      const data = fake.files.get(decodeURIComponent(match[3] ?? ''));
      if (data) {
        return new Response(data as BodyInit);
      }
    }
    return new Response(JSON.stringify({ error: { code: 'unknown-asset', message: 'not found' } }), { status: 404 });
  }) as typeof fetch;
  return { fetchImpl, requests, override };
}
