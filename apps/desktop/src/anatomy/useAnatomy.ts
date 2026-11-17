import { useCallback, useEffect, useState } from 'react';
import type { AnatomyAsset, AnatomyCatalog, SurfaceKind } from '@neuro-observatory/protocol';
import { AnatomyLoadError, type AnatomyClient, type LoadedParcellation, type LoadedSurface } from './anatomyClient';

export type Load<T> =
  | { state: 'idle' }
  | { state: 'loading' }
  | { state: 'ready'; value: T }
  | { state: 'error'; error: AnatomyLoadError };

export interface AnatomyView {
  catalog: Load<AnatomyCatalog>;
  assetId: string | null;
  asset: Load<AnatomyAsset>;
  surfaceKind: SurfaceKind;
  surfaces: Load<LoadedSurface[]>;
  atlas: string | null;
  parcellations: Load<LoadedParcellation[]>;
  selectAsset(assetId: string): void;
  selectSurface(kind: SurfaceKind): void;
  selectAtlas(atlas: string | null): void;
  retry(): void;
}

const IDLE = { state: 'idle' } as const;
const LOADING = { state: 'loading' } as const;
const SURFACE_PREFERENCE: SurfaceKind[] = ['pial', 'white', 'inflated'];

function asLoadError(error: unknown): AnatomyLoadError {
  return error instanceof AnatomyLoadError ? error : new AnatomyLoadError('network', String(error));
}

/**
 * Runs `load` whenever `key` changes, cancelling the previous request.
 * Results of cancelled requests are discarded.
 */
function useCancellableLoad<T>(key: string | null, load: ((signal: AbortSignal) => Promise<T>) | null): Load<T> {
  const [result, setResult] = useState<{ key: string | null; load: Load<T> }>({ key: null, load: IDLE });
  useEffect(() => {
    if (key === null || load === null) {
      return;
    }
    const controller = new AbortController();
    setResult({ key, load: LOADING });
    load(controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) {
          setResult({ key, load: { state: 'ready', value } });
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ key, load: { state: 'error', error: asLoadError(error) } });
        }
      },
    );
    return () => controller.abort();
    // `load` is derived from `key`; the key alone decides when to reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (key === null || load === null) {
    return IDLE;
  }
  return result.key === key ? result.load : LOADING;
}

export function useAnatomy(client: AnatomyClient): AnatomyView {
  const [attempt, setAttempt] = useState(0);
  const [chosenAssetId, setChosenAssetId] = useState<string | null>(null);
  const [chosenSurface, setChosenSurface] = useState<SurfaceKind>('pial');
  const [chosenAtlas, setChosenAtlas] = useState<string | null>(null);

  const catalog = useCancellableLoad(`catalog#${attempt}`, (signal) => client.fetchCatalog(signal));
  const catalogValue = catalog.state === 'ready' ? catalog.value : null;
  const assetId =
    catalogValue === null
      ? null
      : catalogValue.assets.some((a) => a.assetId === chosenAssetId)
        ? chosenAssetId
        : catalogValue.defaultAssetId;

  const asset = useCancellableLoad(assetId === null ? null : `asset#${attempt}#${assetId}`, (signal) =>
    client.fetchAsset(assetId as string, signal),
  );
  const assetValue = asset.state === 'ready' ? asset.value : null;
  const availableKinds = SURFACE_PREFERENCE.filter((kind) => assetValue?.surfaces.some((s) => s.surface === kind));
  const surfaceKind = availableKinds.includes(chosenSurface) ? chosenSurface : (availableKinds[0] ?? chosenSurface);
  const atlas = assetValue?.parcellations.some((p) => p.atlas === chosenAtlas) ? chosenAtlas : null;

  const surfaces = useCancellableLoad(
    assetValue === null ? null : `surfaces#${attempt}#${assetValue.assetId}#${surfaceKind}`,
    assetValue === null ? null : (signal) => client.loadSurfaces(assetValue, surfaceKind, signal),
  );
  const parcellations = useCancellableLoad(
    assetValue === null || atlas === null ? null : `atlas#${attempt}#${assetValue.assetId}#${atlas}`,
    assetValue === null || atlas === null ? null : (signal) => client.loadParcellations(assetValue, atlas, signal),
  );

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return {
    catalog,
    assetId,
    asset,
    surfaceKind,
    surfaces,
    atlas,
    parcellations,
    selectAsset: setChosenAssetId,
    selectSurface: setChosenSurface,
    selectAtlas: setChosenAtlas,
    retry,
  };
}
