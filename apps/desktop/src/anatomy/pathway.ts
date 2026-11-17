import type { Vec3 } from './sceneGeometry';

/**
 * Display input for a later pathway slice. This slice only builds the frame
 * and leaves an empty scene group named `pathway-layer`.
 *
 * A later slice may add an explicit list of `{ from, to }` label pairs
 * (not inferred connectivity). Pulses move along the segment in this same
 * surface-RAS frame. Pulse brightness is a function of the two endpoint
 * intensities already on this frame. Endpoint flashes fire when an
 * intensity crosses a threshold. That slice must not create a
 * `CorticalOverlay` or paint cortical vertices.
 */
export interface PathwayEndpoint {
  label: string;
  positionRasMm: Vec3;
  /** Interpolated display intensity, 0..1. Not a source estimate. */
  intensity: number;
}

export interface PathwayFrame {
  timeMs: number;
  stale: boolean;
  endpoints: readonly PathwayEndpoint[];
}

export function buildPathwayFrame(
  timeMs: number,
  stale: boolean,
  endpoints: readonly { label: string; positionRasMm: Vec3 }[],
  intensityByLabel: ReadonlyMap<string, number>,
): PathwayFrame {
  return {
    timeMs,
    stale,
    endpoints: endpoints.map((endpoint) => ({
      label: endpoint.label,
      positionRasMm: [...endpoint.positionRasMm] as Vec3,
      intensity: intensityByLabel.get(endpoint.label) ?? 0,
    })),
  };
}
