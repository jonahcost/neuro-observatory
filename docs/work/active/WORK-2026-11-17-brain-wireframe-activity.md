# WORK-2026-11-17-brain-wireframe-activity: Wireframe brain presets and sensor highlights

- Status: Active
- Owner: Project owner
- ADRs: `docs/architecture/decisions/ADR-0014-brain-wireframe-activity.md`

## Objective

Show the existing cortical surface as two switchable wireframe presets, Holographic and Grid, and drive sensor-space electrode highlights from a one-second RMS of the live `/ws/v2/eeg` stream without a source estimate.

## Scope

- Desktop scene in `apps/desktop/src/anatomy/`: the original solid surface plus clustered Holographic and Grid presets, an interior test marker, template 10-20 display positions, an empty `pathway-layer`, and atlas vertex colours on all three renderings.
- Desktop stream in `apps/desktop/src/stream/channelActivity.ts` and the existing `onBlock` wiring in `apps/desktop/src/app/app.tsx`. The waveform view stays.
- Opt-in `NEURO_ENGINE_SYNTHETIC_CHANNEL_SCALES` on the synthetic adapter. Protocol v2 is unchanged.

Non-goals: cortical or atlas activity colours, electrode registration, forward or inverse models, bloom, pathway pulses, recording, and a `BrainSceneFrame` wire schema.

## Acceptance Criteria

- [x] A known change in one simulated channel raises only that channel's highlight.
- [x] Both presets keep the interior marker legible from the front, side, and rear, and switching presets does not move the camera.
- [x] Restarting the engine shows a stale stream and fading highlights, then recovery, while the waveform shows its restart gap.
- [x] Inflated surfaces hide electrode markers. Unmapped labels are not drawn as positions.
- [x] Tests listed in the validation section were run and their real results are recorded.
- [x] Solid remains a rendering choice beside Holographic and Grid. An atlas colours the solid surface and the full-resolution surface behind both wireframes.

## Implementation Summary

- Solid, Holographic, and Grid share the surface-RAS scene group. Solid is the original opaque surface and is the default. Orbit controls are not remounted when the rendering changes. Display lines are vertex-clustered (3.5 mm and 16 mm) and do not rewrite the FreeSurfer buffers. Atlas colours are the full-resolution vertex labels on Solid, and the same labels drawn behind the lines on the two wireframes.
- Holographic uses additive cyan lines, the white surface as an inner layer when pial is selected, a fresnel rim, and a second dimmer shell. Grid uses the historical sphere material on the sparser mesh. The interior probe is an 8 mm unlit sphere; 3 mm was not legible in the additive shell.
- The 16 synthetic labels use the Kayser and Tenke 2006 Table A1 unit vectors, placed outside the displayed folded surface. They are hidden on the inflated surface. `PathwayLayer` is an empty group that stores a `PathwayFrame`.
- `ChannelActivity` takes the same `onBlock` path as the waveform, publishes a 1 s RMS at 5 Hz, and the frame loop interpolates it. A non-live stream fades the highlights. `NEURO_ENGINE_SYNTHETIC_CHANNEL_SCALES` is opt-in and does not change the default block.

## Validation Evidence

- `yarn nx test desktop -- src/anatomy/displayLineMesh.spec.ts src/anatomy/template1020.spec.ts src/anatomy/electrodeDisplay.spec.ts src/anatomy/pathway.spec.ts src/stream/channelActivity.spec.ts src/anatomy/AnatomyViewer.spec.tsx src/stream/waveformBuffer.spec.ts src/stream/WaveformView.spec.tsx src/app/app.spec.tsx` — 9 files, 42 tests passed.
- `yarn nx run-many -t lint test typecheck --projects=desktop --output-style=static` — lint, test (72), and typecheck passed. A later `yarn nx run desktop:lint` also passed after the scene label change.
- `yarn nx run neuro-engine:test` — 406 passed, 4 deselected. `yarn nx run neuro-engine:lint` — ruff passed.
- Browser at `http://localhost:4200` against the local fsaverage asset: Holographic showed a fine cyan shell with the interior marker visible; orbiting moved the view and the marker stayed visible; switching to Grid kept that camera and showed a sparser blue mesh with the marker still visible. Stopping the engine showed `Disconnected — reconnecting` and `Sensor highlights: fading`. Starting it again with `NEURO_ENGINE_SYNTHETIC_CHANNEL_SCALES=Cz=4` returned `Connected · Live` and `Sensor highlights: live`, the waveform caption reported a new stream and an observed gap, and the Cz lane and Cz marker were the strongest.
- Follow-up in the same browser: Rendering lists Solid, Holographic, and Grid, and Solid is the default. With aparc selected, Solid shows the opaque coloured surface, Grid shows those colours through the blue gaps, and Holographic shows the same regions on the fine lines and on the surface behind them. `yarn nx test desktop -- src/anatomy/displayLineMesh.spec.ts src/anatomy/AnatomyViewer.spec.tsx` passed (4 and 7 tests). `yarn nx run desktop:lint` passed.

## Risks and Follow-ups

- The 10-20 table is a unit-sphere display model (Kayser and Tenke 2006, Table A1), not a registration to fsaverage or ds000248. Jurcak, Tsuzuki, and Dan 2007 is cited for that distinction. The owner still needs to accept ADR-0014 before it is marked Accepted.
- Cell sizes 3.5 mm and 16 mm, the 8 mm interior probe, holographic line opacity 0.18, the 30 µV display scale, the 5 Hz update, and the 0.6 s fade are starting defaults. The 3 mm probe was not legible.
- A later slice can animate `PathwayFrame` along explicit electrode pairs. Named cortical activation needs its own ADR.
- Rollback is a revert of the desktop preset path and the optional synthetic scale. Default synthetic blocks stay bit-identical when the scale is unset.

## Human Review

ADR-0014 is Proposed. Implementation follows the approved plan. The owner has not yet marked the ADR Accepted. The montage transcription and the spacing defaults remain open for that acceptance.
