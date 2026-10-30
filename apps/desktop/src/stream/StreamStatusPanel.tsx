import type { EegStreamSnapshot } from './eegStreamClient';

const CONNECTION_LABELS: Record<EegStreamSnapshot['connection'], string> = {
  idle: 'Not started',
  connecting: 'Connecting to neuro-engine…',
  open: 'Connected',
  reconnecting: 'Disconnected — reconnecting',
  incompatible: 'Incompatible engine protocol version',
  stopped: 'Stopped',
};

const HEALTH_LABELS: Record<EegStreamSnapshot['health'], string> = {
  waiting: 'Waiting for data',
  live: 'Live',
  stale: 'Stale — no new samples',
};

function provenanceLabel(snapshot: EegStreamSnapshot): string {
  const provenance = snapshot.metadata?.provenance;
  if (!provenance) {
    return 'Unknown';
  }
  return provenance.kind === 'synthetic'
    ? `Synthetic signal — generated, not measured from a person (seed ${provenance.seed})`
    : 'Device measurement (scalp EEG)';
}

export function StreamStatusPanel({ snapshot }: { snapshot: EegStreamSnapshot }) {
  const { metadata, engineStatus, integrity, lastBlock } = snapshot;
  const channels = metadata?.channels ?? [];
  const references = [...new Set(channels.map((c) => c.reference))].join(', ');
  const rate = engineStatus?.counters.effectiveSampleRateHz;

  return (
    <section aria-label="EEG stream status">
      <p role="status" aria-live="polite">
        EEG stream: {CONNECTION_LABELS[snapshot.connection]}
        {snapshot.connection === 'reconnecting' ? ` (attempt ${snapshot.reconnectAttempt})` : ''}
        {' · '}
        {HEALTH_LABELS[snapshot.health]}
      </p>
      <dl>
        <dt>Source</dt>
        <dd data-testid="provenance">{provenanceLabel(snapshot)}</dd>
        <dt>Device</dt>
        <dd>{metadata ? `${metadata.device.model} (${metadata.device.kind})` : '—'}</dd>
        <dt>Channels</dt>
        <dd>
          {metadata
            ? `${channels.length} × ${channels[0]?.unit === 'uV' ? 'µV' : channels[0]?.unit}, ` +
              `reference ${references}, ${metadata.layout}`
            : '—'}
        </dd>
        <dt>Sampling</dt>
        <dd>
          {metadata ? `${metadata.nominalSampleRateHz} Hz nominal` : '—'}
          {rate != null ? `, ${rate.toFixed(2)} Hz measured by engine` : ''}
        </dd>
        <dt>Engine acquisition</dt>
        <dd>{engineStatus ? engineStatus.state : '—'}</dd>
        <dt>Latest sample index</dt>
        <dd>{lastBlock ? lastBlock.firstSampleIndex + lastBlock.sampleCount - 1 : '—'}</dd>
        <dt>Data integrity</dt>
        <dd data-testid="integrity">
          {`acquisition gaps ${integrity.acquisitionGapSamples} samples; ` +
            `dropped in transport ${integrity.transportDroppedBlocks} blocks; ` +
            `duplicate/out-of-order ${integrity.duplicateBlocks + integrity.outOfOrderBlocks}; ` +
            `invalid messages ${snapshot.invalidMessages}`}
        </dd>
      </dl>
      {snapshot.lastProtocolError ? (
        <p role="alert">
          Last rejected message ({snapshot.lastProtocolError.kind}): {snapshot.lastProtocolError.detail}
        </p>
      ) : null}
    </section>
  );
}
