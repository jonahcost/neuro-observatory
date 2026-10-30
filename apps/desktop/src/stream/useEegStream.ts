import { useEffect, useSyncExternalStore } from 'react';
import type { EegStreamClient, EegStreamSnapshot } from './eegStreamClient';

/** Runs the client while mounted and returns throttled status snapshots. */
export function useEegStream(client: EegStreamClient): EegStreamSnapshot {
  useEffect(() => {
    client.start();
    return () => client.stop();
  }, [client]);
  return useSyncExternalStore(client.subscribe, client.getSnapshot);
}

export function engineUrlFromEnv(env: Record<string, unknown>): string | undefined {
  const value = env['VITE_NEURO_ENGINE_WS_URL'];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}
