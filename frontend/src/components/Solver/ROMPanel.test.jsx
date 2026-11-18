// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';
import ROMPanel from './ROMPanel';
import useROMStore from '../../stores/romStore';

vi.mock('axios');
vi.mock('./ROMExplorer', () => ({ default: () => <div data-testid="rom-explorer" /> }));

const handlers = {};
const ack = { fn: null, payload: null };
const socket = {
  on: vi.fn((ev, fn) => { handlers[ev] = fn; }),
  off: vi.fn(),
  emit: vi.fn(),
  timeout: vi.fn(() => ({ emit: (ev, payload, cb) => { ack.payload = payload; ack.fn = cb; } })),
};
vi.mock('../../services/socket', () => ({ getSocket: () => socket }));

const PARAMS = {
  parameters: [
    { key: 'E', label: 'Módulo de Young (E)', nominal: 210e9, default_range: [168e9, 252e9], default_on: true, display_scale: 1e-9, display_unit: 'GPa' },
    { key: 'nu', label: 'Poisson (ν)', nominal: 0.3, default_range: [0.25, 0.35], default_on: false, display_scale: 1, display_unit: '' },
  ],
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  useROMStore.setState({
    candidates: [], space: {}, building: null, buildError: null, roms: [], activeROM: null, pack: null,
    params: {}, result: null, responseTime: null, loadingROM: false, error: null, _inflight: false, _pending: null,
  });
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/parameters')) return Promise.resolve({ data: PARAMS });
    if (url.endsWith('/list')) return Promise.resolve({ data: { roms: [] } });
    return Promise.reject(new Error(url));
  });
});

describe('ROMPanel', () => {
  it('builds a ROM over the selected parameter space and follows progress', async () => {
    axios.post.mockResolvedValue({ data: { rom_id: 'rom1' } });
    render(<ROMPanel graphId="g1" />);
    await screen.findByText(/Construir ROM \(1 parámetro\)/);
    fireEvent.click(screen.getAllByRole('checkbox')[1]);           // add nu
    fireEvent.click(screen.getByText(/Construir ROM \(2 parámetros\)/));
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith('/api/design/rom/g1/build', expect.objectContaining({
      parameter_space: { E: [168e9, 252e9], nu: [0.25, 0.35] }, n_snapshots: 20, n_test: 3,
    })));
    await waitFor(() => expect(handlers.rom_build_progress).toBeDefined());
    handlers.rom_build_progress({ run_id: 'rom1', percent: 40, status: 'Snapshot 8/20' });
    expect(await screen.findByText('Snapshot 8/20')).toBeTruthy();
  });

  it('coalesces slider evaluations while one is in flight', () => {
    useROMStore.setState({ activeROM: { rom_id: 'rom1', parameters: [] }, params: { E: 1 } });
    const { setParam } = useROMStore.getState();
    setParam('E', 2);
    setParam('E', 3);
    setParam('E', 4);
    expect(socket.timeout).toHaveBeenCalledTimes(1);
    expect(useROMStore.getState()._pending).toEqual({ E: 4 });
    ack.fn(null, { coefficients: [1], max_von_mises_mpa: 1, response_ms: 0.1 });
    expect(socket.timeout).toHaveBeenCalledTimes(2);
    expect(ack.payload.params).toEqual({ E: 4 });
    ack.fn(null, { coefficients: [2], max_von_mises_mpa: 2, response_ms: 0.1 });
    expect(useROMStore.getState().result.max_von_mises_mpa).toBe(2);
    expect(useROMStore.getState()._inflight).toBe(false);
  });
});
