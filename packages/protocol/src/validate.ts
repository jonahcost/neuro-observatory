import Ajv2020 from 'ajv/dist/2020';
import type { ErrorObject } from 'ajv';
import schema from '../schemas/eeg-stream.v2.schema.json';
import type {
  EegBlock,
  ServerMessage,
  StreamMetadata,
} from './generated/eeg-stream.v2';

export const PROTOCOL_SCHEMA_VERSION = 2 as const;

/**
 * - `json`: not parseable JSON.
 * - `schema`: violates the canonical JSON Schema.
 * - `unsupported-version`: declares a `schemaVersion` this build does not speak.
 * - `semantic`: schema-valid but violates rules JSON Schema cannot express.
 */
export type ParseErrorKind = 'json' | 'schema' | 'unsupported-version' | 'semantic';

export interface ParseError {
  kind: ParseErrorKind;
  detail: string;
}

export type ParseResult =
  | { ok: true; message: ServerMessage }
  | { ok: false; error: ParseError };

export interface ParseContext {
  /** Metadata of the active stream; enables block-vs-stream checks. */
  metadata?: StreamMetadata | null;
}

// strictNumbers is off so that non-finite numbers are reported by the semantic
// layer, matching the Python implementation (JSON Schema validators disagree on them).
const ajv = new Ajv2020({ allErrors: false, strict: true, strictNumbers: false, allowUnionTypes: true });
const schemaValidator = ajv.compile<ServerMessage>(schema);

function fail(kind: ParseErrorKind, detail: string): ParseResult {
  return { ok: false, error: { kind, detail } };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function describeSchemaError(errors: ErrorObject[] | null | undefined): string {
  const first = errors?.[0];
  if (!first) {
    return 'message does not match the protocol schema';
  }
  // Report location and rule only; never echo sample values.
  return `${first.instancePath || '/'} ${first.message ?? 'is invalid'}`;
}

function metadataIssue(metadata: StreamMetadata): string | null {
  const labels = new Set<string>();
  for (const [position, channel] of metadata.channels.entries()) {
    if (channel.index !== position) {
      return `/channels/${position}/index must equal its position ${position}`;
    }
    if (labels.has(channel.label)) {
      return `/channels/${position}/label duplicates an earlier channel label`;
    }
    labels.add(channel.label);
  }
  return null;
}

function blockIssue(block: EegBlock, metadata: StreamMetadata | null | undefined): string | null {
  for (const [channel, row] of block.samples.entries()) {
    if (row.length !== block.sampleCount) {
      return `/samples/${channel} has ${row.length} samples but sampleCount is ${block.sampleCount}`;
    }
    for (const [sample, value] of row.entries()) {
      if (!Number.isFinite(value)) {
        return `/samples/${channel}/${sample} is not a finite number`;
      }
    }
  }
  if (metadata) {
    if (block.streamId !== metadata.streamId) {
      return `block belongs to stream ${block.streamId}, active stream is ${metadata.streamId}`;
    }
    if (block.samples.length !== metadata.channels.length) {
      return `/samples has ${block.samples.length} channels but metadata declares ${metadata.channels.length}`;
    }
  }
  return null;
}

/** Validate an already-decoded JSON value as a protocol v2 server message. */
export function validateServerMessage(value: unknown, context: ParseContext = {}): ParseResult {
  if (isRecord(value) && typeof value['schemaVersion'] === 'number' && value['schemaVersion'] !== PROTOCOL_SCHEMA_VERSION) {
    return fail(
      'unsupported-version',
      `schemaVersion ${value['schemaVersion']} is not supported (expected ${PROTOCOL_SCHEMA_VERSION})`,
    );
  }
  if (!schemaValidator(value)) {
    return fail('schema', describeSchemaError(schemaValidator.errors));
  }
  const issue =
    value.type === 'stream.metadata'
      ? metadataIssue(value)
      : value.type === 'eeg.block'
        ? blockIssue(value, context.metadata)
        : null;
  if (issue) {
    return fail('semantic', issue);
  }
  return { ok: true, message: value };
}

/** Parse and validate raw WebSocket text. Never throws. */
export function parseServerMessage(raw: string, context: ParseContext = {}): ParseResult {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return fail('json', 'message is not valid JSON');
  }
  return validateServerMessage(value, context);
}
