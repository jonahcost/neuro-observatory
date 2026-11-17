import { describe, expect, it } from 'vitest';
import { ACCENT_VIOLET, ELECTRODE_MARKER_COLOR, markerColor } from './theme';

describe('marker color', () => {
  it('uses violet for the selected label and the electrode color for the rest', () => {
    expect(markerColor('Cz', 'Cz')).toBe(ACCENT_VIOLET);
    expect(markerColor('Fp1', 'Cz')).toBe(ELECTRODE_MARKER_COLOR);
    expect(markerColor('Cz', null)).toBe(ELECTRODE_MARKER_COLOR);
  });
});
