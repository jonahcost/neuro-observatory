# WORK-2026-11-17-desktop-ui-refresh: Desktop instrument layout

- Status: Active
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0015-desktop-ui-refresh.md`

## Objective

Give the desktop app a graphite instrument layout: a compact status header, a dominant brain viewport, one five-mode display inspector, and the existing EEG waveform dock under the brain, without a second stream subscription or a camera reset on display change.

## Scope

In scope:

- `apps/desktop` shell, display picker, camera lifetime, selected-channel cue, and the tests for those paths.
- `docs/architecture/ANATOMY.md`: the framing sentence, so it matches the camera rule.
- This work record and ADR-0015.

Non-goals: protocol or simulator changes, mesh construction, RMS math, waveform gap rules, opacity controls, persisted preferences, routes, and hardware.

Dependencies: 03A and 03B on `6cf2a58`. ADR-0015 stays Proposed until the project owner accepts it.

## Acceptance Criteria

- [x] The header shows the existing synthetic or device source separately from connection and health, and the integrity list is still available.
- [x] Pial, White matter boundary, Inflated, Holographic, and Grid are one radiogroup. Holographic and Grid use pial. The default is solid pial. A missing surface disables its mode.
- [x] Switching modes keeps the canvas mounted, keeps orbit position and zoom, keeps the selected channel, and keeps the single `onBlock` subscription. A new subject still reframes.
- [x] The waveform dock reuses `WaveformView` at 480px. Loading, retry, reconnect, stale highlights, the inflated electrode note, and the white-matter fallback sentence still appear.
- [x] Keyboard focus is visible in CSS. A selected channel has a cue besides color. Reduced motion disables CSS transitions only.
- [x] Desktop lint, typecheck, tests, the workspace run-many, and the governance checks have been run, and the synthetic smoke test has been recorded.

## Implementation Summary

- Graphite tokens live in `apps/desktop/src/styles.css`. Canvas and marker colours that cannot read CSS variables live in `apps/desktop/src/theme.ts` (`#3cf0ff`, `#c4b5fd`, electrode `#9af7ff`). `:focus-visible` is a 2px cyan outline. `prefers-reduced-motion: reduce` shortens CSS animation and transition only.
- `App` is a header plus a workspace. The header shows “Neuro Observatory” and the existing stream status. Source and connection stay visible. The integrity list is inside a closed “Stream details” disclosure. The workspace columns are `minmax(0, 1fr)` and `300px`. Rows are `minmax(320px, 1fr)` and `minmax(220px, min(480px, 32vh))`. The plot content stays 480px and scrolls. The 32vh cap is what keeps the brain the taller row at 800px and 700px; a 480px dock row left the brain at its 320px minimum.
- The Surface and Rendering selects are one radiogroup. `displayModeFor` / `modeFrom` map Pial, White matter boundary, and Inflated to solid plus that surface, and Holographic and Grid to those presets on pial. A surface missing from the asset disables its radio. `BrainShell` still contains the other surface-by-preset branches.
- The last ready surfaces, framing, and asset stay mounted while the next surface loads or fails. `OrbitControls` is keyed by asset id. A new asset sets camera position, target, and far. A surface or preset change keeps position, target, and zoom, and only raises `camera.far`. `docs/architecture/ANATOMY.md` says the same.
- The selected channel is a label on `App`, default none. Lane labels are buttons with `aria-pressed`, violet text, and a left bar. `ElectrodeMarkers` reads that label from a ref inside the existing frame loop. RMS still drives opacity. Inflated still draws no markers. `paint` takes an optional emphasis colour and otherwise keeps `#7dd3fc`.
- One `EegStreamClient`, one `onBlock`, one `WaveformBuffer`, and one `ChannelActivity` remain in `App`. No opacity slider, route, dependency, or stored preference.
- After the first layout, the owner asked for a closer match to a reference card screen. The shell uses rounded cards, a header mark, a Live Brain title, a backdrop grid, Reset view, and an Activity overlay switch for the existing electrode markers. Wireframe and opaque surfaces use the same stacked rows. The header has no section tabs. The source pill says Synthetic EEG or Device EEG and still carries the full provenance sentence. Stream details is its own card to the left of the waveforms, with the integrity list always visible. The wireframe label sits above the Holographic and Grid buttons instead of overlapping them. The waveform heading says EEG Waveforms with the real 10 s and ±100 µV window. The longer trace sentence sits under Trace notes so the lanes stay visible. The reference’s opacity slider, “Simulated” wording, 5 s axis, and three-channel drawing were not copied.

## Validation Evidence

Final tree, after the dock-row change, on 2026-11-17:

