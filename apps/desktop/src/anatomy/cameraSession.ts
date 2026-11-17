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

export type CameraVec3 = readonly [number, number, number];

export interface SurfaceFraming {
  position: CameraVec3;
  target: CameraVec3;
  far: number;
}

export type CameraCommand =
  | { kind: 'frame'; position: CameraVec3; target: CameraVec3; far: number }
  | { kind: 'raise-far'; far: number };

/**
 * A new asset or Reset view applies the framing of the surface on screen:
 * position, orbit target, and far together. A display change only raises far.
 */
export function cameraCommand(args: {
  previousAssetId: string | null;
  assetId: string;
  resetNonce: number;
  seenResetNonce: number;
  currentFar: number;
  framing: SurfaceFraming;
}): CameraCommand {
  const resetting = frameRequested(false, args.resetNonce, args.seenResetNonce);
  const action = cameraPoseAction(args.previousAssetId, args.assetId);
  if (action === 'frame' || resetting) {
    return {
      kind: 'frame',
      position: args.framing.position,
      target: args.framing.target,
      far: args.framing.far,
    };
  }
  return { kind: 'raise-far', far: nextCameraFar(args.currentFar, args.framing.far) };
}

/** Reset view frames again even though the asset id did not change. Nonce 0 is the initial mount. */
export function frameRequested(assetChanged: boolean, resetNonce: number, seenNonce: number): boolean {
  return assetChanged || (resetNonce !== 0 && resetNonce !== seenNonce);
}
