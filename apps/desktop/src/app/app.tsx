import { useEffect, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import type { Mesh } from 'three';
import type { EEGFrame } from '@neuro-observatory/protocol';

function BrainPlaceholder({ activity }: { activity: number }) {
  const mesh = useRef<Mesh>(null);

  useFrame((_, delta) => {
    if (mesh.current) {
      mesh.current.rotation.y += delta * 0.15;
    }
  });

  return (
    <mesh ref={mesh}>
      <sphereGeometry args={[1.5, 48, 32]} />
      <meshStandardMaterial
        color="#49a4ff"
        wireframe
        emissive="#174f85"
        emissiveIntensity={Math.min(activity, 1)}
      />
    </mesh>
  );
}

export function App() {
  const [frame, setFrame] = useState<EEGFrame | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const socket = new WebSocket('ws://127.0.0.1:8000/ws/eeg');

    socket.onopen = () => setConnected(true);
    socket.onmessage = (event: MessageEvent<string>) => {
      setFrame(JSON.parse(event.data) as EEGFrame);
    };
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);

    return () => socket.close();
  }, []);

  const latestVoltage = frame?.samplesUv[0]?.[0] ?? 0;
  const activity = Math.abs(latestVoltage) / 30;

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

      <p>
        EEG: {connected ? 'Connected' : 'Disconnected'}
      </p>

      <p>
        Source: {frame?.deviceId ?? 'None'}
        {' | '}
        Channels: {frame?.channelLabels.length ?? 0}
        {' | '}
        Sample rate: {frame?.sampleRateHz ?? 0} Hz
      </p>

      <div style={{ height: '65vh' }}>
        <Canvas camera={{ position: [0, 0, 5] }}>
          <ambientLight intensity={0.8} />
          <directionalLight position={[5, 5, 5]} intensity={2} />
          <BrainPlaceholder activity={activity} />
          <OrbitControls />
        </Canvas>
      </div>

      <p>
        Fp1: {latestVoltage.toFixed(2)} µV
        {' | '}
        Frame: {frame?.sequence ?? '-'}
      </p>
      <small>
        Simulated signal. Wireframe sphere is a rendering placeholder.
      </small>
    </main>
  );
}

export default App;
