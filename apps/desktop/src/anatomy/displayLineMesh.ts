export interface LineMesh {
  positions: Float32Array;
  indices: Uint32Array;
  /** Mean linear RGB of `vertexColors` in each cluster, when those colours were supplied. */
  colors?: Float32Array;
}

export interface EdgeStats {
  uniqueEdges: number;
  /** Lower median of unique edge lengths, in the same units as `positions`. */
  medianMm: number;
}

/**
 * Display-only line mesh. Vertex clustering in surface RAS. The source
 * arrays are read and never rewritten. The result is not a FreeSurfer
 * source space and has no vertex map back to the asset.
 */
export function simplifyLineMesh(
  positions: Float32Array,
  indices: Uint32Array,
  cellMm: number,
  vertexColors?: Float32Array,
): LineMesh {
  if (!Number.isFinite(cellMm) || cellMm <= 0) {
    throw new Error('cellMm must be a positive finite number');
  }
  const vertexCount = positions.length / 3;
  if (vertexColors !== undefined && vertexColors.length !== positions.length) {
    throw new Error('vertexColors must match positions');
  }
  if (vertexCount < 3 || indices.length < 3) {
    return { positions: new Float32Array(0), indices: new Uint32Array(0) };
  }

  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  for (let i = 0; i < positions.length; i += 3) {
    const x = positions[i] as number;
    const y = positions[i + 1] as number;
    const z = positions[i + 2] as number;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (z < minZ) minZ = z;
  }

  const cellOf = new Int32Array(vertexCount);
  const buckets = new Map<string, { sx: number; sy: number; sz: number; sr: number; sg: number; sb: number; n: number; index: number }>();
  for (let vertex = 0; vertex < vertexCount; vertex += 1) {
    const x = positions[vertex * 3] as number;
    const y = positions[vertex * 3 + 1] as number;
    const z = positions[vertex * 3 + 2] as number;
    const key = `${Math.floor((x - minX) / cellMm)}:${Math.floor((y - minY) / cellMm)}:${Math.floor((z - minZ) / cellMm)}`;
    let bucket = buckets.get(key);
    if (bucket === undefined) {
      bucket = { sx: 0, sy: 0, sz: 0, sr: 0, sg: 0, sb: 0, n: 0, index: buckets.size };
      buckets.set(key, bucket);
    }
    bucket.sx += x;
    bucket.sy += y;
    bucket.sz += z;
    if (vertexColors !== undefined) {
      bucket.sr += vertexColors[vertex * 3] as number;
      bucket.sg += vertexColors[vertex * 3 + 1] as number;
      bucket.sb += vertexColors[vertex * 3 + 2] as number;
    }
    bucket.n += 1;
    cellOf[vertex] = bucket.index;
  }

  const clustered = new Float32Array(buckets.size * 3);
  const colors = vertexColors === undefined ? undefined : new Float32Array(buckets.size * 3);
  for (const bucket of buckets.values()) {
    clustered[bucket.index * 3] = bucket.sx / bucket.n;
    clustered[bucket.index * 3 + 1] = bucket.sy / bucket.n;
    clustered[bucket.index * 3 + 2] = bucket.sz / bucket.n;
    if (colors !== undefined) {
      colors[bucket.index * 3] = bucket.sr / bucket.n;
      colors[bucket.index * 3 + 1] = bucket.sg / bucket.n;
      colors[bucket.index * 3 + 2] = bucket.sb / bucket.n;
    }
  }

  const seen = new Set<string>();
  const triangles: number[] = [];
  for (let t = 0; t < indices.length; t += 3) {
    const a = cellOf[indices[t] as number] as number;
    const b = cellOf[indices[t + 1] as number] as number;
    const c = cellOf[indices[t + 2] as number] as number;
    if (a === b || b === c || a === c) {
      continue;
    }
    const ordered = [a, b, c].sort((p, q) => p - q);
    const key = `${ordered[0]}:${ordered[1]}:${ordered[2]}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    triangles.push(a, b, c);
  }
  return { positions: clustered, indices: new Uint32Array(triangles), ...(colors === undefined ? {} : { colors }) };
}

/** Unique undirected edges and their lower-median length. */
export function meshEdgeStats(positions: Float32Array, indices: Uint32Array): EdgeStats {
  const vertexCount = positions.length / 3;
  const seen = new Set<number>();
  const lengths: number[] = [];
  const consider = (i: number, j: number) => {
    if (i === j || i < 0 || j < 0 || i >= vertexCount || j >= vertexCount) {
      return;
    }
    const lo = i < j ? i : j;
    const hi = i < j ? j : i;
    const key = lo * vertexCount + hi;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    const ax = positions[lo * 3] as number;
    const ay = positions[lo * 3 + 1] as number;
    const az = positions[lo * 3 + 2] as number;
    const bx = positions[hi * 3] as number;
    const by = positions[hi * 3 + 1] as number;
    const bz = positions[hi * 3 + 2] as number;
    lengths.push(Math.hypot(ax - bx, ay - by, az - bz));
  };
  for (let t = 0; t < indices.length; t += 3) {
    const a = indices[t] as number;
    const b = indices[t + 1] as number;
    const c = indices[t + 2] as number;
    consider(a, b);
    consider(b, c);
    consider(c, a);
  }
  if (lengths.length === 0) {
    return { uniqueEdges: 0, medianMm: 0 };
  }
  lengths.sort((p, q) => p - q);
  return { uniqueEdges: lengths.length, medianMm: lengths[(lengths.length - 1) >> 1] as number };
}
