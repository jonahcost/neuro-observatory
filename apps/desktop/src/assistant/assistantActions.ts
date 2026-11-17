import type { AssistantSnapshot, Finding, IntentResult } from '@neuro-observatory/protocol';
import type { DisplayModeId } from '../anatomy/displayModes';

const POSTERIOR = ['O1', 'O2', 'Pz', 'P3', 'P4'];

export interface TraceHighlight {
  streamId: string;
  first: number;
  last: number;
}

export interface EvidenceSelection {
  primary: string | null;
  channels: string[];
  highlight: TraceHighlight;
  seek: boolean;
}

/** One violet primary, with the rest of the finding's channels emphasized. Replay may seek. */
export function evidenceSelection(snapshot: AssistantSnapshot, finding: Finding): EvidenceSelection {
  const channels = finding.channels.map((channel) => channel.label);
  const primary = POSTERIOR.find((label) => channels.includes(label)) ?? channels[0] ?? null;
  return {
    primary,
    channels,
    highlight: {
      streamId: finding.streamId,
      first: finding.firstSampleIndex,
      last: finding.lastSampleIndex,
    },
    seek:
      snapshot.source === 'replay' &&
      snapshot.recordingId !== null &&
      finding.recordingId === snapshot.recordingId &&
      (finding.quality === 'good' || finding.quality === 'stale'),
  };
}

export interface AppliedIntent {
  primary: string | null;
  channels: string[];
  displayMode: DisplayModeId | null;
  seekSampleIndex: number | null;
  message: string;
}

export function applyIntentResult(result: IntentResult): AppliedIntent {
  const displayMode = result.displayMode;
  return {
    primary: result.primaryChannel,
    channels: result.channels,
    displayMode,
    seekSampleIndex: result.intent === 'seek_to_finding' ? result.seekSampleIndex : null,
    message: result.message,
  };
}
