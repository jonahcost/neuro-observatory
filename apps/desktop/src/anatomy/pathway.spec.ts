import { describe, expect, it } from 'vitest';
import { buildPathwayFrame } from './pathway';

describe('pathway frame', () => {
  it('copies electrode positions and the current display intensities', () => {
    const cz: [number, number, number] = [1, 2, 3];
    const frame = buildPathwayFrame(
      1200,
      true,
      [
        { label: 'Cz', positionRasMm: cz },
        { label: 'Fp1', positionRasMm: [4, 5, 6] },
      ],
      new Map([
        ['Cz', 0.8],
        ['Fp1', 0.1],
      ]),
    );
    frame.endpoints[0]?.positionRasMm.splice(0, 3, 9, 9, 9);
    expect(cz).toEqual([1, 2, 3]);
    expect(frame.timeMs).toBe(1200);
    expect(frame.stale).toBe(true);
    expect(frame.endpoints).toEqual([
      { label: 'Cz', positionRasMm: [9, 9, 9], intensity: 0.8 },
      { label: 'Fp1', positionRasMm: [4, 5, 6], intensity: 0.1 },
    ]);
  });
});
