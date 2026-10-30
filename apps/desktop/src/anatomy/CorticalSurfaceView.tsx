import { useEffect, useMemo } from 'react';
import { BufferAttribute, BufferGeometry } from 'three';
import type { Hemisphere, SurfaceKind } from '@neuro-observatory/protocol';
import type { LoadedParcellation, LoadedSurface } from './anatomyClient';
import { RAS_TO_SCENE_ROTATION, SURFACE_RGB, displayOffsetsMm, parcellationColors } from './sceneGeometry';

function HemisphereMesh({
  surface,
  offsetMm,
  parcellation,
}: {
  surface: LoadedSurface;
  offsetMm: number;
  parcellation: LoadedParcellation | undefined;
}) {
  const colored = parcellation !== undefined && parcellation.vertexLabels.length === surface.positions.length / 3;
  const geometry = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new BufferAttribute(surface.positions, 3));
    g.setIndex(new BufferAttribute(surface.indices, 1));
    if (colored && parcellation) {
      g.setAttribute('color', new BufferAttribute(parcellationColors(parcellation), 3));
    }
    g.computeVertexNormals();
    g.computeBoundingSphere();
    return g;
  }, [surface, parcellation, colored]);

  useEffect(() => () => geometry.dispose(), [geometry]);

  return (
    <mesh geometry={geometry} position={[offsetMm, 0, 0]} name={`${surface.hemisphere}.${surface.surface}`}>
      <meshStandardMaterial
        key={colored ? 'atlas' : 'plain'}
        vertexColors={colored}
        color={colored ? '#ffffff' : `rgb(${SURFACE_RGB.map((c) => Math.round(c * 255)).join(',')})`}
        roughness={0.85}
        metalness={0}
      />
    </mesh>
  );
}

/** Both hemispheres in surface RAS (mm), rotated into the y-up scene. */
export function CorticalSurfaceView({
  surfaces,
  kind,
  parcellations,
}: {
  surfaces: readonly LoadedSurface[];
  kind: SurfaceKind;
  parcellations: readonly LoadedParcellation[] | null;
}) {
  const offsets = displayOffsetsMm(surfaces, kind);
  const byHemisphere = new Map<Hemisphere, LoadedParcellation>(parcellations?.map((p) => [p.hemisphere, p]) ?? []);
  return (
    <group rotation={RAS_TO_SCENE_ROTATION}>
      {surfaces.map((surface) => (
        <HemisphereMesh
          key={`${surface.hemisphere}.${surface.surface}`}
          surface={surface}
          offsetMm={offsets[surface.hemisphere]}
          parcellation={byHemisphere.get(surface.hemisphere)}
        />
      ))}
    </group>
  );
}
