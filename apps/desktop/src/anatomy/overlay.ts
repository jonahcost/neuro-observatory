import type { Hemisphere } from '@neuro-observatory/protocol';

/**
 * Integration boundary for future per-vertex values drawn on a cortical surface
 * (see docs/architecture/ANATOMY.md, "Overlay contract"). Nothing produces
 * overlays yet: the viewer shows anatomy only.
 *
 * - `synthetic`: generated test values; never derived from a person.
 * - `estimate`: a model-derived source estimate from measured EEG. It is an
 *   inverse-problem solution, not a direct measurement of cortical activity.
 * - `validated-estimate`: an estimate whose pipeline passed documented
 *   validation for this subject (coregistration, forward model, inverse).
 */
export type OverlayProvenance =
  | { kind: 'synthetic'; generator: string; seed: number }
  | { kind: 'estimate'; method: string; recordingId: string; pipelineVersion: string }
  | { kind: 'validated-estimate'; method: string; recordingId: string; pipelineVersion: string; validationId: string };

export interface CorticalOverlay {
  /** The anatomy asset whose vertices the values index; overlays never transfer between assets. */
  assetId: string;
  provenance: OverlayProvenance;
  quantity: string;
  unit: string;
  /** Sample time of the values on the engine timebase, microseconds; null for static maps. */
  timeUs: number | null;
  /** One value per vertex of each hemisphere (NaN = no value), in asset vertex order. */
  values: Record<Hemisphere, Float32Array>;
}

export const OVERLAY_KIND_LABELS: Record<OverlayProvenance['kind'], string> = {
  synthetic: 'Synthetic overlay — generated test values, not brain activity',
  estimate: 'Model-derived source estimate from scalp EEG — not a direct measurement',
  'validated-estimate': 'Validated model-derived source estimate — not a direct measurement',
};

/** Returns a problem description, or null when the overlay fits the loaded asset. */
export function overlayIssue(overlay: CorticalOverlay, assetId: string, vertexCounts: Record<Hemisphere, number>): string | null {
  if (overlay.assetId !== assetId) {
    return `overlay belongs to asset ${overlay.assetId}, not ${assetId}`;
  }
  for (const hemisphere of ['lh', 'rh'] as const) {
    if (overlay.values[hemisphere].length !== vertexCounts[hemisphere]) {
      return `${hemisphere} has ${overlay.values[hemisphere].length} values for ${vertexCounts[hemisphere]} vertices`;
    }
  }
  return null;
}
