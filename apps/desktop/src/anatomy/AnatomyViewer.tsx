import { memo, useEffect, useId, useMemo, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import type { AnatomyAsset, AnatomyKind, SurfaceKind } from '@neuro-observatory/protocol';
import { RMS_FULL_SCALE_UV, type ActivityDisplay, type ChannelActivity } from '../stream/channelActivity';
import { BrainShell } from './BrainShell';
import type { AnatomyClient, LoadedSurface } from './anatomyClient';
import { RENDER_PRESETS, presetLabel, type RenderPresetId } from './renderPresets';
import { INFLATED_DISPLAY_GAP_MM, cameraFraming, displayBoundsMm, displayOffsetsMm, type Vec3 } from './sceneGeometry';
import { unmappedTemplateLabels } from './template1020';
import { useAnatomy, type AnatomyView, type Load } from './useAnatomy';

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

function AnatomyControls({
  view,
  preset,
  onPreset,
  showMarker,
  onMarker,
  showPathway,
  onPathway,
}: {
  view: AnatomyView;
  preset: RenderPresetId;
  onPreset: (preset: RenderPresetId) => void;
  showMarker: boolean;
  onMarker: (show: boolean) => void;
  showPathway: boolean;
  onPathway: (show: boolean) => void;
}) {
  const subjectId = useId();
  const surfaceId = useId();
  const atlasId = useId();
  const presetId = useId();
  const markerId = useId();
  const pathwayId = useId();
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
      <label htmlFor={presetId}>
        Rendering{' '}
        <select id={presetId} value={preset} onChange={(event) => onPreset(event.target.value as RenderPresetId)}>
          {RENDER_PRESETS.map((id) => (
            <option key={id} value={id}>
              {presetLabel(id)}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor={markerId}>
        <input id={markerId} type="checkbox" checked={showMarker} onChange={(event) => onMarker(event.target.checked)} /> Interior test marker
      </label>
      <label htmlFor={pathwayId}>
        <input id={pathwayId} type="checkbox" checked={showPathway} onChange={(event) => onPathway(event.target.checked)} /> Pathway layer
      </label>
      <button type="button" onClick={view.retry} disabled={view.catalog.state === 'loading'}>
        Refresh subjects
      </button>
    </div>
  );
}

function useCompanionSurface(
  client: AnatomyClient,
  asset: AnatomyAsset | null,
  kind: SurfaceKind | null,
): { surfaces: LoadedSurface[] | null; failed: boolean } {
  const [value, setValue] = useState<LoadedSurface[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (asset === null || kind === null) {
      setValue(null);
      setFailed(false);
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    client.loadSurfaces(asset, kind, controller.signal).then(
      (surfaces) => {
        if (!cancelled) {
          setValue(surfaces);
          setFailed(false);
        }
      },
      () => {
        if (!cancelled) {
          setValue(null);
          setFailed(true);
        }
      },
    );
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [client, asset, kind]);
  return { surfaces: value, failed };
}

export const AnatomyViewer = memo(function AnatomyViewer({
  client,
  activity,
}: {
  client: AnatomyClient;
  activity: ChannelActivity;
}) {
  const view = useAnatomy(client);
  const [preset, setPreset] = useState<RenderPresetId>('solid');
  const [showMarker, setShowMarker] = useState(true);
  const [showPathway, setShowPathway] = useState(false);
  const [highlight, setHighlight] = useState<ActivityDisplay>(() => activity.sampleDisplay(0));
  useEffect(() => {
    const update = () => setHighlight(activity.sampleDisplay(performance.now()));
    update();
    return activity.subscribe(update);
  }, [activity]);
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
  const wantWhite =
    preset === 'holographic' && view.surfaceKind === 'pial' && asset !== null && asset.surfaces.some((surface) => surface.surface === 'white');
  const companion = useCompanionSurface(client, wantWhite ? asset : null, wantWhite ? 'white' : null);
  const innerSurfaces = companion.surfaces;
  const labelKey = [...highlight.byLabel.keys()].join('\n');
  const channelLabels = useMemo(() => (labelKey === '' ? [] : labelKey.split('\n')), [labelKey]);
  const unmapped = unmappedTemplateLabels(channelLabels);

  return (
    <section aria-label="Cortical anatomy" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 8 }}>
      <AnatomyControls
        view={view}
        preset={preset}
        onPreset={setPreset}
        showMarker={showMarker}
        onMarker={setShowMarker}
        showPathway={showPathway}
        onPathway={setShowPathway}
      />
      <p data-testid="sensor-highlight-status" style={{ margin: 0 }}>
        Sensor highlights: {highlight.error ? `unavailable. ${highlight.error}` : highlight.health}
        {highlight.missingSamples > 0 ? `. The last 1 s is missing ${highlight.missingSamples} samples.` : ''}
        {unmapped.length > 0 ? `. Unmapped channels: ${unmapped.join(', ')}` : ''}
      </p>
      {showMarker ? <p style={{ margin: 0 }}>Interior test marker — display probe, not anatomy.</p> : null}
      {companion.failed ? (
        <p style={{ margin: 0 }}>
          The white-matter surface did not load. The inner shell is a scaled copy of the displayed surface, not the white-matter boundary.
        </p>
      ) : null}
      {showPathway ? <p style={{ margin: 0 }}>Pathway layer on — no pulses in this slice.</p> : null}

      <div role="region" aria-label="Brain scene" style={{ height: '55vh', position: 'relative', background: '#05070f', borderRadius: 6 }}>
        {surfaces && framing && asset ? (
          <Canvas camera={{ fov: 35, near: 1, far: framing.far, position: framing.position }}>
            <FrameCamera position={framing.position} far={framing.far} />
            <hemisphereLight args={['#ffffff', '#30343f', 1.1]} />
            <directionalLight position={[300, 400, 300]} intensity={1.6} />
            <directionalLight position={[-300, -100, -300]} intensity={0.6} />
            <BrainShell
              surfaces={surfaces}
              preset={preset}
              showMarker={showMarker}
              showPathway={showPathway}
              activity={activity}
              channelLabels={channelLabels}
              innerSurfaces={innerSurfaces}
              parcellations={parcellations}
            />
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
              ? `; inflated hemispheres separated by ${INFLATED_DISPLAY_GAP_MM} mm for display. Electrode display positions are hidden on the inflated surface because inflation moves the anatomy`
              : ''}
          </dd>
          <dt>Colour</dt>
          <dd>
            {atlasDescription
              ? `${atlasDescription} — anatomical labels, not activity.${
                  preset === 'solid'
                    ? ''
                    : ' On Holographic and Grid these colours stay on the full-resolution surface behind the display lines.'
                }`
              : 'Uniform surface colour'}
          </dd>
          <dt>Activity</dt>
          <dd data-testid="activity-overlay">
            Sensor-space highlights are the one-second RMS of accepted samples, in µV, drawn against a {RMS_FULL_SCALE_UV} µV
            display scale. Missing samples in that second are left out of the mean. These are template display positions, not
            registered electrodes and not a source estimate.
            {highlight.synthetic ? ' Synthetic streams are generated, not measured.' : ''}
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
