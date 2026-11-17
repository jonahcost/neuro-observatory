import { createHash } from 'node:crypto';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { catalogFor, fakeAnatomyEngine, makeFakeAsset } from '../testing/fakeAnatomyEngine';
import { ChannelActivity } from '../stream/channelActivity';
import { createAnatomyClient } from './anatomyClient';
import { AnatomyViewer } from './AnatomyViewer';

// jsdom has no WebGL; the scene graph is covered by sceneGeometry tests.
vi.mock('@react-three/fiber', () => ({
  Canvas: () => <div data-testid="scene" />,
  useThree: () => undefined,
  useFrame: () => undefined,
}));
vi.mock('@react-three/drei', () => ({ OrbitControls: () => null, Html: () => null }));

const BASE = 'http://engine.test/api/anatomy/v1';
const hash = (data: Uint8Array) => createHash('sha256').update(data).digest('hex');

function setup(catalogOverride?: string, before?: (engine: ReturnType<typeof fakeAnatomyEngine>) => void) {
  const template = makeFakeAsset({ assetId: 'fsaverage-0001', kind: 'template', displayName: 'fsaverage template', hash, atlas: true });
  const reference = makeFakeAsset({ assetId: 'ds000248-sub-01-0001', kind: 'reference-subject', displayName: 'ds000248 sub-01', hash });
  const engine = fakeAnatomyEngine(BASE, catalogOverride ?? catalogFor([reference, template], template.asset.assetId), [
    template,
    reference,
  ]);
  before?.(engine);
  const client = createAnatomyClient({ baseUrl: BASE, fetchImpl: engine.fetchImpl, sha256: async (b) => hash(new Uint8Array(b)) });
  render(<AnatomyViewer client={client} activity={new ChannelActivity()} />);
  return engine;
}

describe('AnatomyViewer', () => {
  it('shows the default template with its provenance and no activity claim', async () => {
    setup();
    expect(screen.getByRole('status').textContent).toContain('Loading');
    await waitFor(() => expect(screen.getByTestId('scene')).toBeTruthy());
    expect(screen.getByTestId('anatomy-kind').textContent).toContain('Template anatomy');
    expect(screen.getByTestId('activity-overlay').textContent).toContain('template 10-20 display positions');
    expect(screen.getByTestId('activity-overlay').textContent).toContain('not a source estimate');
    expect(screen.getByTestId('sensor-highlight-status').textContent).toContain('waiting');
    expect((screen.getByLabelText('Interior test marker') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/Population template/)).toBeTruthy();
    const subject = screen.getByLabelText(/Subject/) as HTMLSelectElement;
    expect(subject.value).toBe('fsaverage-0001');
    expect(Array.from(subject.options).map((o) => o.textContent)).toEqual([
      'ds000248 sub-01 [reference-subject]',
      'fsaverage template [template]',
    ]);
  });

  it('switches subject without restarting and labels the reference subject', async () => {
    const engine = setup();
    await waitFor(() => expect(screen.getByTestId('scene')).toBeTruthy());
    fireEvent.change(screen.getByLabelText(/Subject/), { target: { value: 'ds000248-sub-01-0001' } });
    await waitFor(() => expect(screen.getByTestId('anatomy-kind').textContent).toContain('Reference subject'));
    expect(screen.getByText(/1\.5 T, MPRAGE/)).toBeTruthy();
    expect(engine.requests).toContain('/assets/ds000248-sub-01-0001/files/lh.pial.positions.f32');
    expect(engine.requests.filter((r) => r === '/catalog')).toHaveLength(1);
  });

  it('loads other surfaces and anatomical atlases on demand', async () => {
    const engine = setup();
    await waitFor(() => expect(screen.getByTestId('scene')).toBeTruthy());
    fireEvent.change(screen.getByLabelText(/Surface/), { target: { value: 'inflated' } });
    await waitFor(() => expect(screen.getByText(/separated by 8 mm for display/)).toBeTruthy());
    expect(screen.getByText(/hidden on the inflated surface/)).toBeTruthy();
    expect(engine.requests).toContain('/assets/fsaverage-0001/files/rh.inflated.indices.u32');
    fireEvent.change(screen.getByLabelText(/atlas/i), { target: { value: 'aparc' } });
    await waitFor(() => expect(screen.getByText(/anatomical labels, not activity/)).toBeTruthy());
    expect(screen.getByText(/anatomical labels, not activity/)?.textContent).not.toContain('Hidden');
    fireEvent.change(screen.getByLabelText('Rendering'), { target: { value: 'holographic' } });
    expect(screen.getByText(/full-resolution surface behind the display lines/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Rendering'), { target: { value: 'grid' } });
    expect(screen.getByText(/full-resolution surface behind the display lines/)).toBeTruthy();
  });

  it('shows an actionable error and recovers on retry', async () => {
    const engine = setup(undefined, (e) =>
      e.override.set('/catalog', { status: 503, body: '{"error":{"code":"x","message":"data directory unavailable"}}' }),
    );
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('HTTP 503'));
    expect(screen.getByRole('alert').textContent).toContain('data directory unavailable');
    engine.override.delete('/catalog');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByTestId('scene')).toBeTruthy());
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('explains how to prepare anatomy when none exists', async () => {
    setup(JSON.stringify({ type: 'anatomy.catalog', schemaVersion: 1, defaultAssetId: null, assets: [] }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('neuro-engine anatomy prepare fsaverage'));
    expect(screen.queryByTestId('scene')).toBeNull();
  });

  it('picks up newly prepared anatomy when the subject list is refreshed', async () => {
    const engine = setup(undefined, (e) =>
      e.override.set('/catalog', { body: JSON.stringify({ type: 'anatomy.catalog', schemaVersion: 1, defaultAssetId: null, assets: [] }) }),
    );
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('No anatomy prepared yet'));
    engine.override.delete('/catalog');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh subjects' }));
    await waitFor(() => expect(screen.getByTestId('scene')).toBeTruthy());
    expect(screen.getByTestId('anatomy-kind').textContent).toContain('Template anatomy');
    expect(engine.requests.filter((r) => r === '/catalog')).toHaveLength(2);
  });

  it('switches rendering preset without another catalog request', async () => {
    const engine = setup();
    await waitFor(() => expect(screen.getByTestId('scene')).toBeTruthy());
    const rendering = screen.getByLabelText('Rendering') as HTMLSelectElement;
    expect(Array.from(rendering.options).map((option) => option.value)).toEqual(['solid', 'holographic', 'grid']);
    expect(rendering.value).toBe('solid');
    const before = engine.requests.length;
    fireEvent.change(rendering, { target: { value: 'grid' } });
    expect((screen.getByLabelText('Rendering') as HTMLSelectElement).value).toBe('grid');
    expect(engine.requests.length).toBe(before);
    expect(screen.getByTestId('scene')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Pathway layer'));
    expect(screen.getByText(/no pulses in this slice/)).toBeTruthy();
  });
});
