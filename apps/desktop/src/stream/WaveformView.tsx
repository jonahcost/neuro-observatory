import { useEffect, useRef, useSyncExternalStore } from 'react';
import type { EegStreamSnapshot } from './eegStreamClient';
import { CONNECTION_LABELS, HEALTH_LABELS } from './StreamStatusPanel';
import { LANE_HALF_RANGE_UV, TIME_AXIS_PX, WINDOW_SECONDS, type RestartCause, type WaveformBuffer } from './waveformBuffer';

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

export function WaveformView({ buffer, snapshot }: { buffer: WaveformBuffer; snapshot: EegStreamSnapshot }) {
  const chrome = useSyncExternalStore(buffer.subscribe, buffer.getChrome);
  const canvasRef = useRef<HTMLCanvasElement>(null);

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
          buffer.paint(context, cssWidth, cssHeight);
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

  const labels = chrome.labels;
  const shownUnit = unitLabel(chrome.unit);
  const clockNote = restartNote(chrome.restartCause);

  return (
    <section aria-label="EEG waveforms" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 8px' }}>Live EEG</h2>
      <p role="status" aria-live="polite" style={{ margin: '0 0 8px' }}>
        {CONNECTION_LABELS[snapshot.connection]}
        {snapshot.connection === 'reconnecting' ? ` (attempt ${snapshot.reconnectAttempt})` : ''}
        {' · '}
        {HEALTH_LABELS[snapshot.health]}
      </p>
      <p style={{ margin: '0 0 8px', color: '#cbd5e1' }}>
        {chrome.synthetic ? 'Synthetic signal — generated, not measured from a person. ' : ''}
        {labels.length > 0
          ? `${labels.length} channels · ±${LANE_HALF_RANGE_UV} ${shownUnit} · ${WINDOW_SECONDS} s window at ${chrome.rateHz} Hz nominal. Time is seconds before the newest sample, using the stream's nominal sample spacing.${clockNote}`
          : 'Waiting for EEG samples.'}
      </p>
      {chrome.error ? <p role="alert">{chrome.error}</p> : null}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '4.5rem minmax(0, 1fr)',
          height: 480,
          width: '100%',
        }}
      >
        <ol
          style={{
            listStyle: 'none',
            margin: 0,
            padding: 0,
            display: 'grid',
            gridTemplateRows: labels.length > 0 ? `repeat(${labels.length}, 1fr) ${TIME_AXIS_PX}px` : '1fr',
            height: '100%',
          }}
        >
          {labels.map((label, index) => (
            <li
              key={`${index}-${label}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                paddingRight: 8,
                fontSize: 12,
                color: '#cbd5e1',
              }}
            >
              {label}
            </li>
          ))}
          {labels.length > 0 ? <li aria-hidden="true" /> : null}
        </ol>
        <div style={{ position: 'relative', minWidth: 0, minHeight: 0, height: '100%' }}>
          <canvas
            ref={canvasRef}
            aria-hidden="true"
            data-testid="eeg-waveform-canvas"
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }}
          />
        </div>
      </div>
    </section>
  );
}
