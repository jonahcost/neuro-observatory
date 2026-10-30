# Neurophysiology interpretation and validation

- **Three tiers:** raw scalp potential measurements; derived EEG features/source estimates; model-produced states. Represent each separately in code and UI.
- Validate scale units (prefer µV at consumer interfaces, convert deliberately in MNE), reference montage, electrode positions, sample timing, line frequency, aliases, filtering, clipping and artifact sources.
- Source localization requires subject MRI, head model, digitized/aligned electrodes, valid forward model and inverse regularization. Low-density EEG has severe spatial limitations; do not paint a detailed anatomy with fictitious spatial precision.
- A T1-weighted structural MRI contains anatomy, not continuous functional data. A 3D external head scan for custom helmet fit is a separate process.
- Use real device counters/timestamps when available; receipt timestamps are not acquisition timestamps. Annotate gaps and drift.
- Frequency features are estimated over temporal windows, so update rates are not independent evidence at each screen frame.
- Experimental model predictions need documented task labels, split by independent session, baseline, leakage avoidance, uncertainty, and quality gating. Do not infer arbitrary thoughts, diagnose health conditions, or claim clinical accuracy.
- Keep processing/model/calibration versions alongside each session; do not alter raw recordings in place.
