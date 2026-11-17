# ADR-0015: Desktop instrument layout

- Status: Proposed
- Date: 2026-11-17
- Decision Owner: Project owner
- Related Work: `docs/work/active/WORK-2026-11-17-desktop-ui-refresh.md`
- Supersedes: None. Narrows the ADR-0014 viewer controls to five display modes and changes the ADR-0010 framing rule so a surface change no longer resets the camera.

## Context

Verified on `03C/desktop-ui-refresh` at `6cf2a58`, which includes 03A (`2f5aebe`) and 03B (`5937032`):

- `App` owns one `EegStreamClient`, one `WaveformBuffer`, and one `ChannelActivity`. A single `onBlock` feeds the buffer and the activity window. Samples stay out of React state.
- `useAnatomy` defaults to pial. `AnatomyViewer` defaults the rendering preset to solid. Those two selects combine into nine surface-by-preset views. Nothing is stored in `localStorage`. There is no router and no selected EEG channel.
- `OrbitControls` is keyed by `assetId#surfaceKind`. `FrameCamera` writes a new camera position whenever the framing changes. The `<Canvas>` unmounts while the next surface is loading, because `useAnatomy` leaves `surfaces` non-ready until that fetch returns. A preset change does not remount the controls, which is why Holographic and Grid kept the camera in 03B.
- Holographic on pial loads the white surface as an inner shell and falls back to a scaled copy when that fetch fails. Grid keeps the historical blue material. Inflated surfaces hide electrode markers and separate the hemispheres by 8 mm. Opacities are constants, not user controls.
- `WaveformView` is a 480px canvas above the anatomy section. It already draws with `devicePixelRatio`. The status panel already separates synthetic or device provenance from connection and health.
- The desktop app is the Vite dev server on `localhost:4200`. No minimum window is declared.

## Decision

1. **Presentation only.** Change the desktop shell, display picker, camera lifetime, and a selected-channel cue. Do not change protocol schemas, acquisition, anatomy assets, mesh builders, RMS math, or waveform gap rules. Do not add a dependency, a route, or persisted preferences. `zustand` stays unused.
2. **Five modes.** One radiogroup replaces the Surface and Rendering selects. Pial, White matter boundary, and Inflated are solid presets of those surfaces. Holographic and Grid are the pial wireframes from ADR-0014. A mode whose surface is absent from the asset is disabled. The default remains solid pial.
3. **Camera.** Keep the last ready canvas mounted while the next surface loads or fails. Key `OrbitControls` by asset id only. Frame position and orbit target when the asset changes. A surface or preset change keeps position, target, and zoom, and only raises `camera.far` when the new bounds need a larger far plane.
4. **Layout.** A compact header shows the app name and the existing source, connection, and health labels. The detailed integrity list sits in a closed disclosure. The brain viewport is the largest cell. The inspector holds the five modes, the existing subject, atlas, marker, pathway, and provenance. The waveform plot stays 480px tall and scrolls instead of compressing its labels. The dock row is `minmax(220px, min(480px, 32vh))`, so at the 1280×800 and 1024×700 checks the viewport stays taller than the dock.
5. **Selected channel.** A label in `App` state, default none, is shared by the waveform buttons and the electrode markers. The selected lane uses violet plus a bar and `aria-pressed`. The matching marker uses the same violet inside the existing frame loop; RMS still drives opacity. Inflated still draws no markers. A layout change that already clears the buffer clears the selection. Display switches do not.
6. **Status words.** Keep `CONNECTION_LABELS`, `HEALTH_LABELS`, and the synthetic or device provenance sentences. Do not rename Live to Streaming or Synthetic to Simulated.
7. **Motion and focus.** No new animation. `prefers-reduced-motion` disables CSS transitions only. `:focus-visible` draws a cyan outline.

## Alternatives Considered

- Leave the two selects and only restyle the page. Rejected: the milestone asks for five directly selectable displays, with wireframes grouped apart from the opaque surfaces.
- Preserve all nine surface-by-preset combinations in the picker. Rejected: that keeps Holographic-on-inflated and Grid-on-white in the UI. Those branches stay in `BrainShell`; the picker no longer reaches them. Holographic stays on pial so the white inner shell from ADR-0014 still applies.
- Snapshot orbit angles into a store and restore them after remounting the canvas. Rejected: the reset comes from unmounting the canvas and from keying the controls by surface kind. Keeping the canvas mounted is the smaller change.
- Add a mesh-opacity slider or `localStorage`. Rejected: opacity is a preset constant, and a saved preference would be a new persisted format.
- Draw the selected channel by copying samples into React state. Rejected: ADR-0012 keeps samples in the buffer. The view passes an optional emphasis color into `paint`.

## Consequences

- Switching from an inflated view to Holographic or Grid loads pial again and can leave the inflated mesh on screen until that load finishes. The camera does not jump. An inflated brain can sit off the previous orbit target; pan still works, and a larger far plane avoids clipping.
- The header and the waveform both show connection text, from the same labels. The waveform figure keeps the status line ADR-0012 already required.
- Violet marks a chosen channel. It is not a source estimate and does not change the RMS.
- A closed disclosure hides the integrity counters until opened. The source and connection lines stay visible.
- Rollback is reverting this desktop layout, the five-mode helper, and the camera-lifetime change. The stream client, buffer, and anatomy assets stay as they are.

## Validation and Rollback

Unit tests cover the five-mode mapping, the camera pose rule, preset switches that do not refetch the catalog, a delayed surface load that keeps the canvas mounted, the white-matter failure sentence, and a selected channel that survives a mode change. The commands and the synthetic smoke results are recorded in the related work record. This ADR stays Proposed until the project owner accepts it; the change-set gate looks for an Accepted ADR and a completed work record.

Rollback is a revert of the desktop presentation files, this ADR, and the work record. Protocol v2 and the anatomy asset contract are unchanged.
