import { useCallback, useEffect, useState } from 'react';
import { anatomyApiUrlFromEnv, createAnatomyClient } from '../anatomy/anatomyClient';
import type { DisplayModeId } from '../anatomy/displayModes';
import { AnatomyViewer } from '../anatomy/AnatomyViewer';
import { AssistantPanel, assistantApiUrlFromEnv, type AssistantSelection } from '../assistant/AssistantPanel';
import { EegStreamClient } from '../stream/eegStreamClient';
import { StreamDetails, StreamStatusPanel } from '../stream/StreamStatusPanel';
import { engineUrlFromEnv, useEegStream } from '../stream/useEegStream';
import { ChannelActivity } from '../stream/channelActivity';
import { WaveformBuffer } from '../stream/waveformBuffer';
import { WaveformView } from '../stream/WaveformView';
import styles from './app.module.css';

export function App() {
  const [client] = useState(() => new EegStreamClient({ url: engineUrlFromEnv(import.meta.env) }));
  const [anatomyClient] = useState(() => createAnatomyClient({ baseUrl: anatomyApiUrlFromEnv(import.meta.env) }));
  const [buffer] = useState(() => new WaveformBuffer());
  const [activity] = useState(() => new ChannelActivity());
  const [assistantUrl] = useState(() => assistantApiUrlFromEnv(import.meta.env));
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null);
  const [emphasizedChannels, setEmphasizedChannels] = useState<readonly string[]>([]);
  const [highlightRange, setHighlightRange] = useState<AssistantSelection['highlight']>(null);
  const [requestedDisplayMode, setRequestedDisplayMode] = useState<{ nonce: number; mode: DisplayModeId } | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(true);
  const selectChannel = useCallback((label: string | null) => {
    setSelectedChannel(label);
    setEmphasizedChannels(label === null ? [] : [label]);
    setHighlightRange(null);
  }, []);
  const applyAssistant = useCallback((selection: AssistantSelection) => {
    if (selection.channels.length > 0 || selection.primary !== null) {
      setSelectedChannel(selection.primary);
      setEmphasizedChannels(selection.channels);
      setHighlightRange(selection.highlight);
    }
    if (selection.displayMode) {
      setRequestedDisplayMode((current) => ({ nonce: (current?.nonce ?? 0) + 1, mode: selection.displayMode as DisplayModeId }));
    }
  }, []);
  useEffect(() => {
    return client.onBlock((block, metadata) => {
      const now = performance.now();
      buffer.append(block, metadata, now);
      activity.append(block, metadata, now);
    });
  }, [activity, buffer, client]);
  const snapshot = useEegStream(client);
  useEffect(() => {
    activity.noteStream({ health: snapshot.health, connection: snapshot.connection }, performance.now());
  }, [activity, snapshot]);

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.mark} aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M12 4c-2.4 0-4 1.6-4.6 3.2C6 7.6 5 8.6 5 10.2 5 12 6.2 13 7.4 13.2 7 14.4 7.2 16 8.6 17.2 9.6 18.6 10.6 19.2 12 19.2s2.4-.6 3.4-2c1.4-1.2 1.6-2.8 1.2-4 .1 0 .2 0 .2-.1 1.2-.2 2.2-1.2 2.2-3 0-1.6-1-2.6-2.4-3C16 5.6 14.4 4 12 4Z" />
              <path d="M9 10.5c.8.6 1.6.8 3 .8s2.2-.2 3-.8" />
            </svg>
          </span>
          <h1 className={styles.title}>Neuro Observatory</h1>
        </div>
        <StreamStatusPanel snapshot={snapshot} />
      </header>
      <div className={styles.workspace}>
        <section className={styles.assistant} data-collapsed={assistantOpen ? 'false' : 'true'} aria-label="EEG assistant">
          <h2 className={styles.assistantTitle}>
            <button
              type="button"
              className={styles.assistantToggle}
              aria-expanded={assistantOpen}
              aria-controls="eeg-assistant-body"
              aria-label={assistantOpen ? 'Collapse assistant' : 'Expand assistant'}
              onClick={() => setAssistantOpen((open) => !open)}
            >
              Assistant
              <span aria-hidden="true">{assistantOpen ? '‹' : '›'}</span>
            </button>
          </h2>
          <div id="eeg-assistant-body" className={styles.assistantBody} hidden={!assistantOpen}>
            <AssistantPanel baseUrl={assistantUrl} buffer={buffer} onSelection={applyAssistant} />
          </div>
        </section>
        <AnatomyViewer
          client={anatomyClient}
          activity={activity}
          selectedChannel={selectedChannel}
          emphasizedChannels={emphasizedChannels}
          requestedDisplayMode={requestedDisplayMode}
          viewportClassName={styles.viewport}
          inspectorClassName={styles.inspector}
        />
        <div className={styles.lower}>
          <StreamDetails snapshot={snapshot} />
          <div className={styles.dock}>
            <WaveformView
              buffer={buffer}
              selectedChannel={selectedChannel}
              emphasizedChannels={emphasizedChannels}
              highlightRange={highlightRange}
              onSelectChannel={selectChannel}
            />
          </div>
        </div>
      </div>
    </main>
  );
}

export default App;
