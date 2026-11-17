import { describe, expect, it } from 'vitest';
import { cameraCommand, cameraPoseAction, frameRequested, nextCameraFar, orbitControlsKey } from './cameraSession';

describe('camera session', () => {
  it('frames a new asset and keeps the pose for the same asset', () => {
    expect(cameraPoseAction(null, 'fsaverage')).toBe('frame');
    expect(cameraPoseAction('fsaverage', 'fsaverage')).toBe('keep');
    expect(cameraPoseAction('fsaverage', 'ds000248')).toBe('frame');
    expect(cameraPoseAction('fsaverage', null)).toBe('keep');
  });

  it('keys orbit controls by asset only', () => {
    expect(orbitControlsKey('fsaverage-0001')).toBe('fsaverage-0001');
  });

  it('raises the far plane and does not shrink it', () => {
    expect(nextCameraFar(1000, 2500)).toBe(2500);
    expect(nextCameraFar(2500, 1000)).toBe(2500);
  });

  it('frames on reset without treating the initial nonce as a reset', () => {
    expect(frameRequested(false, 0, 0)).toBe(false);
    expect(frameRequested(false, 1, 0)).toBe(true);
    expect(frameRequested(false, 1, 1)).toBe(false);
    expect(frameRequested(true, 1, 1)).toBe(true);
  });

  it('reset and a new asset use the surface on screen, and a display change only raises far', () => {
    const pial = { position: [1, 2, 3] as const, target: [0, 0, 0] as const, far: 1000 };
    const inflated = { position: [4, 5, 6] as const, target: [7, 8, 9] as const, far: 4000 };
    expect(
      cameraCommand({
        previousAssetId: 'fsaverage',
        assetId: 'ds000248',
        resetNonce: 0,
        seenResetNonce: 0,
        currentFar: 1000,
        framing: inflated,
      }),
    ).toEqual({ kind: 'frame', ...inflated });
    expect(
      cameraCommand({
        previousAssetId: 'fsaverage',
        assetId: 'fsaverage',
        resetNonce: 1,
        seenResetNonce: 1,
        currentFar: 1000,
        framing: inflated,
      }),
    ).toEqual({ kind: 'raise-far', far: 4000 });
    expect(
      cameraCommand({
        previousAssetId: 'fsaverage',
        assetId: 'fsaverage',
        resetNonce: 2,
        seenResetNonce: 1,
        currentFar: 9000,
        framing: inflated,
      }),
    ).toEqual({ kind: 'frame', ...inflated });
    expect(
      cameraCommand({
        previousAssetId: 'fsaverage',
        assetId: 'fsaverage',
        resetNonce: 2,
        seenResetNonce: 2,
        currentFar: 9000,
        framing: pial,
      }),
    ).toEqual({ kind: 'raise-far', far: 9000 });
  });
});
