import { act, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

// jsdom has no WebGL; the scene is out of scope for this test.
vi.mock('@react-three/fiber', () => ({
  Canvas: () => <div data-testid="scene" />,
  useThree: () => undefined,
  useFrame: () => undefined,
}));

const EMPTY_CATALOG = { type: 'anatomy.catalog', schemaVersion: 1, defaultAssetId: null, assets: [] };
vi.mock('@react-three/drei', () => ({ OrbitControls: () => null, Html: () => null }));

class StubWebSocket {
  static instances: StubWebSocket[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    StubWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }
}

describe('App', () => {
  afterEach(() => {
    StubWebSocket.instances = [];
    vi.unstubAllGlobals();
  });

  it('connects to the protocol v2 endpoint and shows stream status', async () => {
    vi.stubGlobal('WebSocket', StubWebSocket);
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(EMPTY_CATALOG)));
    vi.stubGlobal('fetch', fetchMock);
    const { App } = await import('./app');
    const { unmount } = render(<App />);

    expect(screen.getByRole('heading', { name: 'Neuro Observatory' })).toBeTruthy();
    const streamStatus = () => within(screen.getByRole('region', { name: 'EEG stream status' })).getByRole('status');
    expect(streamStatus().textContent).toContain('Connecting');
    const socket = StubWebSocket.instances.at(-1);
    expect(socket?.url).toBe('ws://127.0.0.1:8000/ws/v2/eeg');

    act(() => socket?.onopen?.(new Event('open')));
    expect(streamStatus().textContent).toContain('Connected');

    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/anatomy/v1/catalog', expect.anything());
    const anatomy = screen.getByRole('region', { name: 'Cortical anatomy' });
    await waitFor(() => expect(within(anatomy).getByRole('status').textContent).toContain('No anatomy prepared yet'));

    unmount();
    expect(StubWebSocket.instances.every((s) => s.closed)).toBe(true);
  });

  it('plots accepted blocks in stream channel order', async () => {
    vi.stubGlobal('WebSocket', StubWebSocket);
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(EMPTY_CATALOG))));
    const { App } = await import('./app');
    const { unmount } = render(<App />);

    const labels = ['Fp1', 'Fp2', 'F3', 'F4', 'F7', 'F8', 'C3', 'C4', 'Cz', 'P3', 'P4', 'T7', 'T8', 'O1', 'O2', 'Pz'];
    const metadata = {
      type: 'stream.metadata',
      schemaVersion: 2,
      streamId: 'stream-a',
      device: { kind: 'synthetic', model: 'neuro-observatory-synthetic-eeg', deviceId: 'synthetic-0', adapterVersion: '1.0.0' },
      provenance: {
        kind: 'synthetic',
        generator: 'neuro_engine.acquisition.synthetic',
        generatorVersion: '1',
        seed: 0,
        configHash: `sha256:${'ab'.repeat(32)}`,
      },
      nominalSampleRateHz: 125,
      layout: 'channel-major',
      channels: labels.map((label, index) => ({ index, label, type: 'EEG', unit: 'uV', reference: 'synthetic' })),
      timebase: {
        clock: 'engine-monotonic',
        unit: 'us',
        timestampSource: 'synthetic-nominal',
        anchor: { monotonicUs: 0, unixTimeUs: 0 },
      },
    };
    const samples = labels.map((_, index) => [index]);
    const eegBlock = {
      type: 'eeg.block',
      schemaVersion: 2,
      streamId: 'stream-a',
      blockSequence: 0,
      firstSampleIndex: 0,
      sampleCount: 1,
      firstSampleTimeUs: 0,
      droppedSamplesBefore: 0,
      samples,
    };
    const socket = StubWebSocket.instances.at(-1);
    act(() => {
      socket?.onopen?.(new Event('open'));
      socket?.onmessage?.(new MessageEvent('message', { data: JSON.stringify(metadata) }));
      socket?.onmessage?.(new MessageEvent('message', { data: JSON.stringify(eegBlock) }));
    });

    const waveforms = screen.getByRole('region', { name: 'EEG waveforms' });
    const plotted = [...waveforms.querySelectorAll('li')].map((item) => item.textContent).filter((text) => text);
    expect(plotted).toEqual(labels);
    expect(waveforms.textContent).toContain('Synthetic signal');
    expect(screen.queryByText(JSON.stringify(samples))).toBeNull();
    unmount();
  });
});
