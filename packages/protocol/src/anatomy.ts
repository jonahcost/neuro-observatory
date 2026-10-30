import Ajv2020 from 'ajv/dist/2020';
import type { ErrorObject } from 'ajv';
import schema from '../schemas/anatomy-asset.v1.schema.json';
import type {
  AnatomyAsset,
  AnatomyCatalog,
  AnatomyDocument,
  Parcellation,
  SurfaceMesh,
} from './generated/anatomy-asset.v1';
import type { ParseError, ParseErrorKind } from './validate';

export const ANATOMY_SCHEMA_VERSION = 1 as const;

/** Float32 positions may differ from the float64 bounds by rounding; mm. */
const BOUNDS_TOLERANCE_MM = 1e-3;

export type AnatomyParseResult<T extends AnatomyDocument = AnatomyDocument> =
  | { ok: true; document: T }
  | { ok: false; error: ParseError };

const ajv = new Ajv2020({ allErrors: false, strict: true, strictNumbers: false, allowUnionTypes: true });
const schemaValidator = ajv.compile<AnatomyDocument>(schema);

function fail(kind: ParseErrorKind, detail: string): { ok: false; error: ParseError } {
  return { ok: false, error: { kind, detail } };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function describeSchemaError(errors: ErrorObject[] | null | undefined): string {
  const first = errors?.[0];
  if (!first) {
    return 'document does not match the anatomy schema';
  }
  return `${first.instancePath || '/'} ${first.message ?? 'is invalid'}`;
}

function allFinite(values: readonly number[]): boolean {
  return values.every((v) => Number.isFinite(v));
}

function surfaceIssue(surface: SurfaceMesh, path: string): string | null {
  if (surface.positions.dtype !== 'float32') {
    return `${path}/positions/dtype must be float32`;
  }
  if (surface.indices.dtype !== 'uint32') {
    return `${path}/indices/dtype must be uint32`;
  }
  if (surface.positions.byteLength !== surface.vertexCount * 12) {
    return `${path}/positions/byteLength must be 12 * vertexCount`;
  }
  if (surface.indices.byteLength !== surface.triangleCount * 12) {
    return `${path}/indices/byteLength must be 12 * triangleCount`;
  }
  const { min, max } = surface.boundsMm;
  if (!allFinite(min) || !allFinite(max)) {
    return `${path}/boundsMm must be finite`;
  }
  if (min.some((v, axis) => v > (max[axis] as number))) {
    return `${path}/boundsMm/min must not exceed max`;
  }
  return null;
}

function parcellationIssue(parcellation: Parcellation, path: string, vertexCounts: Map<string, number>): string | null {
  if (parcellation.vertexLabels.dtype !== 'int32') {
    return `${path}/vertexLabels/dtype must be int32`;
  }
  if (parcellation.vertexLabels.byteLength !== parcellation.vertexCount * 4) {
    return `${path}/vertexLabels/byteLength must be 4 * vertexCount`;
  }
  const surfaceCount = vertexCounts.get(parcellation.hemisphere);
  if (surfaceCount === undefined) {
    return `${path} labels hemisphere ${parcellation.hemisphere}, which has no surface`;
  }
  if (surfaceCount !== parcellation.vertexCount) {
    return `${path}/vertexCount must equal the ${parcellation.hemisphere} surface vertexCount ${surfaceCount}`;
  }
  const indices = new Set<number>();
  for (const [position, label] of parcellation.labels.entries()) {
    if (indices.has(label.index)) {
      return `${path}/labels/${position}/index duplicates an earlier label`;
    }
    indices.add(label.index);
  }
  return null;
}

function assetIssue(asset: AnatomyAsset): string | null {
  const files = new Set<string>();
  const claim = (file: string, path: string): string | null => {
    if (files.has(file)) {
      return `${path} reuses file ${file}`;
    }
    files.add(file);
    return null;
  };
  const seen = new Set<string>();
  const vertexCounts = new Map<string, number>();
  for (const [position, surface] of asset.surfaces.entries()) {
    const path = `/surfaces/${position}`;
    const key = `${surface.hemisphere}.${surface.surface}`;
    if (seen.has(key)) {
      return `${path} duplicates ${key}`;
    }
    seen.add(key);
    const known = vertexCounts.get(surface.hemisphere);
    if (known !== undefined && known !== surface.vertexCount) {
      return `${path}/vertexCount differs from another ${surface.hemisphere} surface (vertices must correspond)`;
    }
    vertexCounts.set(surface.hemisphere, surface.vertexCount);
    const issue =
      surfaceIssue(surface, path) ??
      claim(surface.positions.file, `${path}/positions`) ??
      claim(surface.indices.file, `${path}/indices`);
    if (issue) {
      return issue;
    }
  }
  const atlases = new Set<string>();
  for (const [position, parcellation] of asset.parcellations.entries()) {
    const path = `/parcellations/${position}`;
    const key = `${parcellation.hemisphere}.${parcellation.atlas}`;
    if (atlases.has(key)) {
      return `${path} duplicates ${key}`;
    }
    atlases.add(key);
    const issue =
      parcellationIssue(parcellation, path, vertexCounts) ?? claim(parcellation.vertexLabels.file, `${path}/vertexLabels`);
    if (issue) {
      return issue;
    }
  }
  for (const [position, transform] of asset.transforms.entries()) {
    const path = `/transforms/${position}`;
    if (transform.from !== asset.coordinateFrame) {
      return `${path}/from must be the asset coordinateFrame`;
    }
    if (transform.to === transform.from) {
      return `${path}/to must differ from from`;
    }
    if (!allFinite(transform.matrix)) {
      return `${path}/matrix must be finite`;
    }
    const [a, b, c, d] = transform.matrix.slice(12);
    if (a !== 0 || b !== 0 || c !== 0 || d !== 1) {
      return `${path}/matrix last row must be [0, 0, 0, 1]`;
    }
  }
  return null;
}

function catalogIssue(catalog: AnatomyCatalog): string | null {
  const ids = new Set<string>();
  for (const [position, summary] of catalog.assets.entries()) {
    if (ids.has(summary.assetId)) {
      return `/assets/${position}/assetId duplicates an earlier asset`;
    }
    ids.add(summary.assetId);
    if (new Set(summary.surfaces).size !== summary.surfaces.length) {
      return `/assets/${position}/surfaces contains duplicates`;
    }
  }
  if (catalog.defaultAssetId !== null && !ids.has(catalog.defaultAssetId)) {
    return '/defaultAssetId is not one of the listed assets';
  }
  return null;
}

/** Validate an already-decoded JSON value as an anatomy v1 document. */
export function validateAnatomyDocument(value: unknown): AnatomyParseResult {
  if (
    isRecord(value) &&
    typeof value['schemaVersion'] === 'number' &&
    value['schemaVersion'] !== ANATOMY_SCHEMA_VERSION
  ) {
    return fail(
      'unsupported-version',
      `schemaVersion ${value['schemaVersion']} is not supported (expected ${ANATOMY_SCHEMA_VERSION})`,
    );
  }
  if (!schemaValidator(value)) {
    return fail('schema', describeSchemaError(schemaValidator.errors));
  }
  const issue = value.type === 'anatomy.asset' ? assetIssue(value) : catalogIssue(value);
  if (issue) {
    return fail('semantic', issue);
  }
  return { ok: true, document: value };
}

/** Parse and validate raw JSON text as an anatomy v1 document. Never throws. */
export function parseAnatomyDocument(raw: string): AnatomyParseResult {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return fail('json', 'document is not valid JSON');
  }
  return validateAnatomyDocument(value);
}

