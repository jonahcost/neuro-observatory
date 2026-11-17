import type { SurfaceKind } from '@neuro-observatory/protocol';
import type { RenderPresetId } from './renderPresets';

export const DISPLAY_MODES = ['pial', 'white', 'inflated', 'holographic', 'grid'] as const;
export type DisplayModeId = (typeof DISPLAY_MODES)[number];

export const OPAQUE_MODES = ['pial', 'white', 'inflated'] as const satisfies readonly DisplayModeId[];
export const WIRE_MODES = ['holographic', 'grid'] as const satisfies readonly DisplayModeId[];

export const MODE_LABELS: Record<DisplayModeId, string> = {
  pial: 'Pial',
  white: 'White matter boundary',
  inflated: 'Inflated',
  holographic: 'Holographic',
  grid: 'Grid',
};

export interface DisplaySelection {
  surfaceKind: SurfaceKind;
  preset: RenderPresetId;
}

/** The five picker modes. Wireframes are the pial presets from ADR-0014. */
export function displayModeFor(mode: DisplayModeId): DisplaySelection {
  switch (mode) {
    case 'pial':
      return { surfaceKind: 'pial', preset: 'solid' };
    case 'white':
      return { surfaceKind: 'white', preset: 'solid' };
    case 'inflated':
      return { surfaceKind: 'inflated', preset: 'solid' };
    case 'holographic':
      return { surfaceKind: 'pial', preset: 'holographic' };
    case 'grid':
      return { surfaceKind: 'pial', preset: 'grid' };
  }
}

/** Checked radio from the live surface and preset. A wire preset wins over the surface name. */
export function modeFrom(surfaceKind: SurfaceKind, preset: RenderPresetId): DisplayModeId {
  if (preset === 'holographic') {
    return 'holographic';
  }
  if (preset === 'grid') {
    return 'grid';
  }
  if (surfaceKind === 'white') {
    return 'white';
  }
  if (surfaceKind === 'inflated') {
    return 'inflated';
  }
  return 'pial';
}

export function modeAvailable(mode: DisplayModeId, availableKinds: readonly SurfaceKind[]): boolean {
  return availableKinds.includes(displayModeFor(mode).surfaceKind);
}
