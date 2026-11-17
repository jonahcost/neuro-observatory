import { describe, expect, it } from 'vitest';
import { meshEdgeStats, simplifyLineMesh } from './displayLineMesh';

/** A V-shaped sheet. The valley floor is z = -20 at x = 0; the rims are z = 0. */
function valleyMesh(): { positions: Float32Array; indices: Uint32Array } {
  const xs: number[] = [];
  const ys: number[] = [];
  for (let x = -24; x <= 24; x += 2) xs.push(x);
  for (let y = 0; y <= 20; y += 2) ys.push(y);
  const positions: number[] = [];
  for (const y of ys) {
    for (const x of xs) {
      positions.push(x, y, -20 * (1 - Math.abs(x) / 24));
    }
  }
  const indices: number[] = [];
  const nx = xs.length;
  for (let j = 0; j < ys.length - 1; j += 1) {
    for (let i = 0; i < nx - 1; i += 1) {
      const a = j * nx + i;
      const b = a + 1;
      const c = a + nx;
      const d = c + 1;
      indices.push(a, c, b, b, c, d);
    }
  }
  return { positions: new Float32Array(positions), indices: new Uint32Array(indices) };
}

describe('display line mesh', () => {
  const valley = valleyMesh();

  it('makes the 16 mm mesh coarser than the 3.5 mm mesh without editing the source', () => {
    const positions = valley.positions.slice();
    const indices = valley.indices.slice();
    const fine = simplifyLineMesh(positions, indices, 3.5);
    const coarse = simplifyLineMesh(positions, indices, 16);
    const fineStats = meshEdgeStats(fine.positions, fine.indices);
    const coarseStats = meshEdgeStats(coarse.positions, coarse.indices);
    expect(coarseStats.uniqueEdges).toBeGreaterThan(0);
    expect(coarseStats.uniqueEdges).toBeLessThan(fineStats.uniqueEdges);
    expect(coarseStats.medianMm).toBeGreaterThan(fineStats.medianMm);
    expect(Array.from(positions)).toEqual(Array.from(valley.positions));
    expect(Array.from(indices)).toEqual(Array.from(valley.indices));
    expect(fine.positions).not.toBe(positions);
  });

  it('keeps the sulcus instead of flattening it onto the convex rim', () => {
    const coarse = simplifyLineMesh(valley.positions, valley.indices, 16);
    let minZ = Infinity;
    let nearest = Infinity;
    for (let i = 0; i < coarse.positions.length; i += 3) {
      const x = coarse.positions[i] as number;
      const y = coarse.positions[i + 1] as number;
      const z = coarse.positions[i + 2] as number;
      minZ = Math.min(minZ, z);
      nearest = Math.min(nearest, Math.hypot(x, y - 10, z + 20));
    }
    expect(minZ).toBeLessThan(-10);
    expect(nearest).toBeLessThan(16);
  });

  it('rejects a non-positive cell size', () => {
    expect(() => simplifyLineMesh(valley.positions, valley.indices, 0)).toThrow(/cellMm/);
  });

  it('averages supplied vertex colours into each cluster and leaves the source arrays alone', () => {
    const positions = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
    const indices = new Uint32Array([0, 1, 2]);
    const colors = new Float32Array([1, 0, 0, 1, 0, 0, 0, 0, 1]);
    const source = colors.slice();
    const mesh = simplifyLineMesh(positions, indices, 10, colors);
    expect(Array.from(colors)).toEqual(Array.from(source));
    expect(mesh.colors).toBeDefined();
    expect(Array.from(mesh.colors ?? [])).toEqual([Math.fround(2 / 3), 0, Math.fround(1 / 3)]);
    expect(() => simplifyLineMesh(positions, indices, 10, new Float32Array(3))).toThrow(/vertexColors/);
  });
});
