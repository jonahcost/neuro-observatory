import { describe, expect, it } from 'vitest';
import type { LoadedParcellation, LoadedSurface } from './anatomyClient';
import { OVERLAY_KIND_LABELS, overlayIssue, type CorticalOverlay } from './overlay';
import {
  INFLATED_DISPLAY_GAP_MM,
  UNLABELLED_RGB,
  cameraFraming,
  displayBoundsMm,
  displayOffsetsMm,
  parcellationColors,
  rasToScene,
} from './sceneGeometry';

function surface(hemisphere: 'lh' | 'rh', min: [number, number, number], max: [number, number, number]): LoadedSurface {
  return { hemisphere, surface: 'inflated', positions: new Float32Array(12), indices: new Uint32Array(12), boundsMm: { min, max } };
}

describe('scene geometry', () => {
  it('maps RAS (z up) to the y-up scene without scaling', () => {
    expect(rasToScene([10, 20, 30])).toEqual([10, 30, -20]);
  });

  it('separates overlapping inflated hemispheres for display only', () => {
    const surfaces = [surface('lh', [-41.5, -108, -73], [41.5, 108, 73]), surface('rh', [-40.9, -107.7, -73.3], [40.9, 107.7, 73.3])];
    const offsets = displayOffsetsMm(surfaces, 'inflated');
    expect(41.5 + offsets.lh).toBeCloseTo(-INFLATED_DISPLAY_GAP_MM / 2);
    expect(-40.9 + offsets.rh).toBeCloseTo(INFLATED_DISPLAY_GAP_MM / 2);
    expect(displayOffsetsMm(surfaces, 'pial')).toEqual({ lh: 0, rh: 0 });
    const bounds = displayBoundsMm(surfaces, offsets);
    expect(bounds?.max[0]).toBeCloseTo(INFLATED_DISPLAY_GAP_MM / 2 + 81.8);
  });

  it('frames the camera on the bounds centre', () => {
    const framing = cameraFraming({ min: [-70, -100, -40], max: [70, 70, 80] });
    expect(framing.target).toEqual(rasToScene([0, -15, 20]));
    const distance = Math.hypot(...framing.position.map((p, i) => p - (framing.target[i] as number)));
    expect(distance).toBeCloseTo(340);
    expect(framing.far).toBeGreaterThan(distance);
  });

  it('colours vertices from atlas labels and greys unlabelled ones', () => {
    const parcellation: LoadedParcellation = {
      atlas: 'aparc',
      hemisphere: 'lh',
      description: 'atlas',
      labels: [{ index: 1, name: 'precentral', rgba: [255, 0, 0, 255] }],
      vertexLabels: new Int32Array([1, -1]),
    };
    expect(Array.from(parcellationColors(parcellation))).toEqual([1, 0, 0, ...UNLABELLED_RGB.map((c) => Math.fround(c))]);
  });
});

describe('overlay contract', () => {
  const overlay: CorticalOverlay = {
    assetId: 'a',
    provenance: { kind: 'synthetic', generator: 'test', seed: 1 },
    quantity: 'test',
    unit: 'a.u.',
    timeUs: null,
    values: { lh: new Float32Array(4), rh: new Float32Array(4) },
  };

  it('binds overlays to one asset and its vertex counts', () => {
    expect(overlayIssue(overlay, 'a', { lh: 4, rh: 4 })).toBeNull();
    expect(overlayIssue(overlay, 'b', { lh: 4, rh: 4 })).toContain('belongs to asset a');
    expect(overlayIssue(overlay, 'a', { lh: 4, rh: 5 })).toContain('rh has 4 values for 5 vertices');
  });

  it('labels every overlay kind as non-measurement', () => {
    expect(OVERLAY_KIND_LABELS.synthetic).toContain('not brain activity');
    expect(OVERLAY_KIND_LABELS.estimate).toContain('not a direct measurement');
    expect(OVERLAY_KIND_LABELS['validated-estimate']).toContain('not a direct measurement');
  });
});