function expectType<T extends AnatomyDocument>(
  result: AnatomyParseResult,
  type: T['type'],
): AnatomyParseResult<T> {
  if (!result.ok) {
    return result;
  }
  if (result.document.type !== type) {
    return fail('schema', `expected a ${type} document, got ${result.document.type}`);
  }
  return { ok: true, document: result.document as T };
}

export function parseAnatomyAsset(raw: string): AnatomyParseResult<AnatomyAsset> {
  return expectType<AnatomyAsset>(parseAnatomyDocument(raw), 'anatomy.asset');
}

export function parseAnatomyCatalog(raw: string): AnatomyParseResult<AnatomyCatalog> {
  return expectType<AnatomyCatalog>(parseAnatomyDocument(raw), 'anatomy.catalog');
}

/**
 * Check decoded surface buffers against their manifest entry: lengths, finite
 * coordinates inside the declared bounds, and triangle indices in range.
 * Returns a description of the first problem, or null.
 */
export function surfaceGeometryIssue(
  surface: SurfaceMesh,
  positions: Float32Array,
  indices: Uint32Array,
): string | null {
  if (positions.length !== surface.vertexCount * 3) {
    return `positions has ${positions.length} values, expected ${surface.vertexCount * 3}`;
  }
  if (indices.length !== surface.triangleCount * 3) {
    return `indices has ${indices.length} values, expected ${surface.triangleCount * 3}`;
  }
  const { min, max } = surface.boundsMm;
  for (let i = 0; i < positions.length; i += 1) {
    const value = positions[i] as number;
    const axis = i % 3;
    if (!Number.isFinite(value)) {
      return `position ${Math.floor(i / 3)} is not finite`;
    }
    if (value < (min[axis] as number) - BOUNDS_TOLERANCE_MM || value > (max[axis] as number) + BOUNDS_TOLERANCE_MM) {
      return `position ${Math.floor(i / 3)} lies outside the declared bounds`;
    }
  }
  for (let i = 0; i < indices.length; i += 1) {
    if ((indices[i] as number) >= surface.vertexCount) {
      return `triangle ${Math.floor(i / 3)} references a vertex outside 0..${surface.vertexCount - 1}`;
    }
  }
  return null;
}

/** Check decoded parcellation labels: one per vertex, each a declared label index or -1. */
export function vertexLabelsIssue(parcellation: Parcellation, labels: Int32Array): string | null {
  if (labels.length !== parcellation.vertexCount) {
    return `vertexLabels has ${labels.length} values, expected ${parcellation.vertexCount}`;
  }
  const known = new Set(parcellation.labels.map((label) => label.index));
  for (let i = 0; i < labels.length; i += 1) {
    const label = labels[i] as number;
    if (label !== -1 && !known.has(label)) {
      return `vertex ${i} has undeclared label ${label}`;
    }
  }
  return null;
}
