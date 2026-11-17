import { useEffect, useRef, useSyncExternalStore } from 'react';
import { ACCENT_VIOLET } from '../theme';
import type { EegStreamSnapshot } from './eegStreamClient';
import { CONNECTION_LABELS, HEALTH_LABELS } from './StreamStatusPanel';
import { LANE_HALF_RANGE_UV, TIME_AXIS_PX, WINDOW_SECONDS, type RestartCause, type WaveformBuffer } from './waveformBuffer';
import styles from './WaveformView.module.css';

function unitLabel(unit: string): string {
  return unit === 'uV' ? 'µV' : unit;
}

function restartNote(cause: RestartCause | null): string {
  if (cause === 'new-stream') {
    return ' Engine clock restarted (new stream). The gap is the observed outage; the new source timestamps were not joined to the previous clock.';
  }
  if (cause === 'source-clock') {
    return ' Source clock moved backwards on this stream. The gap is the observed separation between those clocks.';
  }
  return '';
}

export function WaveformView({
  buffer,
  snapshot,
  selectedChannel = null,
  onSelectChannel,
}: {
  buffer: WaveformBuffer;
  snapshot: EegStreamSnapshot;
  selectedChannel?: string | null;
  onSelectChannel?: (label: string | null) => void;
}) {
  const chrome = useSyncExternalStore(buffer.subscribe, buffer.getChrome);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const emphasisRef = useRef<{ index: number; color: string } | null>(null);
  const layoutEpochRef = useRef(chrome.layoutEpoch);
  const labels = chrome.labels;
  const selectedIndex = selectedChannel === null ? -1 : labels.indexOf(selectedChannel);
  emphasisRef.current = selectedIndex < 0 ? null : { index: selectedIndex, color: ACCENT_VIOLET };

  useEffect(() => {
    const epochChanged = layoutEpochRef.current !== chrome.layoutEpoch;
    layoutEpochRef.current = chrome.layoutEpoch;
    if (!onSelectChannel || selectedChannel === null) {
      return;
    }
    if (epochChanged || !labels.includes(selectedChannel)) {
      onSelectChannel(null);
    }
  }, [chrome.layoutEpoch, labels, onSelectChannel, selectedChannel]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    let frame = 0;
    let stopped = false;
    const draw = () => {
      if (stopped) {
        return;
      }
      const cssWidth = canvas.clientWidth;
      const cssHeight = canvas.clientHeight;
      const dpr = window.devicePixelRatio || 1;
      if (cssWidth > 0 && cssHeight > 0) {
        const backingWidth = Math.max(1, Math.round(cssWidth * dpr));
        const backingHeight = Math.max(1, Math.round(cssHeight * dpr));
        if (canvas.width !== backingWidth || canvas.height !== backingHeight) {
          canvas.width = backingWidth;
          canvas.height = backingHeight;
        }
        const context = canvas.getContext('2d');
        if (context) {
          context.setTransform(dpr, 0, 0, dpr, 0, 0);
          context.clearRect(0, 0, cssWidth, cssHeight);
          buffer.paint(context, cssWidth, cssHeight, emphasisRef.current);
        }
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
    };
  }, [buffer]);

  const shownUnit = unitLabel(chrome.unit);
  const clockNote = restartNote(chrome.restartCause).trim();
  const syntheticNote = chrome.synthetic ? 'Synthetic signal — generated, not measured from a person.' : '';

  return (
    <section id="signals" className={styles.figure} aria-label="EEG waveforms">
      <div className={styles.bar}>
        <h2 className={styles.heading}>EEG Waveforms</h2>
        <p className={styles.scale}>
          {WINDOW_SECONDS} s window · ±{LANE_HALF_RANGE_UV} {shownUnit}
        </p>
      </div>
      <p role="status" aria-live="polite" className={styles.note}>
        {CONNECTION_LABELS[snapshot.connection]}
        {snapshot.connection === 'reconnecting' ? ` (attempt ${snapshot.reconnectAttempt})` : ''}
        {' · '}
        {HEALTH_LABELS[snapshot.health]}
      </p>
      {syntheticNote || clockNote ? (
        <p className={styles.note}>
          {syntheticNote}
          {syntheticNote && clockNote ? ' ' : ''}
          {clockNote}
        </p>
      ) : null}
      {labels.length === 0 ? <p className={styles.note}>Waiting for EEG samples.</p> : null}
      <details className={styles.notes}>
        <summary>Trace notes</summary>
        <p className={styles.note}>
          {labels.length > 0
            ? `${labels.length} channels · ±${LANE_HALF_RANGE_UV} ${shownUnit} · ${WINDOW_SECONDS} s window at ${chrome.rateHz} Hz nominal. Time is seconds before the newest sample, using the stream's nominal sample spacing.`
            : 'Waiting for channel layout.'}
        </p>
      </details>
      {chrome.error ? <p role="alert">{chrome.error}</p> : null}
      <div className={styles.plot}>
        <ol
          className={styles.labels}
          style={{
            gridTemplateRows: labels.length > 0 ? `repeat(${labels.length}, 1fr) ${TIME_AXIS_PX}px` : '1fr',
          }}
        >
          {labels.map((label, index) => (
            <li key={`${index}-${label}`}>
              <button
                type="button"
                className={styles.channel}
                aria-pressed={selectedChannel === label}
                onClick={() => onSelectChannel?.(label)}
              >
                {label}
              </button>
            </li>
          ))}
          {labels.length > 0 ? <li aria-hidden="true" /> : null}
        </ol>
        <div className={styles.canvasSlot}>
          <canvas ref={canvasRef} aria-hidden="true" data-testid="eeg-waveform-canvas" className={styles.canvas} />
        </div>
      </div>
    </section>
  );
}
