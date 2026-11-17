import { useEffect, useMemo, useRef, type ReactNode } from 'react';
import { Html } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  DoubleSide,
  FrontSide,
  GLSL3,
  ShaderMaterial,
  type Group,
  type MeshBasicMaterial,
} from 'three';
import type { ChannelActivity } from '../stream/channelActivity';
import type { LoadedParcellation, LoadedSurface } from './anatomyClient';
import { placeElectrodes, type PlacedElectrode } from './electrodeDisplay';
import { buildPathwayFrame } from './pathway';
import {
  ATLAS_WIRE_OPACITY,
  ELECTRODE_MARKER_RADIUS_MM,
  GLOW_SHELL_SCALE,
  GRID_LINE_OPACITY,
  GRID_RIM,
  HISTORICAL_SPHERE,
  HOLOGRAPHIC_ATLAS_LINE_OPACITY,
  HOLOGRAPHIC_ATLAS_RIM,
  HOLOGRAPHIC_GLOW,
  HOLOGRAPHIC_INNER_COLOR,
  HOLOGRAPHIC_INNER_OPACITY,
  HOLOGRAPHIC_LINE_COLOR,
  HOLOGRAPHIC_LINE_OPACITY,
  HOLOGRAPHIC_RIM,
  INNER_SHELL_SCALE,
  INTERIOR_MARKER_COLOR,
  INTERIOR_MARKER_RADIUS_MM,
  cellSizeMm,
  isWirePreset,
  type FresnelParams,
  type RenderPresetId,
  type WirePresetId,
} from './renderPresets';
import { RAS_TO_SCENE_ROTATION, SURFACE_RGB, displayBoundsMm, displayOffsetsMm, parcellationColors, type Vec3 } from './sceneGeometry';
import { simplifyLineMesh } from './displayLineMesh';

const FRESNEL_VERT = `
out vec3 vNormal;
out vec3 vView;
void main() {
  vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
  vView = normalize(-viewPosition.xyz);
  vNormal = normalize(normalMatrix * normal);
  gl_Position = projectionMatrix * viewPosition;
}
`;

const FRESNEL_FRAG = `
in vec3 vNormal;
in vec3 vView;
uniform vec3 uColor;
uniform float uPower;
uniform float uFacing;
uniform float uRim;
out vec4 fragColor;
void main() {
  float fresnel = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), uPower);
  fragColor = vec4(uColor, mix(uFacing, uRim, fresnel));
}
`;

