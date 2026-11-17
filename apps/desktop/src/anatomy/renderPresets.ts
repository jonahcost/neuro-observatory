/**
 * Display constants. Solid is the original opaque cortical surface.
 * Holographic and Grid are additional display presets.
 * The historical sphere is the pre-anatomy placeholder:
 * sphereGeometry(1.5, 48, 32), meshStandardMaterial #49a4ff,
 * emissive #174f85, emissiveIntensity 0.3, WebGL line width 1.
 * On an ~87 mm bounding radius those chords are about 11 mm and 8.5 mm.
 * Grid uses a 16 mm cell so the gaps are larger than that sphere.
 */

export const RENDER_PRESETS = ['solid', 'holographic', 'grid'] as const;
export type RenderPresetId = (typeof RENDER_PRESETS)[number];
export type WirePresetId = Exclude<RenderPresetId, 'solid'>;

export function isWirePreset(preset: RenderPresetId): preset is WirePresetId {
  return preset !== 'solid';
}

export function presetLabel(preset: RenderPresetId): string {
  if (preset === 'solid') {
    return 'Solid';
  }
  return preset === 'holographic' ? 'Holographic' : 'Grid';
}

export const HOLOGRAPHIC_CELL_MM = 3.5;
export const GRID_CELL_MM = 16;
export const INNER_SHELL_SCALE = 0.94;
export const GLOW_SHELL_SCALE = 1.02;

export const HISTORICAL_SPHERE = {
  color: '#49a4ff',
  emissive: '#174f85',
  emissiveIntensity: 0.3,
  widthSegments: 48,
  heightSegments: 32,
} as const;

export const GRID_LINE_OPACITY = 0.9;
/** Full-resolution atlas wash behind a wireframe. Labels stay on their vertices. */
export const ATLAS_WIRE_OPACITY = 0.78;
/** Non-additive outline used when an atlas is showing, so the labels stay readable. */
export const HOLOGRAPHIC_ATLAS_LINE_OPACITY = 0.42;

export const HOLOGRAPHIC_LINE_COLOR = '#3cf0ff';
export const HOLOGRAPHIC_LINE_OPACITY = 0.18;
export const HOLOGRAPHIC_INNER_COLOR = '#1ec8e0';
export const HOLOGRAPHIC_INNER_OPACITY = 0.08;

export interface FresnelParams {
  color: string;
  power: number;
  facingOpacity: number;
  rimOpacity: number;
}

/** Brighter grazing rim, low facing opacity, so the interior stays visible. */
export const HOLOGRAPHIC_RIM: FresnelParams = {
  color: '#d8fbff',
  power: 2.8,
  facingOpacity: 0.012,
  rimOpacity: 0.7,
};

/** Rim only, while an atlas wash is showing. A facing veil would hide the labels. */
export const HOLOGRAPHIC_ATLAS_RIM: FresnelParams = {
  color: '#d8fbff',
  power: 2.8,
  facingOpacity: 0,
  rimOpacity: 0.28,
};

/** Restrained second shell. Not a bloom pass. */
export const HOLOGRAPHIC_GLOW: FresnelParams = {
  color: '#67e8ff',
  power: 2,
  facingOpacity: 0.015,
  rimOpacity: 0.16,
};

/** Faint outline so the sparse grid still reads as a brain. */
export const GRID_RIM: FresnelParams = {
  color: '#49a4ff',
  power: 2.6,
  facingOpacity: 0.02,
  rimOpacity: 0.2,
};

export const INTERIOR_MARKER_COLOR = '#fff4c2';
/** 8 mm: a 3 mm probe disappeared inside the additive shell at the default framing. */
export const INTERIOR_MARKER_RADIUS_MM = 8;
export const ELECTRODE_CLEARANCE_MM = 12;
export const ELECTRODE_MARKER_RADIUS_MM = 2.2;

export function cellSizeMm(preset: WirePresetId): number {
  return preset === 'grid' ? GRID_CELL_MM : HOLOGRAPHIC_CELL_MM;
}
