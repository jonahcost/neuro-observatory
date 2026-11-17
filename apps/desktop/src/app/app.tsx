import { useEffect, useState } from 'react';
import { anatomyApiUrlFromEnv, createAnatomyClient } from '../anatomy/anatomyClient';
import { AnatomyViewer } from '../anatomy/AnatomyViewer';
import { EegStreamClient } from '../stream/eegStreamClient';
import { StreamStatusPanel } from '../stream/StreamStatusPanel';
import { engineUrlFromEnv, useEegStream } from '../stream/useEegStream';
import { ChannelActivity } from '../stream/channelActivity';
import { WaveformBuffer } from '../stream/waveformBuffer';
import { WaveformView } from '../stream/WaveformView';

export function App() {
  const [client] = useState(() => new EegStreamClient({ url: engineUrlFromEnv(import.meta.env) }));
  const [anatomyClient] = useState(() => createAnatomyClient({ baseUrl: anatomyApiUrlFromEnv(import.meta.env) }));
  const [buffer] = useState(() => new WaveformBuffer());
  const [activity] = useState(() => new ChannelActivity());
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
    <main style={{
      width: '100%',
      minHeight: '100vh',
      background: '#0b1020',
      color: '#e2e8f0',
      fontFamily: 'system-ui',
      padding: 24,
      boxSizing: 'border-box',
    }}>
      <h1>Neuro Observatory</h1>

      <StreamStatusPanel snapshot={snapshot} />

      <WaveformView buffer={buffer} snapshot={snapshot} />

      <AnatomyViewer client={anatomyClient} activity={activity} />
    </main>
  );
}

export default App;
