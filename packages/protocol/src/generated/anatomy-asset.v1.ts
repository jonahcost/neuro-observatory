/**
 * GENERATED FILE - DO NOT EDIT.
 * Source: packages/protocol/schemas/anatomy-asset.v1.schema.json
 * Regenerate: yarn nx run @neuro-observatory/protocol:generate-types
 */

/**
 * Neuro Observatory anatomy asset contract v1: documents served by the neuro-engine that describe prepared, render-ready cortical geometry. Canonical, language-neutral source of truth (ADR-0010). Geometry is anatomy only; it never carries activity.
 */
export type AnatomyDocument = AnatomyAsset | AnatomyCatalog;
/**
 * Anatomy contract major version. Incremented on any breaking change.
 */
export type AnatomySchemaVersion = 1;
/**
 * Content-addressed identifier of one prepared asset. Equal IDs imply identical sources, options and pipeline version.
 */
export type AssetId = string;
export type AnatomySlug = string;
export type AnatomyText = string;
/**
 * template: population average (e.g. fsaverage). reference-subject: a real, non-user participant from a public dataset. personal: derived from the user's own MRI (restricted data).
 */
export type AnatomyKind = 'template' | 'reference-subject' | 'personal';
/**
 * freesurfer-surface-ras: FreeSurfer 'tkrRAS' surface coordinates (+x right, +y anterior, +z superior). scanner-ras: the volume's world (scanner) RAS. mni305-ras: MNI305 space (equal to surface RAS for fsaverage). All in millimetres.
 */
export type CoordinateFrame = 'freesurfer-surface-ras' | 'scanner-ras' | 'mni305-ras';
/**
 * 4x4 affine matrix, row-major, 16 numbers. The last row must be [0, 0, 0, 1].
 *
 * @minItems 16
 * @maxItems 16
 */
export type Matrix4 = number[];
/**
 * FreeSurfer hemisphere: lh (left) or rh (right).
 */
export type Hemisphere = 'lh' | 'rh';
/**
 * FreeSurfer surface. pial and white are anatomical boundaries; inflated is a smoothed visualisation surface sharing the same vertices.
 */
export type SurfaceKind = 'pial' | 'white' | 'inflated';
/**
 * File name inside the asset directory; never a path.
 */
export type AssetFileName = string;
/**
 * Non-negative integer within the JSON/JavaScript safe-integer range.
 */
export type Count = number;
export type Sha256 = string;
/**
 * @minItems 3
 * @maxItems 3
 */
export type Vec3 = number[];
export type LongText = string;

/**
 * Manifest of one prepared cortical asset. Geometry is in millimetres in FreeSurfer surface RAS, unscaled and uncentred; render precision only (float32).
 */
export interface AnatomyAsset {
  type: 'anatomy.asset';
  schemaVersion: AnatomySchemaVersion;
  assetId: AssetId;
  subject: SubjectRef;
  anatomyKind: AnatomyKind;
  acquisition: MriAcquisition;
  coordinateFrame: 'freesurfer-surface-ras';
  units: 'mm';
  /**
   * Transforms from the asset frame to other frames, when known.
   *
   * @maxItems 8
   */
  transforms: CoordinateTransform[];
  /**
   * @minItems 1
   * @maxItems 6
   */
  surfaces: SurfaceMesh[];
  /**
   * @maxItems 16
   */
  parcellations: Parcellation[];
  provenance: AssetProvenance;
  license: DataLicense;
}
export interface SubjectRef {
  datasetId: AnatomySlug;
  datasetVersion: AnatomyText;
  subjectId: AnatomyText;
  sessionId: AnatomyText | null;
  displayName: AnatomyText;
}
/**
 * Structural MRI acquisition facts, each with where they came from. Unknown values are null, never guessed.
 */
export interface MriAcquisition {
  fieldStrengthTesla: number | null;
  sequence: AnatomyText | null;
  scanner: AnatomyText | null;
  /**
   * Where the values above come from: a BIDS sidecar, the dataset README, the acquisition site's documentation (site-level, not per scan), a user declaration, or not applicable (template).
   */
  source: 'sidecar' | 'dataset-readme' | 'site-documentation' | 'user-declared' | 'not-applicable';
}
export interface CoordinateTransform {
  from: CoordinateFrame;
  to: CoordinateFrame;
  matrix: Matrix4;
  units: 'mm';
  /**
   * How the transform was obtained, e.g. 'surface volume_info c_ras' or 'fsaverage definition'.
   */
  source: string;
}
/**
 * One hemisphere surface. positions: float32[3 * vertexCount] (x, y, z in mm, in the asset's coordinateFrame). indices: uint32[3 * triangleCount], counter-clockwise seen from outside, as stored by FreeSurfer. Vertex order is FreeSurfer's and is shared by every surface of the hemisphere.
 */
export interface SurfaceMesh {
  hemisphere: Hemisphere;
  surface: SurfaceKind;
  vertexCount: number;
  triangleCount: number;
  positions: BufferRef;
  indices: BufferRef;
  boundsMm: Bounds;
}
/**
 * Little-endian binary file in the asset directory.
 */
export interface BufferRef {
  file: AssetFileName;
  dtype: 'float32' | 'uint32' | 'int32';
  byteLength: Count;
  sha256: Sha256;
}
export interface Bounds {
  min: Vec3;
  max: Vec3;
}
/**
 * Anatomical atlas labels per vertex (not activity). vertexLabels: int32[vertexCount], each a label index or -1 for unlabelled.
 */
export interface Parcellation {
  atlas: AnatomySlug;
  description: AnatomyText;
  hemisphere: Hemisphere;
  vertexCount: number;
  /**
   * @minItems 1
   * @maxItems 1000
   */
  labels: ParcellationLabel[];
  vertexLabels: BufferRef;
}
export interface ParcellationLabel {
  index: Count;
  name: AnatomyText;
  /**
   * @minItems 4
   * @maxItems 4
   */
  rgba: number[];
}
export interface AssetProvenance {
  pipeline: 'neuro-engine.anatomy.prepare';
  pipelineVersion: AnatomyText;
  preparedAtUtc: string;
  /**
   * @maxItems 16
   */
  tools: ToolVersion[];
  /**
   * @minItems 1
   * @maxItems 256
   */
  sources: SourceFile[];
}
export interface ToolVersion {
  name: AnatomyText;
  version: AnatomyText;
}
export interface SourceFile {
  /**
   * POSIX path relative to the engine data root (e.g. raw/ds000248/1.2.4/...); never absolute.
   */
  path: string;
  bytes: Count;
  sha256: Sha256;
}
export interface DataLicense {
  id: AnatomyText;
  url: string;
  attribution: LongText;
}
/**
 * Prepared assets available from this engine. defaultAssetId is the asset to show first (the fsaverage template when prepared), or null.
 */
export interface AnatomyCatalog {
  type: 'anatomy.catalog';
  schemaVersion: AnatomySchemaVersion;
  defaultAssetId: AssetId | null;
  /**
   * @maxItems 256
   */
  assets: AssetSummary[];
}
export interface AssetSummary {
  assetId: AssetId;
  subject: SubjectRef;
  anatomyKind: AnatomyKind;
  /**
   * @minItems 1
   * @maxItems 3
   */
  surfaces: SurfaceKind[];
  /**
   * @maxItems 16
   */
  atlases: AnatomySlug[];
  licenseId: AnatomyText;
}
