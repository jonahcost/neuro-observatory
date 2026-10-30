import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

// jsdom has no WebGL; the scene is out of scope for this test.
vi.mock('@react-three/fiber', () => ({
  Canvas: () => <div data-testid="scene" />,
  useFrame: () => undefined,
}));
vi.mock('@react-three/drei', () => ({ OrbitControls: () => null }));

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
    const { App } = await import('./app');
    const { unmount } = render(<App />);

    expect(screen.getByRole('heading', { name: 'Neuro Observatory' })).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('Connecting');
    expect(screen.getByText(/does not represent brain activity/)).toBeTruthy();
    const socket = StubWebSocket.instances.at(-1);
    expect(socket?.url).toBe('ws://127.0.0.1:8000/ws/v2/eeg');

    act(() => socket?.onopen?.(new Event('open')));
    expect(screen.getByRole('status').textContent).toContain('Connected');

    unmount();
    expect(StubWebSocket.instances.every((s) => s.closed)).toBe(true);
  });
});
