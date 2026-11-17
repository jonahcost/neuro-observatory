import { useEffect, useState } from 'react';
import { parseAssistantSnapshot, parseIntentResult, type AssistantSnapshot, type Finding } from '@neuro-observatory/protocol';
import type { DisplayModeId } from '../anatomy/displayModes';
import type { WaveformBuffer } from '../stream/waveformBuffer';
import { applyIntentResult, evidenceSelection, type TraceHighlight } from './assistantActions';
import styles from './AssistantPanel.module.css';

const DEFAULT_ASSISTANT_API_URL = 'http://127.0.0.1:8000/api/assistant/v1';

export function assistantApiUrlFromEnv(env: Record<string, unknown>): string {
  const explicit = env['VITE_NEURO_ENGINE_ASSISTANT_URL'];
  if (typeof explicit === 'string' && explicit.length > 0) {
    return explicit.replace(/\/+$/, '');
  }
  const socket = env['VITE_NEURO_ENGINE_WS_URL'];
  if (typeof socket === 'string' && socket.length > 0) {
    const http = socket.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:').replace(/\/ws\/v2\/eeg\/?$/, '');
    return `${http.replace(/\/+$/, '')}/api/assistant/v1`;
  }
  return DEFAULT_ASSISTANT_API_URL;
}

export interface AssistantSelection {
  primary: string | null;
  channels: readonly string[];
  highlight: TraceHighlight | null;
  displayMode: DisplayModeId | null;
}

interface Posted {
  ok: boolean;
  body: unknown;
}

function errorMessage(body: unknown, fallback: string): string {
  if (typeof body === 'object' && body !== null && 'error' in body) {
    const error = (body as { error?: { message?: unknown } }).error;
    if (typeof error?.message === 'string' && error.message.length > 0) {
      return error.message;
    }
  }
  return fallback;
}

async function postJson(url: string, body: unknown, signal: AbortSignal): Promise<Posted> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  const payload: unknown = await response.json().catch(() => null);
  return { ok: response.ok, body: payload };
}

export function AssistantPanel({
  baseUrl,
  buffer,
  onSelection,
}: {
  baseUrl: string;
  buffer: WaveformBuffer;
  onSelection: (selection: AssistantSelection) => void;
}) {
  const [snapshot, setSnapshot] = useState<AssistantSnapshot | null>(null);
  const [note, setNote] = useState('Waiting for assistant status.');
  const [reply, setReply] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [recordingId, setRecordingId] = useState('alpha-step');

  useEffect(() => {
    const controller = new AbortController();
    let timer = 0;
    const load = async () => {
      try {
        const response = await fetch(`${baseUrl}/snapshot`, { signal: controller.signal });
        const parsed = parseAssistantSnapshot(await response.text());
        if (controller.signal.aborted) {
          return;
        }
        if (!parsed.ok) {
          setNote('Assistant status is unavailable. The EEG view is unchanged.');
          return;
        }
        setSnapshot(parsed.document);
        setNote(parsed.document.model === 'unavailable' ? 'The local language model is not installed. Listed commands and on-screen findings still work.' : 'Local model ready.');
      } catch {
        if (controller.signal.aborted) {
          return;
        }
        setNote('Assistant status is unavailable. The EEG view is unchanged.');
      }
    };
    void load();
    timer = window.setInterval(() => void load(), 1000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [baseUrl]);

  const selectFinding = (finding: Finding) => {
    if (!snapshot) {
      return;
    }
    const selection = evidenceSelection(snapshot, finding);
    const visible = buffer.coversSampleRange(selection.highlight.streamId, selection.highlight.first, selection.highlight.last);
    onSelection({
      primary: selection.primary,
      channels: selection.channels,
      highlight: visible ? selection.highlight : null,
      displayMode: null,
    });
    if (!selection.seek) {
      return;
    }
    void postJson(`${baseUrl}/session`, { action: 'seek', sampleIndex: finding.firstSampleIndex }, new AbortController().signal)
      .then((posted) => {
        if (!posted.ok) {
          setReply(errorMessage(posted.body, 'The replay seek did not complete. The EEG socket stayed open.'));
        }
      })
      .catch(() => {
        setReply('The replay seek did not complete. The EEG socket stayed open.');
      });
  };

  const send = async (body: unknown) => {
    try {
      const posted = await postJson(`${baseUrl}/intent`, body, new AbortController().signal);
      if (!posted.ok) {
        setReply(errorMessage(posted.body, 'The assistant command did not complete. The EEG view is unchanged.'));
        return;
      }
      const parsed = parseIntentResult(JSON.stringify(posted.body));
      if (!parsed.ok) {
        setReply('That reply was not a valid assistant result. The EEG view is unchanged.');
        return;
      }
      const applied = applyIntentResult(parsed.document);
      onSelection({
        primary: applied.primary,
        channels: applied.channels,
        highlight: null,
        displayMode: applied.displayMode,
      });
      setReply(applied.message);
    } catch {
      setReply('The assistant command did not complete. The EEG view is unchanged.');
    }
  };

  const session = async (body: unknown) => {
    try {
      const posted = await postJson(`${baseUrl}/session`, body, new AbortController().signal);
      if (!posted.ok) {
        setReply(errorMessage(posted.body, 'The session command did not complete. The waveform stayed on the current socket.'));
      }
    } catch {
      setReply('The session command did not complete. The waveform stayed on the current socket.');
    }
  };

  return (
    <div className={styles.panel}>
      <p className={styles.note} role="status">
        {note}
        {snapshot ? ` Evidence: ${snapshot.evidence}.` : ''}
      </p>
      {reply ? <p className={styles.note}>{reply}</p> : null}
      <p className={styles.note}>Channel measurements are scalp values. They are not a cortical image or a diagnosis.</p>
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          const text = draft.trim();
          if (!text) {
            return;
          }
          void send({ text, sessionGeneration: snapshot?.sessionGeneration ?? 0 });
        }}
      >
        <label className={styles.note} htmlFor="assistant-command">
          Command
        </label>
        <input id="assistant-command" value={draft} onChange={(event) => setDraft(event.target.value)} />
        <button type="submit">Send</button>
      </form>
      <div className={styles.actions}>
        <button type="button" onClick={() => void session({ action: 'pause' })}>
          Pause
        </button>
        <button type="button" onClick={() => void session({ action: 'resume' })}>
          Resume
        </button>
        <button type="button" onClick={() => void session({ action: 'synthetic' })}>
          Synthetic
        </button>
      </div>
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          void session({ action: 'replay', recordingId });
        }}
      >
        <label className={styles.note} htmlFor="assistant-recording">
          Recording
        </label>
        <input id="assistant-recording" value={recordingId} onChange={(event) => setRecordingId(event.target.value)} />
        <button type="submit">Replay</button>
      </form>
      {snapshot && snapshot.findings.length === 0 ? <p className={styles.note}>No qualified finding yet.</p> : null}
      <ul className={styles.findings}>
        {(snapshot?.findings ?? []).map((item) => {
          const labels = item.channels.map((channel) => channel.label).join(', ');
          return (
            <li key={item.findingId}>
              <button type="button" onClick={() => selectFinding(item)}>
                Show {labels}
              </button>
              <p className={styles.note}>
                {item.method} {item.band} · samples {item.firstSampleIndex}–{item.lastSampleIndex}
                {item.quality !== 'good' ? ` · ${item.quality}` : ''}
                {item.synthetic ? ' · synthetic' : ''}
              </p>
            </li>
          );
        })}
      </ul>
      <ul className={styles.lines}>
        {(snapshot?.lines ?? []).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}
