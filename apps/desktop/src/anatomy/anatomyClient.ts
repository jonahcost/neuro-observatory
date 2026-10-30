import {
  parseAnatomyAsset,
  parseAnatomyCatalog,
  surfaceGeometryIssue,
  vertexLabelsIssue,
  type AnatomyAsset,
  type AnatomyCatalog,
  type BufferRef,
  type Hemisphere,
  type Parcellation,
  type SurfaceKind,
  type SurfaceMesh,
} from '@neuro-observatory/protocol';

export const DEFAULT_ANATOMY_API_URL = 'http://127.0.0.1:8000/api/anatomy/v1';

export type AnatomyErrorKind = 'network' | 'http' | 'contract' | 'integrity' | 'aborted';

export class AnatomyLoadError extends Error {
  constructor(
    readonly kind: AnatomyErrorKind,
    message: string,
  ) {
    super(message);
    this.name = 'AnatomyLoadError';
  }
}

export interface LoadedSurface {
  hemisphere: Hemisphere;
  surface: SurfaceKind;
  /** Surface RAS, millimetres, x/y/z interleaved; unchanged from the asset. */
  positions: Float32Array;
  indices: Uint32Array;
  boundsMm: SurfaceMesh['boundsMm'];
}

export interface LoadedParcellation {
  atlas: string;
  hemisphere: Hemisphere;
  description: string;
  labels: Parcellation['labels'];
  vertexLabels: Int32Array;
}

export interface AnatomyClient {
  fetchCatalog(signal?: AbortSignal): Promise<AnatomyCatalog>;
  fetchAsset(assetId: string, signal?: AbortSignal): Promise<AnatomyAsset>;
  loadSurfaces(asset: AnatomyAsset, surface: SurfaceKind, signal?: AbortSignal): Promise<LoadedSurface[]>;
  loadParcellations(asset: AnatomyAsset, atlas: string, signal?: AbortSignal): Promise<LoadedParcellation[]>;
}

export interface AnatomyClientOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  /** SHA-256 hex digest; defaults to Web Crypto. */
  sha256?: (data: ArrayBuffer) => Promise<string>;
}

const LITTLE_ENDIAN = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

async function webCryptoSha256(data: ArrayBuffer): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new AnatomyLoadError('integrity', 'Web Crypto is unavailable, so asset checksums cannot be verified');
  }
  const digest = new Uint8Array(await subtle.digest('SHA-256', data));
  return Array.from(digest, (b) => b.toString(16).padStart(2, '0')).join('');
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

