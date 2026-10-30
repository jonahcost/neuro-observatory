import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { catalogFor, fakeAnatomyEngine, makeFakeAsset } from '../testing/fakeAnatomyEngine';
import { AnatomyLoadError, anatomyApiUrlFromEnv, createAnatomyClient, DEFAULT_ANATOMY_API_URL } from './anatomyClient';

const BASE = 'http://engine.test/api/anatomy/v1';
const hash = (data: Uint8Array) => createHash('sha256').update(data).digest('hex');
const sha256 = async (data: ArrayBuffer) => hash(new Uint8Array(data));

function setup(options: { atlas?: boolean } = {}) {
  const template = makeFakeAsset({ assetId: 'fsaverage-0001', kind: 'template', displayName: 'fsaverage', hash, ...options });
  const engine = fakeAnatomyEngine(BASE, catalogFor([template], template.asset.assetId), [template]);
  const client = createAnatomyClient({ baseUrl: `${BASE}/`, fetchImpl: engine.fetchImpl, sha256 });
  return { template, engine, client };
}

async function rejection(promise: Promise<unknown>): Promise<AnatomyLoadError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(AnatomyLoadError);
    return error as AnatomyLoadError;
  }
  throw new Error('expected a rejection');
}

describe('anatomy client', () => {
  it('loads catalog, manifest and verified surface buffers unchanged', async () => {
    const { client, template } = setup();
    const catalog = await client.fetchCatalog();
    expect(catalog.defaultAssetId).toBe('fsaverage-0001');
    const asset = await client.fetchAsset('fsaverage-0001');
    const surfaces = await client.loadSurfaces(asset, 'pial');
    expect(surfaces.map((s) => s.hemisphere)).toEqual(['lh', 'rh']);
    expect(Array.from(surfaces[0]?.positions ?? [])).toEqual(
      Array.from(new Float32Array(template.files.get('lh.pial.positions.f32')?.buffer ?? new ArrayBuffer(0))),
    );
    expect(surfaces[0]?.indices).toBeInstanceOf(Uint32Array);
  });

  it('loads parcellation labels including unlabelled vertices', async () => {
    const { client } = setup({ atlas: true });
    const asset = await client.fetchAsset('fsaverage-0001');
    const [lh] = await client.loadParcellations(asset, 'aparc');
    expect(Array.from(lh?.vertexLabels ?? [])).toEqual([-1, 0, 1, 1]);
    expect((await rejection(client.loadParcellations(asset, 'yeo7'))).kind).toBe('contract');
  });

  it('rejects documents that violate the contract', async () => {
    const { client, engine, template } = setup();
    engine.override.set('/catalog', { body: '{"type":"anatomy.catalog","schemaVersion":1}' });
    expect((await rejection(client.fetchCatalog())).kind).toBe('contract');
    engine.override.set('/assets/fsaverage-0001/manifest.json', { body: JSON.stringify({ ...template.asset, units: 'm' }) });
    expect((await rejection(client.fetchAsset('fsaverage-0001'))).kind).toBe('contract');
    engine.override.set('/assets/fsaverage-0001/manifest.json', {
      body: JSON.stringify({ ...template.asset, assetId: 'other-asset' }),
    });
    expect((await rejection(client.fetchAsset('fsaverage-0001'))).message).toContain('other-asset');
  });

  it('rejects buffers whose size, checksum or geometry differ from the manifest', async () => {
    const { client, engine, template } = setup();
    const asset = await client.fetchAsset('fsaverage-0001');
    const path = '/assets/fsaverage-0001/files/lh.pial.positions.f32';

    engine.override.set(path, { body: new Uint8Array(12) });
    expect((await rejection(client.loadSurfaces(asset, 'pial'))).message).toContain('bytes');

    const tampered = new Uint8Array(template.files.get('lh.pial.positions.f32') ?? []);
    tampered[0] = (tampered[0] ?? 0) ^ 0xff;
    engine.override.set(path, { body: tampered });
    expect((await rejection(client.loadSurfaces(asset, 'pial'))).message).toContain('SHA-256');

    // Correct checksum but positions outside the declared bounds.
    const outside = new Uint8Array(new Float32Array([-500, 0, 0, -10, 0, 0, -20, 10, 0, -20, 0, 10]).buffer);
    engine.override.set(path, { body: outside });
    const lying = {
      ...asset,
      surfaces: asset.surfaces.map((s) =>
        s.positions.file === 'lh.pial.positions.f32' ? { ...s, positions: { ...s.positions, sha256: hash(outside) } } : s,
      ),
    };
    const error = await rejection(client.loadSurfaces(lying, 'pial'));
    expect(error.kind).toBe('integrity');
    expect(error.message).toContain('outside the declared bounds');
  });

  it('reports HTTP and network failures with actionable messages', async () => {
    const { client, engine } = setup();
    engine.override.set('/catalog', { status: 503, body: '{"error":{"code":"x","message":"data directory unavailable"}}' });
    const http = await rejection(client.fetchCatalog());
    expect(http.kind).toBe('http');
    expect(http.message).toContain('503');
    expect(http.message).toContain('data directory unavailable');

    const offline = createAnatomyClient({
      baseUrl: BASE,
      fetchImpl: () => Promise.reject(new TypeError('Failed to fetch')),
      sha256,
    });
    const network = await rejection(offline.fetchCatalog());
    expect(network.kind).toBe('network');
    expect(network.message).toContain('127.0.0.1:8000');
  });

  it('reports cancellation as aborted', async () => {
    const { client } = setup();
    const controller = new AbortController();
    controller.abort();
    expect((await rejection(client.fetchCatalog(controller.signal))).kind).toBe('aborted');
  });

  it('classifies oversized JSON as integrity failure', async () => {
    const client = createAnatomyClient({
      baseUrl: BASE,
      fetchImpl: (() =>
        Promise.resolve(new Response('{}', { headers: { 'content-length': '9000000' } }))) as typeof fetch,
      sha256,
    });
    const error = await rejection(client.fetchCatalog());
    expect(error.kind).toBe('integrity');
    expect(error.message).toContain('exceeds');
  });

  it('retries stale immutable buffers once with cache reload', async () => {
    const { template, engine } = setup();
    const caches: Array<RequestCache | undefined> = [];
    let attempts = 0;
    const file = '/assets/fsaverage-0001/files/lh.pial.positions.f32';
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).slice(BASE.length);
      if (path === file) {
        caches.push(init?.cache);
        attempts += 1;
        if (attempts === 1) {
          return new Response(new Uint8Array(template.files.get('lh.pial.positions.f32') ?? []).fill(0xff));
        }
      }
      return engine.fetchImpl(input, init);
    }) as typeof fetch;
    const client = createAnatomyClient({ baseUrl: BASE, fetchImpl, sha256 });
    await client.loadSurfaces(template.asset, 'pial');
    expect(caches).toEqual(['default', 'reload']);
  });

  it('aborts sibling buffer requests after an integrity failure', async () => {
    const { template, engine } = setup();
    let siblingAborted = false;
    const broken = '/assets/fsaverage-0001/files/lh.pial.positions.f32';
    const delayed = '/assets/fsaverage-0001/files/rh.pial.positions.f32';
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).slice(BASE.length);
      if (path === broken) {
        return new Response(new Uint8Array(template.files.get('lh.pial.positions.f32') ?? []).fill(0xff));
      }
      if (path === delayed) {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            'abort',
            () => {
              siblingAborted = true;
              reject(new DOMException('aborted', 'AbortError'));
            },
            { once: true },
          );
        });
      }
      return engine.fetchImpl(input, init);
    }) as typeof fetch;
    const client = createAnatomyClient({ baseUrl: BASE, fetchImpl, sha256 });
    expect((await rejection(client.loadSurfaces(template.asset, 'pial'))).kind).toBe('integrity');
    expect(siblingAborted).toBe(true);
  });

  it('reads the API URL from the environment', () => {
    expect(anatomyApiUrlFromEnv({ VITE_NEURO_ENGINE_ANATOMY_URL: 'http://127.0.0.1:9000/x' })).toBe('http://127.0.0.1:9000/x');
    expect(anatomyApiUrlFromEnv({})).toBeUndefined();
    expect(DEFAULT_ANATOMY_API_URL).toBe('http://127.0.0.1:8000/api/anatomy/v1');
  });
});
