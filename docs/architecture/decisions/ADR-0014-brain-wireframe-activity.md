# ADR-0014: Wireframe brain presets and sensor highlights

- Status: Accepted
- Date: 2026-11-17
- Decision Owner: Project owner (accepted the verified Table A1 montage and the spacing and display defaults on 2026-11-17)
- Related Work: `docs/work/completed/WORK-2026-11-17-brain-wireframe-activity.md`
- Supersedes: None. Narrows only the ADR-0010 viewer sentence that no activity is drawn, and only for these sensor-space markers. The vertex-overlay ban stands.

## Context

Verified on `03B/brain-wireframe-activity` at `2f5aebe`:

- The desktop draws full-resolution FreeSurfer surfaces in `freesurfer-surface-ras` millimetres. One group rotation, `[-π/2, 0, 0]` in `sceneGeometry.ts`, maps that frame onto Three.js. Vertex buffers are not rewritten. fsaverage pial is 163 842 vertices and 327 680 triangles per hemisphere. A sample of those edges has a median length of about 0.76 mm. Atlas colours are per-vertex anatomical labels. `CorticalOverlay` has no producer.
- The pre-anatomy placeholder (`a8df9f4^:apps/desktop/src/app/app.tsx`) was `sphereGeometry(1.5, 48, 32)` with `meshStandardMaterial` colour `#49a4ff`, `wireframe`, emissive `#174f85`, and `emissiveIntensity` 0.3. That is a triangulated latitude/longitude grid at WebGL line width 1. On an ~87 mm bounding radius those chords are about 11 mm and 8.5 mm.
- EEG is protocol v2 on `/ws/v2/eeg`. The desktop `WaveformBuffer` keeps 10 s of accepted samples for the canvas plot. Nothing computes RMS. Default synthetic channels differ by phase, so a one-second RMS is nearly the same on every channel. There is no electrode table in the asset, and `pipelines/electrode-registration/` is empty.
- ADR-0006 wants a display-independent scene eventually. ADR-0008 keeps samples out of React state and acquisition independent of clients. ADR-0010 forbids painting the 16 synthetic channels onto cortical vertices. ADR-0012/0013 freeze the waveform across a disconnect and draw an observed hole on resume.

## Decision

1. **Three renderings, one anatomy frame.** Solid keeps the original opaque `meshStandardMaterial`. Holographic and Grid are additional presets, not replacements. All three use surface RAS millimetres and the existing scene rotation. The `OrbitControls` key stays `assetId#surfaceKind`, so a rendering change does not reset the camera, zoom, electrodes, marker, or activity.
2. **Display line meshes are not the scientific surface.** Full pial edges are the comparison baseline and are too dense to leave the interior readable. Both presets draw a vertex-clustered triangle mesh. The starting cell is 3.5 mm for Holographic and 16 mm for Grid (sparser than the historical sphere chords). Native buffers are not rewritten and are not a source space.
3. **Holographic.** Fine additive cyan lines, a dimmer inner layer (the white surface when pial is selected and white is in the manifest; otherwise a 0.94 scale about the display bounds centre), a brighter fresnel silhouette on the full-resolution surface, and one larger, dimmer additive shell. No bloom pass and no new dependency.
4. **Grid.** The historical sphere material and line width, on the 16 mm mesh, plus a faint rim so the outline survives the larger gaps.
5. **Interior test marker.** An unlit sphere at the display bounds centre, toggled on by default, labelled as a display probe. The radius started at 3 mm and is 8 mm, because 3 mm disappeared inside the additive shell at the default framing. Holographic line opacity starts at 0.18, with a low facing fresnel, so the marker stays legible. Pathway animation is not part of this slice.
6. **Sensor-space highlights only.** The 16 synthetic names are placed from the published unit-sphere 10-20 coordinates in Kayser and Tenke, Clinical Neurophysiology 2006;117(2):348–368, Table A1 (the spherical model of the international 10-20 percentage arcs; Oostenveld and Praamstra 2001). Jurcak, Tsuzuki, and Dan, NeuroImage 2007, is the reason this is treated as a relative head-surface layout rather than a registration. Axes match surface RAS: +x right, +y anterior, +z superior. The display radius is the distance from the displayed folded surface's bounds centre to its farthest vertex, plus 12 mm. Markers are hidden on the inflated surface. Unknown labels are listed and not drawn. Copy states that brightness is the one-second RMS of accepted samples, in µV, drawn against 30 µV, and that the positions are template display positions, not registered electrodes and not a source estimate. Atlas colours stay anatomical labels, not activity. On Solid they are the opaque vertex colours. On Holographic and Grid the same full-resolution vertex colours are drawn behind the display lines. Holographic lines use the mean colour of the vertices in each cell, which can blend a boundary cell, and the wash keeps the exact label. Grid lines stay the historical blue. While an atlas is selected, Holographic drops the additive glow so the labels stay readable. With no atlas, the additive holographic shell is unchanged.
7. **Activity path.** `ChannelActivity` subscribes to the same `onBlock` callback as `WaveformBuffer`. It keeps its own one-second ring on the sample index, publishes per-channel RMS (`sqrt(mean(x^2))` in µV) at 5 Hz, and does not put samples in React state. An index gap occupies that window and contributes no voltage; `droppedSamplesBefore` does not add further slots when it disagrees with the index. A resent block contributes only samples at or after the next index. Layout identity is the waveform's: labels, units, channel types, references, nominal rate, and provenance kind. A new `streamId`, or a same-id clock that steps backwards by more than half a sample, drops the window instead of averaging the two clocks. The frame loop only interpolates the last two RMS snapshots. Display intensity is `clamp(rms / 30 µV, 0, 1)`. When the stream is not live, intensity fades with a 0.6 s time constant. A stream past 64 channels or 20 000 samples in the one-second window clears any previous highlight and reports the cap. The waveform viewer is unchanged.
8. **One-channel demonstration.** Default `generate_block` output stays bit-identical. `NEURO_ENGINE_SYNTHETIC_CHANNEL_SCALES` (for example `Cz=4`) multiplies those rows and is included in `config_hash` only when a scale is set. Protocol v2 is unchanged.
9. **Pathway slot.** An empty group named `pathway-layer` holds a Three-free `PathwayFrame`: electrode label, surface-RAS position, interpolated intensity, time, and a stale flag. A later slice may animate explicit endpoint pairs and flashes from that frame. It must not create a `CorticalOverlay`.

