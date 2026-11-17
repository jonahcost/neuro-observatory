import type { Vec3 } from './sceneGeometry';

/**
 * Unit-sphere 10-20 directions for the 16 synthetic labels.
 *
 * Transcribed from Kayser and Tenke, Clinical Neurophysiology 2006;117(2):348–368, Table A1.
 * That table is the spherical model of the international 10-20 percentage
 * arcs (Oostenveld and Praamstra 2001): +x through T8, +y through Fpz,
 * +z through Cz. Those axes match surface RAS (+x right, +y anterior,
 * +z superior). Jurcak, Tsuzuki, and Dan, NeuroImage 2007, is why this
 * stays a relative head-surface display model and not an MRI registration.
 *
 * Values are the published Cartesian coordinates on a radius-1 sphere.
 * They are not digitized positions for fsaverage or ds000248.
 */
export const TEMPLATE_1020_CITATION =
  'Kayser & Tenke 2006, Clin Neurophysiol 117:348–368, Table A1 (spherical 10-20; Oostenveld & Praamstra 2001). Relative head-surface layout, not a subject registration (Jurcak, Tsuzuki & Dan 2007).';

export const TEMPLATE_1020_UNIT: Readonly<Record<string, Vec3>> = {
  Fp1: [-0.30902, 0.95106, 0],
  Fp2: [0.30902, 0.95106, 0],
  F7: [-0.80902, 0.58779, 0],
  F3: [-0.54891, 0.67173, 0.49747],
  F4: [0.54891, 0.67173, 0.49747],
  F8: [0.80902, 0.58779, 0],
  T7: [-1, 0, 0],
  C3: [-0.70711, 0, 0.70711],
  Cz: [0, 0, 1],
  C4: [0.70711, 0, 0.70711],
  T8: [1, 0, 0],
  P3: [-0.54891, -0.67173, 0.49747],
  Pz: [0, -0.70711, 0.70711],
  P4: [0.54891, -0.67173, 0.49747],
  O1: [-0.30902, -0.95106, 0],
  O2: [0.30902, -0.95106, 0],
};

export const SYNTHETIC_CHANNEL_LABELS = [
  'Fp1',
  'Fp2',
  'F3',
  'F4',
  'F7',
  'F8',
  'C3',
  'C4',
  'Cz',
  'P3',
  'P4',
  'T7',
  'T8',
  'O1',
  'O2',
  'Pz',
] as const;

export function templateDirection(label: string): Vec3 | null {
  return TEMPLATE_1020_UNIT[label] ?? null;
}

export function unmappedTemplateLabels(labels: readonly string[]): string[] {
  return labels.filter((label) => templateDirection(label) === null);
}
