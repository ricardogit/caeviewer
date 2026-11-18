// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react';
import axios from 'axios';
import TopologyPanel from './TopologyPanel';
import useTopologyStore, { DEFAULT_SETTINGS } from '../../stores/topologyStore';

vi.mock('axios');
vi.mock('./DensityField', () => ({ default: () => <div data-testid="density-field" /> }));
vi.mock('recharts', () => {
  const Stub = ({ children }) => <div>{children}</div>;
  return { LineChart: Stub, Line: Stub, XAxis: Stub, YAxis: Stub, Tooltip: Stub, ResponsiveContainer: Stub, CartesianGrid: Stub };
});

const handlers = {};
const socket = {
  on: vi.fn((ev, fn) => { handlers[ev] = fn; }),
  off: vi.fn(),
  emit: vi.fn(),
};
vi.mock('../../services/socket', () => ({ getSocket: () => socket }));

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  useTopologyStore.setState({
    settings: { ...DEFAULT_SETTINGS }, runId: null, status: 'idle', history: [], summary: null, error: null, meta: null,
  });
});

describe('TopologyPanel', () => {
  it('launches SIMP with the settings and follows the live progress', async () => {
    axios.post.mockResolvedValue({ data: { run_id: 'run1', status: 'queued' } });
    render(<TopologyPanel graphId="g1" />);
    fireEvent.click(screen.getByText('Optimizar topología'));
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
      '/api/design/topology/g1/run-simp',
      expect.objectContaining({ volume_fraction: 0.4, p_penalization: 3, max_iter: 150, projection: true }),
    ));
    const posted = axios.post.mock.calls[0][1];
    expect(posted).not.toHaveProperty('mesh_size_mm');          // empty = automatic
    expect(socket.emit).toHaveBeenCalledWith('join_run', { run_id: 'run1' });

    act(() => {
      handlers.topology_progress({ run_id: 'run1', iter: 1, compliance: 2.0, volume_fraction: 0.4, change: 0.2,
        beta: 1, grayness: 1, max_iter: 150 });
      handlers.topology_progress({ run_id: 'run1', iter: 2, compliance: 1.0, volume_fraction: 0.4, change: 0.2,
        beta: 1, grayness: 0.9 });
    });
    expect(await screen.findByText(/Flexibilidad: 2\.000 → 1\.000 \(−50 %\)/)).toBeTruthy();
    expect(screen.getByText('Detener')).toBeTruthy();

    act(() => {
      handlers.topology_done({ run_id: 'run1', compliance_initial: 2.0, compliance_bw: 0.5, converged: true,
        n_iterations: 2, grayness: 0.05, wall_time_s: 3.2 });
    });
    expect(await screen.findByText(/Convergió en 2 iteraciones/)).toBeTruthy();
    expect(screen.getByText('Optimizar topología')).toBeTruthy();
  });

  it('shows the backend error (e.g. gravity in the study)', async () => {
    axios.post.mockRejectedValue({ response: { data: { error: 'Quita la carga de gravedad' } } });
    render(<TopologyPanel graphId="g1" />);
    fireEvent.click(screen.getByText('Optimizar topología'));
    expect(await screen.findByText('Quita la carga de gravedad')).toBeTruthy();
  });

  it('sends the AM overhang settings only when the constraint is on', async () => {
    axios.post.mockResolvedValue({ data: { run_id: 'run2', status: 'queued' } });
    render(<TopologyPanel graphId="g1" />);
    fireEvent.click(screen.getByText('Optimizar topología'));
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    expect(axios.post.mock.calls[0][1]).not.toHaveProperty('build_direction');
    expect(axios.post.mock.calls[0][1]).not.toHaveProperty('tau');

    act(() => useTopologyStore.setState({ status: 'idle' }));
    fireEvent.click(screen.getByLabelText(/Manufactura aditiva/));
    fireEvent.change(screen.getByLabelText('Dirección de impresión'), { target: { value: '+Y' } });
    fireEvent.click(screen.getByText('Optimizar topología'));
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1]).toEqual(expect.objectContaining({
      am_constraint: true, build_direction: [0, 1, 0], max_overhang_angle: 45 }));

    act(() => {
      handlers.topology_progress({ run_id: 'run2', iter: 1, compliance: 2.0, volume_fraction: 0.4, change: 0.2,
        beta: 1, grayness: 1 });
      handlers.topology_done({ run_id: 'run2', compliance_initial: 2.0, compliance_bw: 0.6, converged: true,
        n_iterations: 9, wall_time_s: 1, method: 'SIMP',
        am: { constrained: true, build_direction: [0, 1, 0], max_overhang_angle: 45,
          overhang_area_fraction: 0.021, unsupported_volume_fraction: 0.004 } });
    });
    expect(await screen.findByText(/voladizo 2\.1 % del área · sin soporte 0\.4 % del volumen/)).toBeTruthy();
  });

  it('launches the level set on its own endpoint without the SIMP-only keys', async () => {
    axios.post.mockResolvedValue({ data: { run_id: 'run3', status: 'queued' } });
    render(<TopologyPanel graphId="g1" />);
    fireEvent.click(screen.getByLabelText('Level Set'));
    expect(screen.queryByText(/Penalización p/)).toBeNull();
    expect(screen.getByText(/Regularización τ/)).toBeTruthy();
    fireEvent.click(screen.getByText('Optimizar topología'));
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
      '/api/design/topology/g1/run-levelset',
      expect.objectContaining({ volume_fraction: 0.4, tau: 2e-4, ramp_iter: 40 }),
    ));
    const posted = axios.post.mock.calls[0][1];
    ['p_penalization', 'filter_factor', 'projection', 'am_constraint', 'method'].forEach(k =>
      expect(posted).not.toHaveProperty(k));
  });
});
