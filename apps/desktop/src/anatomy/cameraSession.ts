/**
 * Orbit lifetime for the brain viewport.
 * A new subject frames the camera. A display change on the same asset does not.
 */

export function orbitControlsKey(assetId: string): string {
  return assetId;
}

export function cameraPoseAction(previousAssetId: string | null, nextAssetId: string | null): 'frame' | 'keep' {
  if (nextAssetId === null || previousAssetId === nextAssetId) {
    return 'keep';
  }
  return 'frame';
}

/** Never shrink the far plane during a display change, so a larger surface is not clipped. */
export function nextCameraFar(currentFar: number, framedFar: number): number {
  return Math.max(currentFar, framedFar);
}

/** Reset view frames again even though the asset id did not change. Nonce 0 is the initial mount. */
export function frameRequested(assetChanged: boolean, resetNonce: number, seenNonce: number): boolean {
  return assetChanged || (resetNonce !== 0 && resetNonce !== seenNonce);
}