## Alternatives Considered

- Draw every native triangle edge. Rejected: about 0.76 mm median spacing becomes a near-solid cyan shell at the current framing and hides an interior marker.
- Recolour the clustered line mesh by a majority atlas label. Rejected: a 16 mm cell can cover more than one region, and the resulting colour would not be a vertex label. The wash uses the scientific mesh instead.
- Keep the opaque `meshStandardMaterial` and tint vertices from RMS. Rejected: that is the cortical overlay ADR-0010 forbids, and it does not match either preset.
- Use MNE `standard_1020` or ds000248 digitized points. Rejected for this slice: those coordinates are not in the served asset, and dropping them into surface RAS without a head↔MRI transform would look like a registration. The spherical table is labelled as a display model.
- Compute RMS inside `useFrame` from `WaveformBuffer`. Rejected: the 10 s plot buffer and the 1 s feature would be coupled, and signal processing would sit in the render loop.
- Change the default synthetic mixture so channels differ in amplitude. Rejected: it would make the everyday stream a special demo. The scale is opt-in and hashed when used.
- Add UnrealBloom or a `BrainSceneFrame` wire schema. Rejected here: glow is a second mesh, and the scene frame stays a desktop TypeScript value until a display-protocol ADR.
- Treat an index gap as 0 µV, or pack accepted samples together and call that one second. Rejected after review: both state a voltage or a duration the sample clock does not contain. The gap takes time and is omitted from the mean. The waveform already places samples by index (ADR-0013).

## Consequences

- The viewer no longer says that nothing is drawn from the EEG stream. It says the marks are sensor-space display highlights. A reader can still mistake the spherical electrodes for a subject montage; the caption and the inflated-surface hide are the mitigations.
- Clustering does not preserve a vertex map back to FreeSurfer. That is acceptable because the line mesh is discarded on the next surface change and is never an inverse source space.
- Full-resolution fresnel shells still upload the scientific mesh to the GPU as a display surface. They do not decimate the asset.
- A 30 µV full scale is a display convention. Resting synthetic RMS is about 15 µV. It is not a calibrated power.
- Empty `channel_scales` are omitted from `config_hash`, so the default provenance hash is unchanged. A demo scale changes the hash and the samples together.
- Restart behaviour of the waveform is untouched. Highlights fade instead of freezing, which is a different display rule and is labelled in the brain status line. A new stream or a backwards source clock clears the RMS window; the plot keeps its own hole.
- A one-second window that still contains a gap says how many samples are missing. The displayed RMS and that count stay on the previous snapshot until the ease arrives at the new one, one publish interval later.

## Validation and Rollback

- Unit tests: the 16 mm mesh is coarser than the 3.5 mm mesh and keeps a sulcus; the 16 labels match the published vectors; Cz-only amplitude raises only Cz; interpolation stays between RMS snapshots; a stale stream fades; a new `streamId` drops the old RMS; an index gap ages old samples out of the second and a larger `droppedSamplesBefore` does not invent time; an overlapping resend keeps only its new tail; a reference or provenance change, and a backwards source clock, clear the window; a stream past the channel cap clears the previous highlight; default synthetic blocks stay bit-identical and a scale changes one row and the hash.
- Visual check: orbit both presets through front, side, and rear with the interior marker on. The marker stays legible, and the camera does not jump. With `NEURO_ENGINE_SYNTHETIC_CHANNEL_SCALES=Cz=4`, the Cz lane and the Cz marker both rise. Restarting the engine shows a stale stream, fading highlights, then recovery, and the waveform shows its restart gap.
- Rollback: revert this ADR's desktop and synthetic-scale changes. Protocol v2, the waveform buffer, and the anatomy assets stay as they were.
