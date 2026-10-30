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
export {
  StreamIntegrityTracker,
  emptyIntegrityCounters,
  sampleTimeUs,
  type BlockVerdict,
  type IntegrityCounters,
  type MetadataVerdict,
} from './integrity';
