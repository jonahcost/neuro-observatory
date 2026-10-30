import { memo, useEffect, useId, useMemo } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import type { AnatomyAsset, AnatomyKind, SurfaceKind } from '@neuro-observatory/protocol';
import { CorticalSurfaceView } from './CorticalSurfaceView';
import { INFLATED_DISPLAY_GAP_MM, cameraFraming, displayBoundsMm, displayOffsetsMm, type Vec3 } from './sceneGeometry';
import { useAnatomy, type AnatomyView, type Load } from './useAnatomy';
import type { AnatomyClient } from './anatomyClient';

export const ANATOMY_KIND_LABELS: Record<AnatomyKind, string> = {
  template: 'Template anatomy — an average brain (fsaverage), not any individual',
  'reference-subject': "Reference subject — a public research participant's anatomy, not yours",
  personal: 'Personal anatomy — reconstructed from an MRI you imported',
};

const SURFACE_LABELS: Record<SurfaceKind, string> = {
  pial: 'Pial (outer cortical surface)',
  white: 'White matter boundary',
  inflated: 'Inflated (display aid)',
};

function FrameCamera({ position, far }: { position: Vec3; far: number }) {
  const camera = useThree((state) => state.camera);
  useEffect(() => {
    camera.position.set(...position);
    camera.near = 1;
    camera.far = far;
    camera.updateProjectionMatrix();
  }, [camera, position, far]);
  return null;
}

function statusText(view: AnatomyView): string | null {
  const stages: [string, Load<unknown>][] = [
    ['anatomy catalog', view.catalog],
    ['asset manifest', view.asset],
    ['cortical surfaces', view.surfaces],
    ['atlas', view.parcellations],
  ];
  for (const [label, load] of stages) {
    if (load.state === 'loading') {
      return `Loading ${label}…`;
    }
  }
  return null;
}

function firstError(view: AnatomyView) {
  for (const load of [view.catalog, view.asset, view.surfaces, view.parcellations]) {
    if (load.state === 'error') {
      return load.error;
    }
  }
  return null;
}

function AcquisitionFacts({ asset }: { asset: AnatomyAsset }) {
  const { acquisition, subject } = asset;
  if (asset.anatomyKind === 'template') {
    return <>Population template; no single scan.</>;
  }
  const strength = acquisition.fieldStrengthTesla === null ? 'field strength unknown' : `${acquisition.fieldStrengthTesla} T`;
  return (
    <>
      {subject.subjectId}: {strength}
      {acquisition.sequence ? `, ${acquisition.sequence}` : ''}
      {acquisition.scanner ? `, ${acquisition.scanner}` : ''} (source: {acquisition.source})
    </>
  );
}

