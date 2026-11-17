import type { Hemisphere } from '@neuro-observatory/protocol';
import { ELECTRODE_CLEARANCE_MM } from './renderPresets';
import type { Vec3 } from './sceneGeometry';
import { templateDirection } from './template1020';

export interface ElectrodeSurface {
  hemisphere: Hemisphere;
  /** Surface RAS millimetres, x/y/z interleaved. Not modified. */
  positions: Float32Array;
  offsetMm: number;
}

export interface PlacedElectrode {
  label: string;
  positionRasMm: Vec3;
}

export interface ElectrodeLayout {
  placed: PlacedElectrode[];
  unmapped: string[];
  centreRasMm: Vec3;
  /** Distance from the centre to the farthest displayed vertex, plus clearance. */
  radiusMm: number;
}

/**
 * Template display positions outside the displayed folded surface.
 * Centre is the bounds centre after the hemisphere display offset.
 * Radius reaches the farthest vertex of those surfaces, then adds
 * ELECTRODE_CLEARANCE_MM. This is a scalp-side display offset, not a head model.
 * Callers hide the result on inflated surfaces, where the vertices have moved.
 */
export function placeElectrodes(surfaces: readonly ElectrodeSurface[], labels: readonly string[]): ElectrodeLayout {
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;
  let count = 0;
  for (const surface of surfaces) {
    const { positions, offsetMm } = surface;
    for (let i = 0; i < positions.length; i += 3) {
      const x = (positions[i] as number) + offsetMm;
      const y = positions[i + 1] as number;
      const z = positions[i + 2] as number;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (z < minZ) minZ = z;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      if (z > maxZ) maxZ = z;
      count += 1;
    }
  }
  const centre: Vec3 = count === 0 ? [0, 0, 0] : [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2];
  let farthest = 0;
  for (const surface of surfaces) {
    const { positions, offsetMm } = surface;
    for (let i = 0; i < positions.length; i += 3) {
      const dx = (positions[i] as number) + offsetMm - centre[0];
      const dy = (positions[i + 1] as number) - centre[1];
      const dz = (positions[i + 2] as number) - centre[2];
      const distance = Math.hypot(dx, dy, dz);
      if (distance > farthest) farthest = distance;
    }
  }
  const radiusMm = farthest + ELECTRODE_CLEARANCE_MM;
  const placed: PlacedElectrode[] = [];
  const unmapped: string[] = [];
  for (const label of labels) {
    const direction = templateDirection(label);
    if (direction === null) {
      unmapped.push(label);
      continue;
    }
    const length = Math.hypot(direction[0], direction[1], direction[2]);
    const scale = length === 0 ? 0 : radiusMm / length;
    placed.push({
      label,
      positionRasMm: [centre[0] + direction[0] * scale, centre[1] + direction[1] * scale, centre[2] + direction[2] * scale],
    });
  }
  return { placed, unmapped, centreRasMm: centre, radiusMm };
}
