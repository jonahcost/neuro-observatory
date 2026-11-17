import Ajv2020 from 'ajv/dist/2020';
import type { ErrorObject } from 'ajv';
import schema from '../schemas/assistant.v1.schema.json';
import type { AssistantDocument, AssistantSnapshot, Finding, IntentResult } from './generated/assistant.v1';
import type { ParseError, ParseErrorKind } from './validate';

export const ASSISTANT_SCHEMA_VERSION = 1 as const;

export type AssistantParseResult<T extends AssistantDocument = AssistantDocument> =
  | { ok: true; document: T }
  | { ok: false; error: ParseError };

const ajv = new Ajv2020({ allErrors: false, strict: true, strictNumbers: false, allowUnionTypes: true });
const schemaValidator = ajv.compile<AssistantDocument>(schema);

function fail(kind: ParseErrorKind, detail: string): { ok: false; error: ParseError } {
  return { ok: false, error: { kind, detail } };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function describeSchemaError(errors: ErrorObject[] | null | undefined): string {
  const first = errors?.[0];
  if (!first) {
    return 'document does not match the assistant schema';
  }
  return `${first.instancePath || '/'} ${first.message ?? 'is invalid'}`;
}

function finiteMeasurement(finding: Finding, findingIndex: number): string | null {
  if (finding.lastSampleIndex < finding.firstSampleIndex) {
    return `/findings/${findingIndex}/lastSampleIndex is before firstSampleIndex`;
  }
  if (finding.lastSampleTimeUs < finding.firstSampleTimeUs) {
    return `/findings/${findingIndex}/lastSampleTimeUs is before firstSampleTimeUs`;
  }
  if (!Number.isFinite(finding.nominalSampleRateHz)) {
    return `/findings/${findingIndex}/nominalSampleRateHz is not finite`;
  }
  const labels = new Set<string>();
  for (const [channelIndex, channel] of finding.channels.entries()) {
    if (labels.has(channel.label)) {
      return `/findings/${findingIndex}/channels/${channelIndex}/label duplicates an earlier channel`;
    }
    labels.add(channel.label);
    const numbers = [channel.powerUv2, channel.baselineUv2, channel.changeDb, channel.rmsUv, channel.acceptedSampleFraction];
    if (numbers.some((value) => !Number.isFinite(value))) {
      return `/findings/${findingIndex}/channels/${channelIndex} has a non-finite measurement`;
    }
  }
  return null;
}

/** Rules the JSON Schema cannot express. Details name the path and never echo sample arrays. */
export function assistantSemanticIssue(document: AssistantDocument): string | null {
  if (document.type !== 'assistant.snapshot') {
    return null;
  }
  for (const [index, finding] of document.findings.entries()) {
    const issue = finiteMeasurement(finding, index);
    if (issue) {
      return issue;
    }
  }
  return null;
}

export function validateAssistantDocument(value: unknown): AssistantParseResult {
  if (!schemaValidator(value)) {
    return fail('schema', describeSchemaError(schemaValidator.errors));
  }
  const issue = assistantSemanticIssue(value);
  if (issue) {
    return fail('semantic', issue);
  }
  return { ok: true, document: value };
}

export function parseAssistantDocument(raw: string): AssistantParseResult {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return fail('json', 'document is not valid JSON');
  }
  if (isRecord(value) && typeof value.schemaVersion === 'number' && value.schemaVersion !== ASSISTANT_SCHEMA_VERSION) {
    return fail('unsupported-version', `schemaVersion ${value.schemaVersion} is not supported (expected ${ASSISTANT_SCHEMA_VERSION})`);
  }
  return validateAssistantDocument(value);
}

export function parseAssistantSnapshot(raw: string): AssistantParseResult<AssistantSnapshot> {
  const parsed = parseAssistantDocument(raw);
  if (!parsed.ok) {
    return parsed;
  }
  if (parsed.document.type !== 'assistant.snapshot') {
    return fail('schema', '/type must be assistant.snapshot');
  }
  return { ok: true, document: parsed.document };
}

export function parseIntentResult(raw: string): AssistantParseResult<IntentResult> {
  const parsed = parseAssistantDocument(raw);
  if (!parsed.ok) {
    return parsed;
  }
  if (parsed.document.type !== 'assistant.intent-result') {
    return fail('schema', '/type must be assistant.intent-result');
  }
  return { ok: true, document: parsed.document };
}
