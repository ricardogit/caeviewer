// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';
import UncertaintyPanel from './UncertaintyPanel';
import useUncertaintyStore from '../../stores/uncertaintyStore';

vi.mock('axios');
vi.mock('./UncertaintyBand', () => ({ default: () => <div data-testid="band" /> }));
vi.mock('recharts', () => {
  const Stub = ({ children }) => <div>{children}</div>;
  return {
    BarChart: Stub, Bar: Stub, XAxis: Stub, YAxis: Stub, Tooltip: Stub, ResponsiveContainer: Stub,
    ReferenceLine: Stub, CartesianGrid: Stub, LineChart: Stub, Line: Stub,
  };
});
const handlers = {};
const socket = { on: vi.fn((ev, fn) => { handlers[ev] = fn; }), off: vi.fn(), emit: vi.fn() };
vi.mock('../../services/socket', () => ({ getSocket: () => socket }));

const SETUP = {
  parameters: [
    { key: 'E', label: 'Módulo de Young E', nominal: 69e9, std: 2e9, display_scale: 1e-9, display_unit: 'GPa' },
    { key: 'load_0', label: 'Carga (fuerza)', nominal: 1000, std: 0, display_scale: 1, display_unit: 'N' },
  ],
  failure: { yield_mean: 276e6, yield_std: 4e6 },
  material: { material_name: 'Al 6061-T6' },
  roms: [{ rom_id: 'r1', hash: 'abcdef0123', parameter_space: { E: [1, 2], load_0: [1, 2] } }],
  tier_samples: { 1: 100 },
  max_rom_samples: 2000,
};
const RESULT = {
  run_id: 'u1',
  summary: {
    method: 'rom', n_samples: 1000, confidence: 0.95, wall_time_s: 0.8, out_of_range: 0,
    max_von_mises: {
      mean: 150e6, std: 15e6, cv: 0.1, ci_low: 120e6, ci_high: 180e6, histogram: { counts: [1], edges: [1, 2] },
    },
    max_displacement: { mean: 1e-3, std: 1e-4, ci_low: 8e-4, ci_high: 1.2e-3 },
    reliability: {
      p_failure: 0.012, p_failure_ci: [0.007, 0.02], n_failures: 12, beta_cornell: 2.3, beta_from_pf: 2.26,
      safety_factor_mean: 1.84, safety_factor_p05: 1.4,
    },
    random_variables: { yield: { mean: 276e6 } },
    sensitivity: { max_von_mises: { load_0: { spearman: 0.98, share: 0.97 } }, max_displacement: {} },
  },
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  useUncertaintyStore.setState({
    setup: null, vars: {}, running: null, runError: null, runs: [], result: null,
    settings: { n_samples: 1000, confidence: 0.95, method: 'auto', rom_id: '', seed: 0 },
  });
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/setup')) return Promise.resolve({ data: SETUP });
    if (url.endsWith('/list')) return Promise.resolve({ data: { runs: [] } });
    if (url.endsWith('/run/u1')) return Promise.resolve({ data: RESULT });
    return Promise.reject(new Error(url));
  });
});

describe('UncertaintyPanel', () => {
  it('prefills the material std and yield, runs Monte Carlo and shows the reliability', async () => {
    axios.post.mockResolvedValue({ data: { run_id: 'u1', method: 'rom', n_samples: 1000 } });
    render(<UncertaintyPanel graphId="g1" />);
    expect(await screen.findByText('Material del estudio: Al 6061-T6')).toBeTruthy();
    fireEvent.click(screen.getByText(/Propagar incertidumbre \(1 variable\)/));
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
      '/api/design/material/uncertainty/g1/run',
      expect.objectContaining({
        distributions: { E: { mean: 69e9, std: 2e9 } },
        n_samples: 1000,
        method: 'auto',
        failure: { yield_mean: 276e6, yield_std: 4e6 },
      }),
    ));
    await waitFor(() => expect(handlers.uncertainty_done).toBeDefined());
    handlers.uncertainty_progress({ run_id: 'u1', percent: 50, status: 'Muestra 500/1000' });
    expect(await screen.findByText(/Muestra 500\/1000/)).toBeTruthy();
    handlers.uncertainty_done({ run_id: 'u1' });
    expect(await screen.findByText('1.20e-2')).toBeTruthy();
    expect(screen.getByText(/2\.30 \(Cornell\)/)).toBeTruthy();
  });
});
