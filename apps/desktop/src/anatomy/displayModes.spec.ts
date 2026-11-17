import { describe, expect, it } from 'vitest';
import { displayModeFor, modeAvailable, modeFrom } from './displayModes';

describe('display modes', () => {
  it('maps the five picker modes onto the existing surface and preset', () => {
    expect(displayModeFor('pial')).toEqual({ surfaceKind: 'pial', preset: 'solid' });
    expect(displayModeFor('white')).toEqual({ surfaceKind: 'white', preset: 'solid' });
    expect(displayModeFor('inflated')).toEqual({ surfaceKind: 'inflated', preset: 'solid' });
    expect(displayModeFor('holographic')).toEqual({ surfaceKind: 'pial', preset: 'holographic' });
    expect(displayModeFor('grid')).toEqual({ surfaceKind: 'pial', preset: 'grid' });
  });

  it('checks the wireframe radio even when the surface has not caught up', () => {
    expect(modeFrom('pial', 'solid')).toBe('pial');
    expect(modeFrom('white', 'solid')).toBe('white');
    expect(modeFrom('inflated', 'solid')).toBe('inflated');
    expect(modeFrom('white', 'holographic')).toBe('holographic');
    expect(modeFrom('inflated', 'grid')).toBe('grid');
  });

  it('disables a mode whose surface is missing', () => {
    const kinds = ['pial', 'inflated'] as const;
    expect(modeAvailable('pial', kinds)).toBe(true);
    expect(modeAvailable('inflated', kinds)).toBe(true);
    expect(modeAvailable('holographic', kinds)).toBe(true);
    expect(modeAvailable('grid', kinds)).toBe(true);
    expect(modeAvailable('white', kinds)).toBe(false);
    expect(modeAvailable('pial', [])).toBe(false);
  });
});
