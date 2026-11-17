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

function provenanceLabel(snapshot: EegStreamSnapshot): { short: string; full: string } {
  const provenance = snapshot.metadata?.provenance;
  if (!provenance) {
    return { short: 'Unknown', full: 'Unknown' };
  }
  if (provenance.kind === 'synthetic') {
    return {
      short: 'Synthetic EEG',
      full: `Synthetic signal — generated, not measured from a person (seed ${provenance.seed})`,
    };
  }
  if (snapshot.metadata?.device.kind === 'replay') {
    const references = [...new Set((snapshot.metadata.channels ?? []).map((channel) => channel.reference))].join(', ');
    return {
      short: 'Recorded EEG',
      full: `Replay of a recorded file (reference ${references || 'unknown'}). Sample times follow the playback clock, not a live amplifier clock.`,
    };
  }
  return { short: 'Device EEG', full: 'Device measurement (scalp EEG)' };
}

export function StreamStatusPanel({ snapshot }: { snapshot: EegStreamSnapshot }) {
  const provenance = provenanceLabel(snapshot);
  const live = snapshot.connection === 'open' && snapshot.health === 'live';

  return (
    <section className={styles.panel} aria-label="EEG stream status">
      <div className={styles.summary} data-testid="provenance">
        <p className={styles.pill}>
          <span className={live ? styles.dotLive : styles.dot} aria-hidden="true" />
          <span>{provenance.short}</span>
        </p>
        {provenance.full === provenance.short ? null : <p className={styles.detail}>{provenance.full}</p>}
        <p className={styles.connection} role="status" aria-live="polite">
          {CONNECTION_LABELS[snapshot.connection]}
          {snapshot.connection === 'reconnecting' ? ` (attempt ${snapshot.reconnectAttempt})` : ''}
          {' · '}
          {HEALTH_LABELS[snapshot.health]}
        </p>
      </div>
      {snapshot.lastProtocolError ? (
        <p role="alert">
          Last rejected message ({snapshot.lastProtocolError.kind}): {snapshot.lastProtocolError.detail}
        </p>
      ) : null}
    </section>
  );
}

export function StreamDetails({ snapshot }: { snapshot: EegStreamSnapshot }) {
  const { metadata, engineStatus, integrity, lastBlock } = snapshot;
  const channels = metadata?.channels ?? [];
  const references = [...new Set(channels.map((c) => c.reference))].join(', ');
  const rate = engineStatus?.counters.effectiveSampleRateHz;

  return (
    <section className={styles.card} aria-label="Stream details">
      <h2 className={styles.cardTitle}>Stream details</h2>
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
    </section>
  );
}
