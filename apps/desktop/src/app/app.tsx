import { useState } from 'react';
import { anatomyApiUrlFromEnv, createAnatomyClient } from '../anatomy/anatomyClient';
import { AnatomyViewer } from '../anatomy/AnatomyViewer';
import { EegStreamClient } from '../stream/eegStreamClient';
import { StreamStatusPanel } from '../stream/StreamStatusPanel';
import { engineUrlFromEnv, useEegStream } from '../stream/useEegStream';

export function App() {
  const [client] = useState(() => new EegStreamClient({ url: engineUrlFromEnv(import.meta.env) }));
  const [anatomyClient] = useState(() => createAnatomyClient({ baseUrl: anatomyApiUrlFromEnv(import.meta.env) }));
  const snapshot = useEegStream(client);

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

      <AnatomyViewer client={anatomyClient} />
    </main>
  );
}

export default App;