function AnatomyControls({ view }: { view: AnatomyView }) {
  const subjectId = useId();
  const surfaceId = useId();
  const atlasId = useId();
  const catalog = view.catalog.state === 'ready' ? view.catalog.value : null;
  const asset = view.asset.state === 'ready' ? view.asset.value : null;
  const kinds = (['pial', 'white', 'inflated'] as const).filter((k) => asset?.surfaces.some((s) => s.surface === k));
  const atlases = [...new Set(asset?.parcellations.map((p) => p.atlas) ?? [])];

  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'end' }}>
      <label htmlFor={subjectId}>
        Subject{' '}
        <select
          id={subjectId}
          value={view.assetId ?? ''}
          disabled={!catalog || catalog.assets.length === 0}
          onChange={(event) => view.selectAsset(event.target.value)}
        >
          {catalog?.assets.map((a) => (
            <option key={a.assetId} value={a.assetId}>
              {a.subject.displayName} [{a.anatomyKind}]
            </option>
          ))}
        </select>
      </label>
      <label htmlFor={surfaceId}>
        Surface{' '}
        <select
          id={surfaceId}
          value={view.surfaceKind}
          disabled={!asset}
          onChange={(event) => view.selectSurface(event.target.value as SurfaceKind)}
        >
          {kinds.map((k) => (
            <option key={k} value={k}>
              {SURFACE_LABELS[k]}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor={atlasId}>
        Anatomical atlas colouring{' '}
        <select
          id={atlasId}
          value={view.atlas ?? ''}
          disabled={!asset || atlases.length === 0}
          onChange={(event) => view.selectAtlas(event.target.value || null)}
        >
          <option value="">None</option>
          {atlases.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </label>
      <button type="button" onClick={view.retry} disabled={view.catalog.state === 'loading'}>
        Refresh subjects
      </button>
    </div>
  );
}

export const AnatomyViewer = memo(function AnatomyViewer({ client }: { client: AnatomyClient }) {
  const view = useAnatomy(client);
  const asset = view.asset.state === 'ready' ? view.asset.value : null;
  const surfaces = view.surfaces.state === 'ready' ? view.surfaces.value : null;
  const parcellations = view.parcellations.state === 'ready' ? view.parcellations.value : null;
  const framing = useMemo(() => {
    const bounds = surfaces ? displayBoundsMm(surfaces, displayOffsetsMm(surfaces, view.surfaceKind)) : null;
    return bounds ? cameraFraming(bounds) : null;
  }, [surfaces, view.surfaceKind]);
  const error = firstError(view);
  const loading = statusText(view);
  const empty = view.catalog.state === 'ready' && view.catalog.value.assets.length === 0;
  const atlasDescription = parcellations?.[0]?.description;

  return (
    <section aria-label="Cortical anatomy" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 8 }}>
      <AnatomyControls view={view} />

      <div style={{ height: '55vh', position: 'relative', background: '#05070f', borderRadius: 6 }}>
        {surfaces && framing && asset ? (
          <Canvas camera={{ fov: 35, near: 1, far: framing.far, position: framing.position }}>
            <FrameCamera position={framing.position} far={framing.far} />
            <hemisphereLight args={['#ffffff', '#30343f', 1.1]} />
            <directionalLight position={[300, 400, 300]} intensity={1.6} />
            <directionalLight position={[-300, -100, -300]} intensity={0.6} />
            <CorticalSurfaceView surfaces={surfaces} kind={view.surfaceKind} parcellations={parcellations} />
            <OrbitControls
              key={`${asset.assetId}#${view.surfaceKind}`}
              makeDefault
              target={framing.target}
              enablePan
              enableZoom
              enableRotate
            />
          </Canvas>
        ) : null}
        <div role="status" aria-live="polite" style={{ position: 'absolute', top: 12, left: 12 }}>
          {loading}
          {empty
            ? 'No anatomy prepared yet. Run: neuro-engine datasets fetch fsaverage --accept-license, then ' +
              'neuro-engine anatomy prepare fsaverage, and choose Refresh subjects'
            : null}
        </div>
        {error ? (
          <div role="alert" style={{ position: 'absolute', top: 12, left: 12, right: 12 }}>
            Anatomy unavailable ({error.kind}): {error.message}{' '}
            <button type="button" onClick={view.retry}>
              Retry
            </button>
          </div>
        ) : null}
      </div>

      {asset ? (
        <dl data-testid="anatomy-provenance" style={{ margin: 0 }}>
          <dt>Anatomy</dt>
          <dd data-testid="anatomy-kind">{ANATOMY_KIND_LABELS[asset.anatomyKind]}</dd>
          <dt>Source</dt>
          <dd>
            {asset.subject.datasetId} {asset.subject.datasetVersion} · <AcquisitionFacts asset={asset} />
          </dd>
          <dt>Geometry</dt>
          <dd>
            FreeSurfer surfaces in surface RAS, millimetres, full resolution
            {view.surfaceKind === 'inflated'
              ? `; inflated hemispheres separated by ${INFLATED_DISPLAY_GAP_MM} mm for display`
              : ''}
          </dd>
          <dt>Colour</dt>
          <dd>
            {atlasDescription
              ? `${atlasDescription} — anatomical labels, not activity`
              : 'Uniform surface colour'}
          </dd>
          <dt>Activity</dt>
          <dd data-testid="activity-overlay">
            No activity overlay. The EEG stream is not mapped onto this anatomy; no source estimate is shown.
          </dd>
          <dt>License</dt>
          <dd>
            {asset.license.id} — {asset.license.attribution}
          </dd>
        </dl>
      ) : null}
    </section>
  );
});
