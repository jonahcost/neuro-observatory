import type { EegStreamSnapshot } from './eegStreamClient';
import styles from './StreamStatusPanel.module.css';

export const CONNECTION_LABELS: Record<EegStreamSnapshot['connection'], string> = {
  idle: 'Not started',
  connecting: 'Connecting to neuro-engine…',
  open: 'Connected',
  reconnecting: 'Disconnected — reconnecting',
  incompatible: 'Incompatible engine protocol version',
  stopped: 'Stopped',
};

export const HEALTH_LABELS: Record<EegStreamSnapshot['health'], string> = {
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
    <section className={styles.panel} aria-label="EEG stream status">
      <div className={styles.summary}>
        <p className={styles.item}>
          <span className={styles.kicker}>Source</span>
          <span data-testid="provenance">{provenanceLabel(snapshot)}</span>
        </p>
        <p className={styles.item} role="status" aria-live="polite">
          <span className={styles.kicker}>Connection</span>
          {CONNECTION_LABELS[snapshot.connection]}
          {snapshot.connection === 'reconnecting' ? ` (attempt ${snapshot.reconnectAttempt})` : ''}
          {' · '}
          {HEALTH_LABELS[snapshot.health]}
        </p>
      </div>
      <details className={styles.details}>
        <summary>Stream details</summary>
        <dl>
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
              `invalid messages ${snapshot.invalidMessages}; ` +
              `sample consumer errors ${snapshot.listenerErrors}`}
          </dd>
        </dl>
      </details>
      {snapshot.lastProtocolError ? (
        <p role="alert">
          Last rejected message ({snapshot.lastProtocolError.kind}): {snapshot.lastProtocolError.detail}
        </p>
      ) : null}
    </section>
  );
}
