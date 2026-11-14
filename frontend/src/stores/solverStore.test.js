import { describe, it, expect, vi, beforeEach } from 'vitest';
import axios from 'axios';
import useSolverStore from './solverStore';

vi.mock('axios');
const handlers = {};
const socket = { on: vi.fn((ev, fn) => { handlers[ev] = fn; }), off: vi.fn(), emit: vi.fn() };
vi.mock('../services/socket', () => ({ getSocket: () => socket }));

beforeEach(() => {
  vi.clearAllMocks();
  useSolverStore.getState().resetRun();
  useSolverStore.setState({ adaptiveSettings: { target_error: 0.02, max_cycles: 4, theta: 0.5 }, tier: 1 });
});

describe('adaptive run (FASE 3)', () => {
  it('posts the adaptive settings to run-adaptive and streams one log entry per cycle', async () => {
    axios.post.mockResolvedValue({ data: { run_id: 'r1', status: 'queued' } });
    await useSolverStore.getState().startAdaptiveRun('g1');

    const [url, body] = axios.post.mock.calls[0];
    expect(url).toBe('/api/design/solver/g1/run-adaptive/');
    expect(body).toMatchObject({ target_error: 0.02, max_cycles: 4, theta: 0.5, tier: 1 });
    expect(socket.emit).toHaveBeenCalledWith('join_run', { run_id: 'r1' });

    handlers.adaptive_progress({ run_id: 'r1', cycle: 0, global_error: 0.06, n_nodes: 100 });
    handlers.adaptive_progress({ run_id: 'other', cycle: 0, global_error: 0.5, n_nodes: 1 });
    handlers.adaptive_progress({ run_id: 'r1', cycle: 1, global_error: 0.015, n_nodes: 180 });
    expect(useSolverStore.getState().adaptiveLog.map(e => e.cycle)).toEqual([0, 1]);

    axios.get.mockResolvedValue({ data: { fields: [] } });
    handlers.solver_done({ run_id: 'r1', max_displacement_mm: 1, adaptive_log: [{ cycle: 0 }, { cycle: 1 }] });
    expect(useSolverStore.getState().runStatus).toBe('done');
    expect(useSolverStore.getState().adaptiveLog).toHaveLength(2);
  });

  it('a plain run still posts to /run and clears the adaptive log', async () => {
    useSolverStore.setState({ adaptiveLog: [{ cycle: 0 }] });
    axios.post.mockResolvedValue({ data: { run_id: 'r2' } });
    await useSolverStore.getState().startRun('g1');
    expect(axios.post.mock.calls[0][0]).toBe('/api/design/solver/g1/run/');
    expect(useSolverStore.getState().adaptiveLog).toEqual([]);
  });
});