export function anatomyApiUrlFromEnv(env: Record<string, unknown>): string | undefined {
  const value = env['VITE_NEURO_ENGINE_ANATOMY_URL'];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

export function createAnatomyClient(options: AnatomyClientOptions = {}): AnatomyClient {
  const baseUrl = (options.baseUrl ?? DEFAULT_ANATOMY_API_URL).replace(/\/+$/, '');
  const fetchImpl = options.fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
  const sha256 = options.sha256 ?? webCryptoSha256;

  async function request(path: string, signal: AbortSignal | undefined, cache: RequestCache): Promise<Response> {
    let response: Response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, { signal, cache });
    } catch (error) {
      if (isAbort(error) || signal?.aborted) {
        throw new AnatomyLoadError('aborted', 'request cancelled');
      }
      throw new AnatomyLoadError('network', 'cannot reach neuro-engine; is it running on 127.0.0.1:8000?');
    }
    if (!response.ok) {
      let detail = '';
      try {
        const body: unknown = await response.json();
        const error = (body as { error?: { code?: unknown; message?: unknown } }).error;
        detail = typeof error?.message === 'string' ? `: ${error.message}` : '';
      } catch {
        // Non-JSON error bodies carry no extra detail.
      }
      throw new AnatomyLoadError('http', `neuro-engine returned HTTP ${response.status}${detail}`);
    }
    return response;
  }

  async function readText(path: string, signal: AbortSignal | undefined): Promise<string> {
    const response = await request(path, signal, 'no-cache');
    try {
      return await response.text();
    } catch {
      throw new AnatomyLoadError(signal?.aborted ? 'aborted' : 'network', 'response interrupted');
    }
  }

  async function readBuffer(asset: AnatomyAsset, ref: BufferRef, signal: AbortSignal | undefined): Promise<ArrayBuffer> {
    const path = `/assets/${encodeURIComponent(asset.assetId)}/files/${encodeURIComponent(ref.file)}`;
    // Buffers are immutable per asset ID, so the HTTP cache may serve them.
    const response = await request(path, signal, 'default');
    let data: ArrayBuffer;
    try {
      data = await response.arrayBuffer();
    } catch {
      throw new AnatomyLoadError(signal?.aborted ? 'aborted' : 'network', `${ref.file}: download interrupted`);
    }
    if (data.byteLength !== ref.byteLength) {
      throw new AnatomyLoadError('integrity', `${ref.file}: ${data.byteLength} bytes, manifest says ${ref.byteLength}`);
    }
    if ((await sha256(data)) !== ref.sha256) {
      throw new AnatomyLoadError('integrity', `${ref.file}: SHA-256 does not match the manifest`);
    }
    return data;
  }

  function requireLittleEndian(): void {
    if (!LITTLE_ENDIAN) {
      throw new AnatomyLoadError('integrity', 'asset buffers are little-endian; this platform is not');
    }
  }

  return {
    async fetchCatalog(signal) {
      const result = parseAnatomyCatalog(await readText('/catalog', signal));
      if (!result.ok) {
        throw new AnatomyLoadError('contract', `catalog rejected (${result.error.kind}): ${result.error.detail}`);
      }
      return result.document;
    },

    async fetchAsset(assetId, signal) {
      const result = parseAnatomyAsset(await readText(`/assets/${encodeURIComponent(assetId)}/manifest.json`, signal));
      if (!result.ok) {
        throw new AnatomyLoadError('contract', `asset manifest rejected (${result.error.kind}): ${result.error.detail}`);
      }
      if (result.document.assetId !== assetId) {
        throw new AnatomyLoadError('contract', `manifest describes ${result.document.assetId}, not ${assetId}`);
      }
      return result.document;
    },

    async loadSurfaces(asset, surface, signal) {
      requireLittleEndian();
      const meshes = asset.surfaces.filter((s) => s.surface === surface);
      if (meshes.length === 0) {
        throw new AnatomyLoadError('contract', `asset ${asset.assetId} has no ${surface} surface`);
      }
      return Promise.all(
        meshes.map(async (mesh) => {
          const [positionData, indexData] = await Promise.all([
            readBuffer(asset, mesh.positions, signal),
            readBuffer(asset, mesh.indices, signal),
          ]);
          const positions = new Float32Array(positionData);
          const indices = new Uint32Array(indexData);
          const issue = surfaceGeometryIssue(mesh, positions, indices);
          if (issue) {
            throw new AnatomyLoadError('integrity', `${mesh.hemisphere}.${mesh.surface}: ${issue}`);
          }
          return { hemisphere: mesh.hemisphere, surface: mesh.surface, positions, indices, boundsMm: mesh.boundsMm };
        }),
      );
    },

    async loadParcellations(asset, atlas, signal) {
      requireLittleEndian();
      const parcellations = asset.parcellations.filter((p) => p.atlas === atlas);
      if (parcellations.length === 0) {
        throw new AnatomyLoadError('contract', `asset ${asset.assetId} has no ${atlas} atlas`);
      }
      return Promise.all(
        parcellations.map(async (parcellation) => {
          const vertexLabels = new Int32Array(await readBuffer(asset, parcellation.vertexLabels, signal));
          const issue = vertexLabelsIssue(parcellation, vertexLabels);
          if (issue) {
            throw new AnatomyLoadError('integrity', `${parcellation.hemisphere}.${atlas}: ${issue}`);
          }
          return {
            atlas,
            hemisphere: parcellation.hemisphere,
            description: parcellation.description,
            labels: parcellation.labels,
            vertexLabels,
          };
        }),
      );
    },
  };
}
