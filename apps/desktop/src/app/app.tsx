import { useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import type { Mesh } from 'three';
import { EegStreamClient } from '../stream/eegStreamClient';
import { StreamStatusPanel } from '../stream/StreamStatusPanel';
import { engineUrlFromEnv, useEegStream } from '../stream/useEegStream';

function BrainPlaceholder() {
  const mesh = useRef<Mesh>(null);

  useFrame((_, delta) => {
    if (mesh.current) {
      mesh.current.rotation.y += delta * 0.15;
    }
  });

  return (
    <mesh ref={mesh}>
      <sphereGeometry args={[1.5, 48, 32]} />
      <meshStandardMaterial color="#49a4ff" wireframe emissive="#174f85" emissiveIntensity={0.3} />
    </mesh>
  );
}

export function App() {
  const [client] = useState(() => new EegStreamClient({ url: engineUrlFromEnv(import.meta.env) }));
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

      <div style={{ height: '55vh' }}>
        <Canvas camera={{ position: [0, 0, 5] }}>
          <ambientLight intensity={0.8} />
          <directionalLight position={[5, 5, 5]} intensity={2} />
          <BrainPlaceholder />
          <OrbitControls />
        </Canvas>
      </div>

      <small>
        The wireframe sphere is a rendering placeholder; it does not represent brain activity.
      </small>
    </main>
  );
}

export default App;
