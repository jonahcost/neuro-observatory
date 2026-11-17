import { memo, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import type { AnatomyAsset, AnatomyKind, SurfaceKind } from '@neuro-observatory/protocol';
import { RMS_FULL_SCALE_UV, type ActivityDisplay, type ChannelActivity } from '../stream/channelActivity';
import { BrainShell } from './BrainShell';
import styles from './AnatomyViewer.module.css';
import type { AnatomyClient, LoadedParcellation, LoadedSurface } from './anatomyClient';
import { cameraPoseAction, nextCameraFar, orbitControlsKey } from './cameraSession';
import { MODE_LABELS, OPAQUE_MODES, WIRE_MODES, displayModeFor, modeAvailable, modeFrom, type DisplayModeId } from './displayModes';
import type { RenderPresetId } from './renderPresets';
import { INFLATED_DISPLAY_GAP_MM, cameraFraming, displayBoundsMm, displayOffsetsMm, type Vec3 } from './sceneGeometry';
import { unmappedTemplateLabels } from './template1020';
import { useAnatomy, type AnatomyView, type Load } from './useAnatomy';

export const ANATOMY_KIND_LABELS: Record<AnatomyKind, string> = {
  template: 'Template anatomy — an average brain (fsaverage), not any individual',
  'reference-subject': "Reference subject — a public research participant's anatomy, not yours",
  personal: 'Personal anatomy — reconstructed from an MRI you imported',
};

interface HeldScene {
  asset: AnatomyAsset;
  surfaces: LoadedSurface[];
  surfaceKind: SurfaceKind;
  preset: RenderPresetId;
  parcellations: LoadedParcellation[] | null;
}

function FrameCamera({ assetId, position, far }: { assetId: string; position: Vec3; far: number }) {
  const camera = useThree((state) => state.camera);
  const appliedAsset = useRef<string | null>(null);
  useEffect(() => {
    const action = cameraPoseAction(appliedAsset.current, assetId);
    if (action === 'frame') {
      camera.position.set(position[0], position[1], position[2]);
      camera.near = 1;
      camera.far = far;
      appliedAsset.current = assetId;
    } else {
      const raised = nextCameraFar(camera.far, far);
      if (raised !== camera.far) {
        camera.far = raised;
      }
    }
    camera.updateProjectionMatrix();
  }, [assetId, camera, far, position]);
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

function ModeOptions({
  modes,
  legend,
  name,
  mode,
  available,
  onMode,
}: {
  modes: readonly DisplayModeId[];
  legend: string;
  name: string;
  mode: DisplayModeId;
  available: readonly SurfaceKind[];
  onMode: (mode: DisplayModeId) => void;
}) {
  return (
    <fieldset className={styles.group}>
      <legend>{legend}</legend>
      {modes.map((id) => (
        <label key={id} className={styles.option}>
          <input
            type="radio"
            name={name}
            value={id}
            checked={mode === id}
            disabled={!modeAvailable(id, available)}
            onChange={() => onMode(id)}
          />
          {MODE_LABELS[id]}
        </label>
      ))}
    </fieldset>
  );
}

function DisplayInspector({
  view,
  mode,
  onMode,
  showMarker,
  onMarker,
  showPathway,
  onPathway,
  electrodesHidden,
  highlight,
  unmapped,
  companionFailed,
  shown,
}: {
  view: AnatomyView;
  mode: DisplayModeId;
  onMode: (mode: DisplayModeId) => void;
  showMarker: boolean;
  onMarker: (show: boolean) => void;
  showPathway: boolean;
  onPathway: (show: boolean) => void;
  electrodesHidden: boolean;
  highlight: ActivityDisplay;
  unmapped: readonly string[];
  companionFailed: boolean;
  shown: HeldScene | null;
}) {
  const subjectId = useId();
  const atlasId = useId();
  const markerId = useId();
  const pathwayId = useId();
  const modeName = useId();
  const catalog = view.catalog.state === 'ready' ? view.catalog.value : null;
  const asset = view.asset.state === 'ready' ? view.asset.value : null;
  const available = (['pial', 'white', 'inflated'] as const).filter((kind) => asset?.surfaces.some((surface) => surface.surface === kind));
  const atlases = [...new Set(asset?.parcellations.map((parcellation) => parcellation.atlas) ?? [])];
  const described = shown?.asset ?? asset;
  const surfaceKind = shown?.surfaceKind ?? view.surfaceKind;
  const preset = shown?.preset ?? displayModeFor(mode).preset;
  const atlasDescription = shown?.parcellations?.[0]?.description;

  return (
    <>
      <div role="radiogroup" aria-label="Brain display" className={styles.modes}>
        <ModeOptions modes={OPAQUE_MODES} legend="Opaque surfaces" name={modeName} mode={mode} available={available} onMode={onMode} />
        <ModeOptions modes={WIRE_MODES} legend="Wireframe" name={modeName} mode={mode} available={available} onMode={onMode} />
      </div>
      <div>
        <label className={styles.field} htmlFor={subjectId}>
          Subject
          <select
            id={subjectId}
            value={view.assetId ?? ''}
            disabled={!catalog || catalog.assets.length === 0}
            onChange={(event) => view.selectAsset(event.target.value)}
          >
            {catalog?.assets.map((item) => (
              <option key={item.assetId} value={item.assetId}>
                {item.subject.displayName} [{item.anatomyKind}]
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field} htmlFor={atlasId}>
          Anatomical atlas colouring
          <select
            id={atlasId}
            value={view.atlas ?? ''}
            disabled={!asset || atlases.length === 0}
            onChange={(event) => view.selectAtlas(event.target.value || null)}
          >
            <option value="">None</option>
            {atlases.map((atlas) => (
              <option key={atlas} value={atlas}>
                {atlas}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.check} htmlFor={markerId}>
          <input id={markerId} type="checkbox" checked={showMarker} onChange={(event) => onMarker(event.target.checked)} /> Interior test marker
        </label>
        <label className={styles.check} htmlFor={pathwayId}>
          <input id={pathwayId} type="checkbox" checked={showPathway} onChange={(event) => onPathway(event.target.checked)} /> Pathway layer
        </label>
        <button className={styles.action} type="button" onClick={view.retry} disabled={view.catalog.state === 'loading'}>
          Refresh subjects
        </button>
      </div>
      {electrodesHidden ? null : (
        <p data-testid="sensor-highlight-status" className={styles.note}>
          Sensor highlights: {highlight.error ? `unavailable. ${highlight.error}` : highlight.health}
          {highlight.missingSamples > 0 ? `. The last 1 s is missing ${highlight.missingSamples} samples.` : ''}
          {unmapped.length > 0 ? `. Unmapped channels: ${unmapped.join(', ')}` : ''}
        </p>
      )}
      {showMarker ? <p className={styles.note}>Interior test marker — display probe, not anatomy.</p> : null}
      {companionFailed ? (
        <p className={styles.note}>
          The white-matter surface did not load. The inner shell is a scaled copy of the displayed surface, not the white-matter boundary.
        </p>
      ) : null}
      {showPathway ? <p className={styles.note}>Pathway layer on — no pulses in this slice.</p> : null}
      {described ? (
        <dl data-testid="anatomy-provenance" className={styles.provenance}>
          <dt>Anatomy</dt>
          <dd data-testid="anatomy-kind">{ANATOMY_KIND_LABELS[described.anatomyKind]}</dd>
          <dt>Source</dt>
          <dd>
            {described.subject.datasetId} {described.subject.datasetVersion} · <AcquisitionFacts asset={described} />
          </dd>
          <dt>Geometry</dt>
          <dd>
            FreeSurfer surfaces in surface RAS, millimetres, full resolution
            {surfaceKind === 'inflated'
              ? `; inflated hemispheres separated by ${INFLATED_DISPLAY_GAP_MM} mm for display. Electrode display positions are hidden on the inflated surface because inflation moves the anatomy`
              : ''}
          </dd>
          <dt>Colour</dt>
          <dd>
            {atlasDescription
              ? `${atlasDescription} — anatomical labels, not activity.${
                  preset === 'solid' ? '' : ' On Holographic and Grid these colours stay on the full-resolution surface behind the display lines.'
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
            {described.license.id} — {described.license.attribution}
          </dd>
        </dl>
      ) : null}
    </>
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
  selectedChannel = null,
  viewportClassName,
  inspectorClassName,
}: {
  client: AnatomyClient;
  activity: ChannelActivity;
  selectedChannel?: string | null;
  viewportClassName?: string;
  inspectorClassName?: string;
}) {
  const view = useAnatomy(client);
  const [preset, setPreset] = useState<RenderPresetId>('solid');
  const [showMarker, setShowMarker] = useState(true);
  const [showPathway, setShowPathway] = useState(false);
  const [highlight, setHighlight] = useState<ActivityDisplay>(() => activity.sampleDisplay(0));
  const heldRef = useRef<HeldScene | null>(null);
  const framedAssetId = useRef<string | null>(null);
  const orbitTarget = useRef<Vec3 | null>(null);
  const orbitPosition = useRef<Vec3 | null>(null);
  const selectedLabelRef = useRef<string | null>(selectedChannel);
  selectedLabelRef.current = selectedChannel;
  useEffect(() => {
    const update = () => setHighlight(activity.sampleDisplay(performance.now()));
    update();
    return activity.subscribe(update);
  }, [activity]);
  const asset = view.asset.state === 'ready' ? view.asset.value : null;
  const surfaces = view.surfaces.state === 'ready' ? view.surfaces.value : null;
  const parcellations = view.parcellations.state === 'ready' ? view.parcellations.value : null;
  const previousHold = heldRef.current;
  if (
    asset &&
    surfaces &&
    (previousHold === null ||
      previousHold.asset !== asset ||
      previousHold.surfaces !== surfaces ||
      previousHold.surfaceKind !== view.surfaceKind ||
      previousHold.preset !== preset ||
      previousHold.parcellations !== parcellations)
  ) {
    heldRef.current = {
      asset,
      surfaces,
      surfaceKind: view.surfaceKind,
      preset,
      parcellations,
    };
  }
  const shown = heldRef.current;
  const framing = useMemo(() => {
    if (!shown) {
      return null;
    }
    const bounds = displayBoundsMm(shown.surfaces, displayOffsetsMm(shown.surfaces, shown.surfaceKind));
    return bounds ? cameraFraming(bounds) : null;
  }, [shown]);
  if (shown && framing && framedAssetId.current !== shown.asset.assetId) {
    framedAssetId.current = shown.asset.assetId;
    orbitTarget.current = framing.target;
    orbitPosition.current = framing.position;
  }
  const poseTarget = orbitTarget.current;
  const posePosition = orbitPosition.current;
  const error = firstError(view);
  const loading = statusText(view);
  const empty = view.catalog.state === 'ready' && view.catalog.value.assets.length === 0;
  const wantWhite =
    preset === 'holographic' && view.surfaceKind === 'pial' && asset !== null && asset.surfaces.some((surface) => surface.surface === 'white');
  const companion = useCompanionSurface(client, wantWhite ? asset : null, wantWhite ? 'white' : null);
  const labelKey = [...highlight.byLabel.keys()].join('\n');
  const channelLabels = useMemo(() => (labelKey === '' ? [] : labelKey.split('\n')), [labelKey]);
  const unmapped = unmappedTemplateLabels(channelLabels);
  const mode = modeFrom(view.surfaceKind, preset);
  const electrodesHidden = (shown?.surfaceKind ?? view.surfaceKind) === 'inflated';
  const companionFailed = companion.failed && shown?.preset === 'holographic' && shown.surfaceKind === 'pial';
  const selectMode = (next: DisplayModeId) => {
    const selection = displayModeFor(next);
    view.selectSurface(selection.surfaceKind);
    setPreset(selection.preset);
  };

  return (
    <>
      <div className={[viewportClassName, styles.viewport].filter(Boolean).join(' ')} role="region" aria-label="Cortical anatomy">
        <div className={styles.scene} role="region" aria-label="Brain scene">
          {shown && framing && poseTarget && posePosition ? (
            <Canvas camera={{ fov: 35, near: 1, far: framing.far, position: posePosition }}>
              <FrameCamera assetId={shown.asset.assetId} position={posePosition} far={framing.far} />
              <hemisphereLight args={['#ffffff', '#30343f', 1.1]} />
              <directionalLight position={[300, 400, 300]} intensity={1.6} />
              <directionalLight position={[-300, -100, -300]} intensity={0.6} />
              <BrainShell
                surfaces={shown.surfaces}
                preset={shown.preset}
                showMarker={showMarker}
                showPathway={showPathway}
                activity={activity}
                channelLabels={channelLabels}
                innerSurfaces={shown.preset === 'holographic' && shown.surfaceKind === 'pial' ? companion.surfaces : null}
                parcellations={shown.parcellations}
                selectedLabelRef={selectedLabelRef}
              />
              <OrbitControls
                key={orbitControlsKey(shown.asset.assetId)}
                makeDefault
                target={poseTarget}
                enablePan
                enableZoom
                enableRotate
              />
            </Canvas>
          ) : null}
          <div className={styles.status} role="status" aria-live="polite">
            {loading}
            {empty
              ? 'No anatomy prepared yet. Run: neuro-engine datasets fetch fsaverage --accept-license, then ' +
                'neuro-engine anatomy prepare fsaverage, and choose Refresh subjects'
              : null}
          </div>
          {error ? (
            <div className={styles.alert} role="alert">
              Anatomy unavailable ({error.kind}): {error.message}{' '}
              <button type="button" onClick={view.retry}>
                Retry
              </button>
            </div>
          ) : null}
        </div>
      </div>
      <aside className={[inspectorClassName, styles.inspector].filter(Boolean).join(' ')} aria-label="Display inspector">
        <DisplayInspector
          view={view}
          mode={mode}
          onMode={selectMode}
          showMarker={showMarker}
          onMarker={setShowMarker}
          showPathway={showPathway}
          onPathway={setShowPathway}
          electrodesHidden={electrodesHidden}
          highlight={highlight}
          unmapped={unmapped}
          companionFailed={companionFailed}
          shown={shown}
        />
      </aside>
    </>
  );
});
