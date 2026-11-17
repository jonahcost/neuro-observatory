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

  it('clears the command and shows the model reply', async () => {
    let finish: (response: Response) => void = () => undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
          return new Promise<Response>((resolve) => {
            finish = resolve;
          });
        }
        return new Response(JSON.stringify(waiting));
      }),
    );
    render(<AssistantPanel baseUrl="http://127.0.0.1:8000/api/assistant/v1" buffer={new WaveformBuffer()} onSelection={() => undefined} />);
    const command = await screen.findByRole('textbox', { name: 'Command' });
    fireEvent.change(command, { target: { value: 'Explain Fp1 and Fp2 to me' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(command).toHaveProperty('value', '');
    expect(await screen.findByText('Asking the local model…')).toBeTruthy();
    finish(
      new Response(
        JSON.stringify({
          type: 'assistant.intent-result',
          schemaVersion: 1,
          ok: false,
          intent: 'clarify',
          message: 'I left this stream where it is.',
          channels: [],
          primaryChannel: null,
          findingIds: [],
          displayMode: null,
          seekSampleIndex: null,
          sessionGeneration: 1,
          streamId: null,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );
    expect(await screen.findByText('I left this stream where it is.')).toBeTruthy();
  });
});
