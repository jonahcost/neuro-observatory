import type { Hemisphere, SurfaceKind } from '@neuro-observatory/protocol';
import type { LoadedParcellation, LoadedSurface } from './anatomyClient';

export type Vec3 = [number, number, number];

/**
 * Scene axes from surface RAS: Three.js is y-up, RAS is z-up.
 * Applied as a rotation of the scene group (-90 degrees about x); vertex data is never modified.
 * Scene units are millimetres.
 */
export const RAS_TO_SCENE_ROTATION: Vec3 = [-Math.PI / 2, 0, 0];

export function rasToScene([x, y, z]: Vec3): Vec3 {
  return [x, z, -y];
}

/**
 * FreeSurfer inflates each hemisphere around its own centre, so the two inflated
 * surfaces overlap at x = 0. For display only, they are pulled apart along x so
 * their medial extremes sit `gapMm` apart. Other surfaces are shown in place.
 */
export const INFLATED_DISPLAY_GAP_MM = 8;

export function displayOffsetsMm(surfaces: readonly LoadedSurface[], kind: SurfaceKind): Record<Hemisphere, number> {
  const offsets: Record<Hemisphere, number> = { lh: 0, rh: 0 };
  if (kind !== 'inflated') {
    return offsets;
  }
  for (const surface of surfaces) {
    offsets[surface.hemisphere] =
      surface.hemisphere === 'lh'
        ? -INFLATED_DISPLAY_GAP_MM / 2 - surface.boundsMm.max[0]
        : INFLATED_DISPLAY_GAP_MM / 2 - surface.boundsMm.min[0];
  }
  return offsets;
}

/** Combined RAS bounds after display offsets, in mm. */
export function displayBoundsMm(
  surfaces: readonly LoadedSurface[],
  offsets: Record<Hemisphere, number>,
): { min: Vec3; max: Vec3 } | null {
  if (surfaces.length === 0) {
    return null;
  }
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const surface of surfaces) {
    const shift = offsets[surface.hemisphere];
    for (let axis = 0; axis < 3; axis += 1) {
      const delta = axis === 0 ? shift : 0;
      min[axis] = Math.min(min[axis] as number, (surface.boundsMm.min[axis] as number) + delta);
      max[axis] = Math.max(max[axis] as number, (surface.boundsMm.max[axis] as number) + delta);
    }
  }
  return { min, max };
}

/** Orbit target and a camera position that frames the bounds from the left-anterior-superior. */
export function cameraFraming(bounds: { min: Vec3; max: Vec3 }): { target: Vec3; position: Vec3; far: number } {
  const centreRas = bounds.min.map((lo, axis) => (lo + (bounds.max[axis] as number)) / 2) as Vec3;
  const size = Math.max(...bounds.max.map((hi, axis) => hi - (bounds.min[axis] as number)));
  const distance = size * 2;
  const directionRas: Vec3 = [-0.6, 0.45, 0.35];
  const norm = Math.hypot(...directionRas);
  const eyeRas = centreRas.map((c, axis) => c + ((directionRas[axis] as number) / norm) * distance) as Vec3;
  return { target: rasToScene(centreRas), position: rasToScene(eyeRas), far: distance * 10 };
}

export const SURFACE_RGB: Vec3 = [0.8, 0.76, 0.72];
export const UNLABELLED_RGB: Vec3 = [0.45, 0.45, 0.45];

function srgbToLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** Linear-RGB vertex colours from an atlas; unlabelled vertices are grey. */
export function parcellationColors(parcellation: LoadedParcellation): Float32Array {
  const lookup = new Map<number, Vec3>(
    parcellation.labels.map((label) => [
      label.index,
      [srgbToLinear(label.rgba[0]), srgbToLinear(label.rgba[1]), srgbToLinear(label.rgba[2])],
    ]),
  );
  const colors = new Float32Array(parcellation.vertexLabels.length * 3);
  for (let vertex = 0; vertex < parcellation.vertexLabels.length; vertex += 1) {
    const rgb = lookup.get(parcellation.vertexLabels[vertex] as number) ?? UNLABELLED_RGB;
    colors.set(rgb, vertex * 3);
  }
  return colors;
}
