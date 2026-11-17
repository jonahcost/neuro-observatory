import { describe, expect, it } from 'vitest';
import { cameraPoseAction, frameRequested, nextCameraFar, orbitControlsKey } from './cameraSession';

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
});
