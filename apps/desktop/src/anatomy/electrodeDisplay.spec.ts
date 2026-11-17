import { describe, expect, it } from 'vitest';
import { placeElectrodes } from './electrodeDisplay';
import { ELECTRODE_CLEARANCE_MM } from './renderPresets';

describe('electrode display placement', () => {
  it('puts mapped labels outside the surface and reports the rest', () => {
    const positions = new Float32Array([10, 0, 0, -10, 0, 0]);
    const layout = placeElectrodes([{ hemisphere: 'lh', positions, offsetMm: 0 }], ['Cz', 'EOG1', 'Fp1']);
    expect(layout.unmapped).toEqual(['EOG1']);
    expect(layout.placed.map((item) => item.label)).toEqual(['Cz', 'Fp1']);
    expect(layout.centreRasMm).toEqual([0, 0, 0]);
    expect(layout.radiusMm).toBeCloseTo(10 + ELECTRODE_CLEARANCE_MM);
    const cz = layout.placed[0]?.positionRasMm;
    expect(cz?.[0]).toBeCloseTo(0);
    expect(cz?.[1]).toBeCloseTo(0);
    expect(cz?.[2]).toBeCloseTo(layout.radiusMm);
    const before = Array.from(positions);
    placeElectrodes([{ hemisphere: 'lh', positions, offsetMm: 4 }], ['T8']);
    expect(Array.from(positions)).toEqual(before);
  });
});
