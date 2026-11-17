import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WaveformBuffer } from '../stream/waveformBuffer';
import { AssistantPanel } from './AssistantPanel';

const waiting = {
  type: 'assistant.snapshot',
  schemaVersion: 1,
  sessionGeneration: 1,
  streamId: null,
  source: 'synthetic',
  recordingId: null,
  paused: false,
  evidence: 'waiting',
  model: 'unavailable',
  classifier: 'disabled',
  analysisSamplesExpired: 0,
  findings: [],
  markers: [],
  lines: [],
};

describe('AssistantPanel session errors', () => {
  it('shows the engine refusal when pause is rejected', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
          return new Response(
            JSON.stringify({ error: { code: 'not-replay', message: 'The live synthetic stream keeps running.' } }),
            { status: 400 },
          );
        }
        return new Response(JSON.stringify(waiting));
      }),
    );
    render(<AssistantPanel baseUrl="http://127.0.0.1:8000/api/assistant/v1" buffer={new WaveformBuffer()} onSelection={() => undefined} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Pause' }));
    expect(await screen.findByText(/keeps running/)).toBeTruthy();
  });
});
