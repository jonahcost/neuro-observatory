# WORK-2026-11-17-brain-wireframe-activity: Wireframe brain presets and sensor highlights

- Status: Completed
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
- [x] An index gap occupies the one-second RMS window and contributes no voltage. A resent block does not double-count samples. A reference, provenance, or backwards-clock change drops the window. A stream past the highlight cap clears the previous highlight and says why.
- [x] The activity caption names the one-second RMS and the 30 µV display scale. A failed white-matter load says the inner shell is a scaled copy. The interior-marker sentence follows the checkbox.

## Implementation Summary

- Solid, Holographic, and Grid share the surface-RAS scene group. Solid is the original opaque surface and is the default. Orbit controls are not remounted when the rendering changes. Display lines are vertex-clustered (3.5 mm and 16 mm) and do not rewrite the FreeSurfer buffers. Atlas colours are the full-resolution vertex labels on Solid, and the same labels drawn behind the lines on the two wireframes.
- Holographic uses additive cyan lines, the white surface as an inner layer when pial is selected, a fresnel rim, and a second dimmer shell. Grid uses the historical sphere material on the sparser mesh. The interior probe is an 8 mm unlit sphere; 3 mm was not legible in the additive shell.
- The 16 synthetic labels use the Kayser and Tenke 2006 Table A1 unit vectors, placed outside the displayed folded surface. They are hidden on the inflated surface. `PathwayLayer` is an empty group that stores a `PathwayFrame`.
- `ChannelActivity` takes the same `onBlock` path as the waveform and publishes a 1 s RMS at 5 Hz. The window follows the sample index: gaps take slots and are omitted from the mean, overlapping blocks contribute only their new tail, and `droppedSamplesBefore` does not invent time. Labels, units, channel types, references, rate, and provenance kind are the layout. A new stream id or a backwards source clock drops the window. A stream past 64 channels or 20 000 samples clears the previous highlight and sets an error. The frame loop eases between RMS snapshots, and the missing-sample count stays with the snapshot on screen. A non-live stream fades the highlights. `NEURO_ENGINE_SYNTHETIC_CHANNEL_SCALES` is opt-in and does not change the default block.
- Review correction, 2026-11-17: the 10-20 citation is Clinical Neurophysiology 2006;117(2):348–368, Table A1. The values were already the published unit vectors. `docs/architecture/ANATOMY.md` now describes sensor-space highlights and `BrainShell`. The interior-marker sentence is hidden with the marker. A failed white-matter fetch says the inner shell is a scaled copy of the displayed surface.

## Validation Evidence

- `yarn nx test desktop -- src/anatomy/displayLineMesh.spec.ts src/anatomy/template1020.spec.ts src/anatomy/electrodeDisplay.spec.ts src/anatomy/pathway.spec.ts src/stream/channelActivity.spec.ts src/anatomy/AnatomyViewer.spec.tsx src/stream/waveformBuffer.spec.ts src/stream/WaveformView.spec.tsx src/app/app.spec.tsx` — recorded as 9 files, 42 tests. Re-run of that file list on the pre-fix tree was 9 files, 43 tests. The earlier count was short by one.
- `yarn nx run-many -t lint test typecheck --projects=desktop --output-style=static` — lint, test (72), and typecheck passed before the review fixes. A later `yarn nx run desktop:lint` also passed after the scene label change.
- `yarn nx run neuro-engine:test` — 406 passed, 4 deselected, before the review fixes. `yarn nx run neuro-engine:lint` — ruff passed. The review fixes do not change the engine.
- Browser at `http://localhost:4200` against the local fsaverage asset, before the review fixes: Holographic showed a fine cyan shell with the interior marker visible; orbiting moved the view and the marker stayed visible; switching to Grid kept that camera and showed a sparser blue mesh with the marker still visible. Stopping the engine showed `Disconnected — reconnecting` and `Sensor highlights: fading`. Starting it again with `NEURO_ENGINE_SYNTHETIC_CHANNEL_SCALES=Cz=4` returned `Connected · Live` and `Sensor highlights: live`, the waveform caption reported a new stream and an observed gap, and the Cz lane and Cz marker were the strongest. This browser pass was not repeated after the RMS-window correction.
- Follow-up in the same browser, before the review fixes: Rendering lists Solid, Holographic, and Grid, and Solid is the default. With aparc selected, Solid shows the opaque coloured surface, Grid shows those colours through the blue gaps, and Holographic shows the same regions on the fine lines and on the surface behind them.
- Review fixes, 2026-11-17: `yarn nx test desktop` — 13 files, 80 tests passed. `yarn nx run desktop:lint --skip-nx-cache` — eslint passed. `yarn nx run desktop:typecheck --skip-nx-cache` — `tsc -p tsconfig.app.json --noEmit` passed. `python3 tools/governance/check_governance.py --all` passed. `python3 tools/governance/check_governance.py --base main --head HEAD` failed before acceptance, because that comparison sees only commit `9953197`. After ADR-0014 was accepted and this record was moved to `docs/work/completed/`, a `check_change_set` over the committed plus uncommitted paths passed.

## Risks and Follow-ups

- The 10-20 table is a unit-sphere display model (Kayser and Tenke, Clinical Neurophysiology 2006;117(2):348–368, Table A1), not a registration to fsaverage or ds000248. Jurcak, Tsuzuki, and Dan 2007 is cited for that distinction. The owner accepted that display model, and the spacing and display defaults, on 2026-11-17.
- Cell sizes 3.5 mm and 16 mm, the 8 mm interior probe, holographic line opacity 0.18, the 30 µV display scale, the 5 Hz update, and the 0.6 s fade are starting defaults. The 3 mm probe was not legible. Raw RMS includes DC, so an unfiltered device stream can sit at full scale.
- The displayed RMS eases across one publish interval. A slow block stretches that ease to the time since the previous snapshot.
- `CorticalSurfaceView` is no longer mounted. `BrainShell` is the viewer. The old component is still in the tree.
- A later slice can animate `PathwayFrame` along explicit electrode pairs. Named cortical activation needs its own ADR.
- Rollback of the review fixes is a revert of the sample-index window, the cap error, and the caption changes. Rollback of the milestone is a revert of the desktop preset path and the optional synthetic scale. Default synthetic blocks stay bit-identical when the scale is unset.

## Human Review

The owner accepted ADR-0014 on 2026-11-17, including the verified Table A1 montage and the spacing and display defaults, after the justified review fixes were applied. The review fixes and this completed record are in the working tree and are not yet committed.
