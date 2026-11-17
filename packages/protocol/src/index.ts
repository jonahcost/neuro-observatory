export type {
  ChannelSpec,
  ClockAnchor,
  DeviceInfo,
  DeviceProvenance,
  EegBlock,
  ServerMessage,
  StreamCounters,
  StreamError,
  StreamMetadata,
  StreamStatus,
  SyntheticProvenance,
  Timebase,
} from './generated/eeg-stream.v2';
export {
  PROTOCOL_SCHEMA_VERSION,
  parseServerMessage,
  validateServerMessage,
  type ParseContext,
  type ParseError,
  type ParseErrorKind,
  type ParseResult,
} from './validate';
export type {
  AnatomyAsset,
  AnatomyCatalog,
  AnatomyDocument,
  AnatomyKind,
  AssetSummary,
  BufferRef,
  CoordinateFrame,
  CoordinateTransform,
  DataLicense,
  Hemisphere,
  MriAcquisition,
  Parcellation,
  ParcellationLabel,
  SubjectRef,
  SurfaceKind,
  SurfaceMesh,
} from './generated/anatomy-asset.v1';
export {
  ANATOMY_SCHEMA_VERSION,
  parseAnatomyAsset,
  parseAnatomyCatalog,
  parseAnatomyDocument,
  surfaceGeometryIssue,
  validateAnatomyDocument,
  vertexLabelsIssue,
  type AnatomyParseResult,
} from './anatomy';
export type { AssistantDocument, AssistantSnapshot, Finding, IntentResult, Marker } from './generated/assistant.v1';
export { ASSISTANT_SCHEMA_VERSION, parseAssistantDocument, parseAssistantSnapshot, parseIntentResult, validateAssistantDocument } from './assistant';
export {
  StreamIntegrityTracker,
  emptyIntegrityCounters,
  sampleTimeUs,
  type BlockVerdict,
  type IntegrityCounters,
  type MetadataVerdict,
} from './integrity';
