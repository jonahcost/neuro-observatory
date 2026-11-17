import { describe, expect, it } from 'vitest';
import { SYNTHETIC_CHANNEL_LABELS, TEMPLATE_1020_UNIT, templateDirection, unmappedTemplateLabels } from './template1020';

describe('template 10-20 display directions', () => {
  it('has one finite unit vector for every synthetic label', () => {
    expect(Object.keys(TEMPLATE_1020_UNIT).sort()).toEqual([...SYNTHETIC_CHANNEL_LABELS].sort());
    for (const label of SYNTHETIC_CHANNEL_LABELS) {
      const direction = templateDirection(label);
      expect(direction).not.toBeNull();
      const [x, y, z] = direction as [number, number, number];
      expect(Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)).toBe(true);
      expect(Math.hypot(x, y, z)).toBeCloseTo(1, 4);
    }
  });

  it('reports labels that are not in the display table', () => {
    expect(unmappedTemplateLabels(['Cz', 'EOG1', 'Fp1'])).toEqual(['EOG1']);
    expect(templateDirection('EOG1')).toBeNull();
  });
});