function useLineGeometry(surface: LoadedSurface, cellMm: number, vertexColors?: Float32Array): BufferGeometry {
  const geometry = useMemo(() => {
    const simplified = simplifyLineMesh(surface.positions, surface.indices, cellMm, vertexColors);
    const next = new BufferGeometry();
    next.setAttribute('position', new BufferAttribute(simplified.positions, 3));
    next.setIndex(new BufferAttribute(simplified.indices, 1));
    if (simplified.colors !== undefined) {
      next.setAttribute('color', new BufferAttribute(simplified.colors, 3));
    }
    next.computeVertexNormals();
    return next;
  }, [surface, cellMm, vertexColors]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return geometry;
}

function useFullGeometry(surface: LoadedSurface, parcellation: LoadedParcellation | undefined): BufferGeometry {
  const geometry = useMemo(() => {
    const next = new BufferGeometry();
    next.setAttribute('position', new BufferAttribute(surface.positions, 3));
    next.setIndex(new BufferAttribute(surface.indices, 1));
    if (parcellation !== undefined && parcellation.vertexLabels.length === surface.positions.length / 3) {
      next.setAttribute('color', new BufferAttribute(parcellationColors(parcellation), 3));
    }
    next.computeVertexNormals();
    return next;
  }, [surface, parcellation]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return geometry;
}

function ScaleAbout({ centre, scale, children }: { centre: Vec3; scale: number; children: ReactNode }) {
  return (
    <group position={centre}>
      <group scale={scale}>
        <group position={[-centre[0], -centre[1], -centre[2]]}>{children}</group>
      </group>
    </group>
  );
}

function WireLines({
  geometry,
  offsetMm,
  color,
  opacity,
  additive,
  flat = false,
  emissive,
}: {
  geometry: BufferGeometry;
  offsetMm: number;
  color: string;
  opacity: number;
  additive: boolean;
  /** Unlit lines without additive blending, so a coloured surface underneath stays visible. */
  flat?: boolean;
  emissive?: string;
}) {
  return (
    <mesh geometry={geometry} position={[offsetMm, 0, 0]} renderOrder={2}>
      {additive || flat ? (
        <meshBasicMaterial
          color={geometry.getAttribute('color') === undefined ? color : '#ffffff'}
          vertexColors={geometry.getAttribute('color') !== undefined}
          wireframe
          transparent
          opacity={opacity}
          depthWrite={false}
          blending={additive ? AdditiveBlending : undefined}
          side={DoubleSide}
          toneMapped={false}
        />
      ) : (
        <meshStandardMaterial
          color={color}
          emissive={emissive}
          emissiveIntensity={HISTORICAL_SPHERE.emissiveIntensity}
          wireframe
          transparent
          opacity={opacity}
          depthWrite={false}
          side={DoubleSide}
        />
      )}
    </mesh>
  );
}

function FresnelShell({
  geometry,
  offsetMm,
  centre,
  scale,
  params,
}: {
  geometry: BufferGeometry;
  offsetMm: number;
  centre: Vec3;
  scale: number;
  params: FresnelParams;
}) {
  const material = useMemo(
    () =>
      new ShaderMaterial({
        glslVersion: GLSL3,
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        side: FrontSide,
        toneMapped: false,
        uniforms: {
          uColor: { value: new Color(params.color) },
          uPower: { value: params.power },
          uFacing: { value: params.facingOpacity },
          uRim: { value: params.rimOpacity },
        },
        vertexShader: FRESNEL_VERT,
        fragmentShader: FRESNEL_FRAG,
      }),
    [params],
  );
  useEffect(() => () => material.dispose(), [material]);
  return (
    <ScaleAbout centre={centre} scale={scale}>
      <mesh geometry={geometry} material={material} position={[offsetMm, 0, 0]} renderOrder={2} />
    </ScaleAbout>
  );
}

function SolidHemisphere({
  surface,
  offsetMm,
  parcellation,
}: {
  surface: LoadedSurface;
  offsetMm: number;
  parcellation: LoadedParcellation | undefined;
}) {
  const geometry = useFullGeometry(surface, parcellation);
  const colored = geometry.getAttribute('color') !== undefined;
  return (
    <mesh geometry={geometry} position={[offsetMm, 0, 0]} name={`${surface.hemisphere}.${surface.surface}`}>
      <meshStandardMaterial
        key={colored ? 'atlas' : 'plain'}
        vertexColors={colored}
        color={colored ? '#ffffff' : `rgb(${SURFACE_RGB.map((channel) => Math.round(channel * 255)).join(',')})`}
        roughness={0.85}
        metalness={0}
      />
    </mesh>
  );
}

/** Anatomical vertex colours on the scientific mesh, behind the display lines. */
function AtlasWash({ geometry, offsetMm }: { geometry: BufferGeometry; offsetMm: number }) {
  if (geometry.getAttribute('color') === undefined) {
    return null;
  }
  return (
    <mesh geometry={geometry} position={[offsetMm, 0, 0]} renderOrder={1}>
      <meshStandardMaterial
        vertexColors
        color="#ffffff"
        transparent
        opacity={ATLAS_WIRE_OPACITY}
        depthWrite={false}
        roughness={0.85}
        metalness={0}
        side={FrontSide}
      />
    </mesh>
  );
}

function OuterHemisphere({
  surface,
  offsetMm,
  preset,
  centre,
  fallbackInner,
  parcellation,
}: {
  surface: LoadedSurface;
  offsetMm: number;
  preset: WirePresetId;
  centre: Vec3;
  fallbackInner: boolean;
  parcellation: LoadedParcellation | undefined;
}) {
  const holographic = preset === 'holographic';
  const vertexColors = useMemo(
    () =>
      holographic && parcellation !== undefined && parcellation.vertexLabels.length === surface.positions.length / 3
        ? parcellationColors(parcellation)
        : undefined,
    [holographic, parcellation, surface],
  );
  const lines = useLineGeometry(surface, cellSizeMm(preset), vertexColors);
  const full = useFullGeometry(surface, parcellation);
  const colored = full.getAttribute('color') !== undefined;
  const showAdditiveShell = holographic && !colored;
  return (
    <>
      <AtlasWash geometry={full} offsetMm={offsetMm} />
      <WireLines
        geometry={lines}
        offsetMm={offsetMm}
        color={holographic ? HOLOGRAPHIC_LINE_COLOR : HISTORICAL_SPHERE.color}
        opacity={holographic ? (colored ? HOLOGRAPHIC_ATLAS_LINE_OPACITY : HOLOGRAPHIC_LINE_OPACITY) : GRID_LINE_OPACITY}
        additive={showAdditiveShell}
        flat={holographic && colored}
        emissive={holographic ? undefined : HISTORICAL_SPHERE.emissive}
      />
      {showAdditiveShell && fallbackInner ? (
        <ScaleAbout centre={centre} scale={INNER_SHELL_SCALE}>
          <WireLines
            geometry={lines}
            offsetMm={offsetMm}
            color={HOLOGRAPHIC_INNER_COLOR}
            opacity={HOLOGRAPHIC_INNER_OPACITY}
            additive
          />
        </ScaleAbout>
      ) : null}
      <FresnelShell
        geometry={full}
        offsetMm={offsetMm}
        centre={centre}
        scale={1}
        params={holographic ? (colored ? HOLOGRAPHIC_ATLAS_RIM : HOLOGRAPHIC_RIM) : GRID_RIM}
      />
      {showAdditiveShell ? (
        <FresnelShell geometry={full} offsetMm={offsetMm} centre={centre} scale={GLOW_SHELL_SCALE} params={HOLOGRAPHIC_GLOW} />
      ) : null}
    </>
  );
}

function InnerHemisphere({ surface, offsetMm }: { surface: LoadedSurface; offsetMm: number }) {
  const lines = useLineGeometry(surface, cellSizeMm('holographic'));
  return (
    <WireLines
      geometry={lines}
      offsetMm={offsetMm}
      color={HOLOGRAPHIC_INNER_COLOR}
      opacity={HOLOGRAPHIC_INNER_OPACITY}
      additive
    />
  );
}

/** Bright probe at the display bounds centre. Not anatomy. */
export function InteriorMarker({ position }: { position: Vec3 }) {
  return (
    <mesh position={position} renderOrder={4} name="interior-test-marker">
      <sphereGeometry args={[INTERIOR_MARKER_RADIUS_MM, 16, 12]} />
      <meshBasicMaterial color={INTERIOR_MARKER_COLOR} toneMapped={false} />
    </mesh>
  );
}

export function ElectrodeMarkers({
  electrodes,
  activity,
  visible,
}: {
  electrodes: readonly PlacedElectrode[];
  activity: ChannelActivity;
  visible: boolean;
}) {
  const materials = useRef(new Map<string, MeshBasicMaterial>());
  const labelNodes = useRef(new Map<string, HTMLSpanElement>());
  useFrame(() => {
    const display = activity.sampleDisplay(performance.now());
    for (const electrode of electrodes) {
      const intensity = display.byLabel.get(electrode.label)?.intensity ?? 0;
      const material = materials.current.get(electrode.label);
      if (material) {
        material.opacity = 0.18 + 0.82 * intensity;
      }
      const label = labelNodes.current.get(electrode.label);
      if (label) {
        label.style.opacity = String(0.45 + 0.55 * intensity);
      }
    }
  });
  if (!visible) {
    return null;
  }
  return (
    <>
      {electrodes.map((electrode) => (
        <group key={electrode.label} position={electrode.positionRasMm}>
          <mesh
            renderOrder={3}
            ref={(mesh) => {
              if (mesh === null) {
                materials.current.delete(electrode.label);
                return;
              }
              const material = mesh.material;
              if (!Array.isArray(material)) {
                materials.current.set(electrode.label, material as MeshBasicMaterial);
              }
            }}
          >
            <sphereGeometry args={[ELECTRODE_MARKER_RADIUS_MM, 12, 8]} />
            <meshBasicMaterial color="#9af7ff" transparent opacity={0.18} depthWrite={false} toneMapped={false} />
          </mesh>
          <Html position={[0, 3.4, 0]} center zIndexRange={[2, 0]} style={{ pointerEvents: 'none' }}>
            <span
              ref={(node) => {
                if (node === null) {
                  labelNodes.current.delete(electrode.label);
                  return;
                }
                labelNodes.current.set(electrode.label, node);
              }}
              style={{ color: '#d7f7ff', fontSize: '11px', whiteSpace: 'nowrap' }}
            >
              {electrode.label}
            </span>
          </Html>
        </group>
      ))}
    </>
  );
}

/** Empty slot. A later slice reads `userData.pathwayFrame` and draws pulses here. */
export function PathwayLayer({
  activity,
  electrodes,
  visible,
}: {
  activity: ChannelActivity;
  electrodes: readonly PlacedElectrode[];
  visible: boolean;
}) {
  const group = useRef<Group>(null);
  useFrame(() => {
    const display = activity.sampleDisplay(performance.now());
    const intensities = new Map<string, number>();
    for (const [label, value] of display.byLabel) {
      intensities.set(label, value.intensity);
    }
    if (group.current) {
      group.current.userData['pathwayFrame'] = buildPathwayFrame(
        performance.now(),
        display.health !== 'live',
        electrodes,
        intensities,
      );
    }
  });
  return <group ref={group} name="pathway-layer" visible={visible} />;
}

export function BrainShell({
  surfaces,
  preset,
  showMarker,
  showPathway,
  activity,
  channelLabels,
  innerSurfaces,
  parcellations,
}: {
  surfaces: readonly LoadedSurface[];
  preset: RenderPresetId;
  showMarker: boolean;
  showPathway: boolean;
  activity: ChannelActivity;
  channelLabels: readonly string[];
  innerSurfaces: readonly LoadedSurface[] | null;
  parcellations: readonly LoadedParcellation[] | null;
}) {
  const kind = surfaces[0]?.surface ?? 'pial';
  const offsets = useMemo(() => displayOffsetsMm(surfaces, kind), [surfaces, kind]);
  const centre = useMemo(() => {
    const bounds = displayBoundsMm(surfaces, offsets);
    if (bounds === null) {
      return null;
    }
    return [
      (bounds.min[0] + bounds.max[0]) / 2,
      (bounds.min[1] + bounds.max[1]) / 2,
      (bounds.min[2] + bounds.max[2]) / 2,
    ] as Vec3;
  }, [surfaces, offsets]);
  const electrodes = useMemo(() => {
    if (centre === null || kind === 'inflated') {
      return [];
    }
    return placeElectrodes(
      surfaces.map((surface) => ({
        hemisphere: surface.hemisphere,
        positions: surface.positions,
        offsetMm: offsets[surface.hemisphere],
      })),
      channelLabels,
    ).placed;
  }, [surfaces, offsets, centre, kind, channelLabels]);

  if (centre === null) {
    return null;
  }
  const wire = isWirePreset(preset);
  const useWhiteInner = preset === 'holographic' && innerSurfaces !== null && innerSurfaces.length > 0;
  const innerOffsets = useWhiteInner ? displayOffsetsMm(innerSurfaces, 'white') : null;
  const byHemisphere = new Map(parcellations?.map((parcellation) => [parcellation.hemisphere, parcellation]) ?? []);
  return (
    <group rotation={RAS_TO_SCENE_ROTATION}>
      {showMarker ? <InteriorMarker position={centre} /> : null}
      <ElectrodeMarkers electrodes={electrodes} activity={activity} visible={kind !== 'inflated'} />
      <PathwayLayer activity={activity} electrodes={electrodes} visible={showPathway} />
      {wire
        ? surfaces.map((surface) => (
            <OuterHemisphere
              key={`${surface.hemisphere}.${surface.surface}`}
              surface={surface}
              offsetMm={offsets[surface.hemisphere]}
              preset={preset}
              centre={centre}
              fallbackInner={preset === 'holographic' && !useWhiteInner}
              parcellation={byHemisphere.get(surface.hemisphere)}
            />
          ))
        : surfaces.map((surface) => (
            <SolidHemisphere
              key={`${surface.hemisphere}.${surface.surface}`}
              surface={surface}
              offsetMm={offsets[surface.hemisphere]}
              parcellation={byHemisphere.get(surface.hemisphere)}
            />
          ))}
      {useWhiteInner && innerOffsets
        ? innerSurfaces.map((surface) => (
            <InnerHemisphere
              key={`inner.${surface.hemisphere}.${surface.surface}`}
              surface={surface}
              offsetMm={innerOffsets[surface.hemisphere]}
            />
          ))
        : null}
    </group>
  );
}