- `NX_DAEMON=false yarn nx run-many -t lint test typecheck build --parallel=3 --skip-nx-cache --output-style=static` passed in 7.7s. Protocol: 98 tests. Desktop: lint and typecheck passed, 16 files / 90 tests. Engine: ruff passed, pytest 406 passed / 4 deselected. Vite build wrote `dist/apps/desktop`. Warnings: the desktop JS chunk is 1,364.52 kB (gzip 379.88 kB); pytest printed `StarletteDeprecationWarning` for `starlette.testclient`.
- Desktop tests in that run include `displayModes.spec.ts`, `cameraSession.spec.ts`, `theme.spec.ts`, `AnatomyViewer.spec.tsx` (preset switch does not refetch, delayed white load keeps `data-testid="scene"`, inflated 8 mm sentence, white-matter scaled-copy sentence), `WaveformView.spec.tsx` (Cz `aria-pressed`), `StreamStatusPanel.spec.tsx` (details opened before the integrity list), and `app.spec.tsx` (waveform region follows anatomy; Cz stays pressed after Grid; one `StubWebSocket`).

Synthetic smoke against the already-running Vite page at `http://localhost:4200` and the local engine. No headset.

- At 1280×800, device pixel ratio 1: header 51px, anatomy region 493×980, dock 256×980 with scroll height 584, plot client height 480, channel labels 12px, inspector 749×300. The page did not scroll. Holographic fsaverage showed the cyan wireframe, the interior marker, and the Holographic radio selected. Cz was pressed, violet, with a bar; the other traces stayed cyan. The header read the synthetic seed-0 source and “Connected · Live”.
- Camera hold: the perspective camera was moved to about `[40, 80, 120]` with far `3483.3`. Grid, Holographic, and White kept that pose and far. Inflated kept the pose and raised far to `4321.1`, showed the 8 mm sentence and “hidden on the inflated surface”, and hid the sensor-highlight line. Cz stayed `aria-pressed`. Switching subject to ds000248 reframed that same camera to about `[-386.9, 225.2, -289.5]`. Switching back to fsaverage framed again. The subject was returned to fsaverage and the mode to Pial after the check.
- At 1024×700, device pixel ratio 2: anatomy 425×724, dock 224×724 (scroll height 584, client 223), inspector 649×300 (scroll height 924). No page scroll. Labels stayed 12px. All five radios were present. The brain canvas backing store was 1448×850 for a 724×425 client. The waveform canvas backing store was 1240×960 for a 620×480 client.
- `prefers-reduced-motion: reduce` was emulated. `matchMedia` matched, and a radio’s computed `transition-duration` and `animation-duration` were `0.01ms`. The emulation was then cleared. Before the engine stop, a waveform pixel strip changed over 700ms (`876268` to `868068`), so the traces were still moving.
- The pre-existing `yarn nx run neuro-engine:serve` (pid 78707) was stopped. The header became “Disconnected — reconnecting (attempt 4) · Waiting for data”. Sensor highlights read “fading”. The same waveform strip stayed `860612` across 800ms. The same serve command was started again. The header returned to “Connected · Live”, highlights returned to “live”, the waveform caption included “Engine clock restarted (new stream). The gap is the observed outage”, and a later strip changed (`165961` to `183676`).
- The engine log for that restart accepted four `/ws/v2/eeg` connections from the already-open dev page. `app.spec.tsx` still sees one socket on a fresh mount. This layout does not add a second `onBlock`.
- `:focus-visible` is in `styles.css`. Programmatic focus and the embedded browser’s Tab did not match that pseudo-class, so a physical keyboard outline was not observed.

Governance, this working tree, ADR still Proposed and this record still active:

- `python3 tools/governance/check_governance.py --all` passed: “Governance check passed. Human review and scientific/safety validation still required.”
- `python3 tools/governance/check_governance.py --base origin/main --head HEAD` also passed. That comparison sees committed paths only. There is no implementation commit yet, so it does not see these files.
- A `check_change_set` dry run over the 24 working-tree paths failed, as the interim check before acceptance: “Implementation/config change requires an added or updated completed WORK record in this PR” and “ADR-0015-desktop-ui-refresh.md: Status must be Accepted”.

## Risks and Follow-ups

- An inflated brain can sit off the previous orbit target. Pan still works, and the far plane grows. Subject changes still reframe.
- Holographic-on-inflated and Grid-on-white remain in `BrainShell` and are not in the picker. Holographic in the picker stays on pial so the white inner shell still loads.
- The dock row uses `32vh` so the brain stays larger at the two checked window sizes. Below 960×640 the shell can scroll. There is no native window constraint.
- Violet is a selection cue. It does not change the RMS and is not a source estimate.
- The physical-keyboard focus outline was not observed in the embedded browser. The CSS rule is present.
- The desktop production chunk remains over 500 kB. That warning predates this layout.
- ADR-0015 is Proposed. This record stays in `docs/work/active/` until the owner accepts it. Nothing was committed.

## Human Review

The owner requested implementation of the proposed 03C plan on 2026-11-17. That request is not recorded here as acceptance of ADR-0015. The ADR stays Proposed, and this record stays Active, until the owner accepts it. No commit, push, or hardware check was made.
