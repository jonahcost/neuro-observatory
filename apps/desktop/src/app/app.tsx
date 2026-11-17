import { useCallback, useEffect, useState } from 'react';
import { anatomyApiUrlFromEnv, createAnatomyClient } from '../anatomy/anatomyClient';
import { AnatomyViewer } from '../anatomy/AnatomyViewer';
import { EegStreamClient } from '../stream/eegStreamClient';
import { StreamStatusPanel } from '../stream/StreamStatusPanel';
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
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null);
  const selectChannel = useCallback((label: string | null) => {
    setSelectedChannel(label);
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
        <h1 className={styles.title}>Neuro Observatory</h1>
        <StreamStatusPanel snapshot={snapshot} />
      </header>
      <div className={styles.workspace}>
        <AnatomyViewer
          client={anatomyClient}
          activity={activity}
          selectedChannel={selectedChannel}
          viewportClassName={styles.viewport}
          inspectorClassName={styles.inspector}
        />
        <div className={styles.dock}>
          <WaveformView buffer={buffer} snapshot={snapshot} selectedChannel={selectedChannel} onSelectChannel={selectChannel} />
        </div>
      </div>
    </main>
  );
}

export default App;
