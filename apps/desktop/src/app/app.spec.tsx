import { createHash } from 'node:crypto';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { catalogFor, fakeAnatomyEngine, makeFakeAsset } from '../testing/fakeAnatomyEngine';

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
    const assistant = screen.getByRole('region', { name: 'EEG assistant' });
    const anatomy = screen.getByRole('region', { name: 'Cortical anatomy' });
    const waveforms = screen.getByRole('region', { name: 'EEG waveforms' });
    expect(assistant.compareDocumentPosition(anatomy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(anatomy.compareDocumentPosition(waveforms) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(assistant).getByRole('textbox', { name: 'Command' })).toBeTruthy();
    fireEvent.click(within(assistant).getByRole('button', { name: 'Collapse assistant' }));
    expect(within(assistant).queryByRole('textbox', { name: 'Command' })).toBeNull();
    fireEvent.click(within(assistant).getByRole('button', { name: 'Expand assistant' }));
    expect(within(assistant).getByRole('textbox', { name: 'Command' })).toBeTruthy();
    expect(StubWebSocket.instances).toHaveLength(1);
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
    expect(waveforms.textContent).not.toContain('Synthetic signal');
    expect(waveforms.textContent).not.toContain('Connected');
    expect(screen.getByRole('region', { name: 'EEG stream status' }).textContent).toContain('Synthetic signal');
    expect(screen.queryByText(JSON.stringify(samples))).toBeNull();
    unmount();
  });

  it('keeps the selected channel and the same socket when the display changes', async () => {
    vi.stubGlobal('WebSocket', StubWebSocket);
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const hash = (data: Uint8Array) => createHash('sha256').update(data).digest('hex');
    const template = makeFakeAsset({
      assetId: 'fsaverage-0001',
      kind: 'template',
      displayName: 'fsaverage template',
      hash,
      surfaces: ['pial', 'inflated'],
    });
    const engine = fakeAnatomyEngine(
      'http://127.0.0.1:8000/api/anatomy/v1',
      catalogFor([template], template.asset.assetId),
      [template],
    );
    vi.stubGlobal('fetch', engine.fetchImpl);
    const { App } = await import('./app');
    const { unmount } = render(<App />);
    await waitFor(() => expect(screen.getByTestId('scene')).toBeTruthy());

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
    const eegBlock = {
      type: 'eeg.block',
      schemaVersion: 2,
      streamId: 'stream-a',
      blockSequence: 0,
      firstSampleIndex: 0,
      sampleCount: 1,
      firstSampleTimeUs: 0,
      droppedSamplesBefore: 0,
      samples: labels.map(() => [0]),
    };
    const socket = StubWebSocket.instances.at(-1);
    act(() => {
      socket?.onopen?.(new Event('open'));
      socket?.onmessage?.(new MessageEvent('message', { data: JSON.stringify(metadata) }));
      socket?.onmessage?.(new MessageEvent('message', { data: JSON.stringify(eegBlock) }));
    });

    fireEvent.click(screen.getByRole('button', { name: 'Cz' }));
    expect(screen.getByRole('button', { name: 'Cz' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('radio', { name: 'Grid' }));
    expect(screen.getByRole('button', { name: 'Cz' }).getAttribute('aria-pressed')).toBe('true');
    expect((screen.getByRole('radio', { name: 'Grid' }) as HTMLInputElement).checked).toBe(true);
    expect(StubWebSocket.instances).toHaveLength(1);
    unmount();
  });

  it('emphasizes a finding on the existing EEG socket', async () => {
    vi.stubGlobal('WebSocket', StubWebSocket);
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const assistant = {
      type: 'assistant.snapshot',
      schemaVersion: 1,
      sessionGeneration: 1,
      streamId: 'stream-a',
      source: 'synthetic',
      recordingId: null,
      paused: false,
      evidence: 'ready',
      model: 'unavailable',
      classifier: 'disabled',
      analysisSamplesExpired: 0,
      findings: [
        {
          findingId: 'finding-alpha',
          sessionGeneration: 1,
          streamId: 'stream-a',
          recordingId: null,
          sourceKind: 'synthetic',
          deviceId: 'synthetic-0',
          method: 'band-power',
          methodVersion: '1',
          band: 'alpha',
          firstSampleIndex: 0,
          lastSampleIndex: 0,
          firstSampleTimeUs: 0,
          lastSampleTimeUs: 0,
          nominalSampleRateHz: 125,
          channels: [
            {
              index: 13,
              label: 'O1',
              reference: 'synthetic',
              unit: 'uV',
              powerUv2: 10,
              baselineUv2: 1,
              changeDb: 10,
              rmsUv: 3,
              acceptedSampleFraction: 1,
              quality: 'good',
            },
            {
              index: 14,
              label: 'O2',
              reference: 'synthetic',
              unit: 'uV',
              powerUv2: 10,
              baselineUv2: 1,
              changeDb: 10,
              rmsUv: 3,
              acceptedSampleFraction: 1,
              quality: 'good',
            },
          ],
          quality: 'good',
          synthetic: true,
        },
      ],
      markers: [],
      lines: ['O1, O2 alpha power changed.'],
    };
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('/api/assistant/v1')) {
        return new Response(JSON.stringify(assistant));
      }
      return new Response(JSON.stringify(EMPTY_CATALOG));
    });
    vi.stubGlobal('fetch', fetchMock);
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
    const socket = StubWebSocket.instances.at(-1);
    act(() => {
      socket?.onopen?.(new Event('open'));
      socket?.onmessage?.(new MessageEvent('message', { data: JSON.stringify(metadata) }));
      socket?.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'eeg.block',
            schemaVersion: 2,
            streamId: 'stream-a',
            blockSequence: 0,
            firstSampleIndex: 0,
            sampleCount: 1,
            firstSampleTimeUs: 0,
            droppedSamplesBefore: 0,
            samples: labels.map(() => [0]),
          }),
        }),
      );
    });
    const show = await screen.findByRole('button', { name: 'Show O1, O2' });
    fireEvent.click(show);
    expect(screen.getByRole('button', { name: 'O1' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'O2' }).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('button', { name: 'Cz' }).getAttribute('aria-pressed')).toBe('false');
    expect(StubWebSocket.instances).toHaveLength(1);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/session'))).toBe(false);
    unmount();
  });
});
