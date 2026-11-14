import { describe, it, expect, vi, beforeEach } from 'vitest';
import axios from 'axios';
import useDesignStore from './designStore';

vi.mock('axios');
const handlers = {};
const socket = { on: vi.fn((ev, fn) => { handlers[ev] = fn; }), off: vi.fn(), emit: vi.fn() };
vi.mock('../services/socket', () => ({ getSocket: () => socket }));

beforeEach(() => {
  vi.clearAllMocks();
  useDesignStore.getState().resetRun();
  useDesignStore.setState({ activeGraphId: null, preflight: null, historyOpen: false });
  useDesignStore.setState({ adaptiveSettings: { target_error: 0.02, max_cycles: 4, theta: 0.5 }, tier: 1 });
});

describe('adaptive run (FASE 3)', () => {
  it('posts the adaptive settings to run-adaptive and streams one log entry per cycle', async () => {
    axios.post.mockResolvedValue({ data: { run_id: 'r1', status: 'queued' } });
    await useDesignStore.getState().startAdaptiveRun('g1');

    const [url, body] = axios.post.mock.calls[0];
    expect(url).toBe('/api/design/solver/g1/run-adaptive/');
    expect(body).toMatchObject({ target_error: 0.02, max_cycles: 4, theta: 0.5, tier: 1 });
    expect(socket.emit).toHaveBeenCalledWith('join_run', { run_id: 'r1' });

    handlers.adaptive_progress({ run_id: 'r1', cycle: 0, global_error: 0.06, n_nodes: 100 });
    handlers.adaptive_progress({ run_id: 'other', cycle: 0, global_error: 0.5, n_nodes: 1 });
    handlers.adaptive_progress({ run_id: 'r1', cycle: 1, global_error: 0.015, n_nodes: 180 });
    expect(useDesignStore.getState().adaptiveLog.map(e => e.cycle)).toEqual([0, 1]);

    axios.get.mockResolvedValue({ data: { fields: [] } });
    handlers.solver_done({ run_id: 'r1', max_displacement_mm: 1, adaptive_log: [{ cycle: 0 }, { cycle: 1 }] });
    expect(useDesignStore.getState().runStatus).toBe('done');
    expect(useDesignStore.getState().adaptiveLog).toHaveLength(2);
  });

  it('a plain run still posts to /run and clears the adaptive log', async () => {
    useDesignStore.setState({ adaptiveLog: [{ cycle: 0 }] });
    axios.post.mockResolvedValue({ data: { run_id: 'r2' } });
    await useDesignStore.getState().startRun('g1');
    expect(axios.post.mock.calls[0][0]).toBe('/api/design/solver/g1/run/');
    expect(useDesignStore.getState().adaptiveLog).toEqual([]);
  });
});

describe('single study store (plan §9.3)', () => {
  it('opening another study resets the run, the preflight and the history; old run events are ignored', async () => {
    axios.post.mockResolvedValue({ data: { run_id: 'r1' } });
    useDesignStore.setState({ activeGraphId: 'g1' });
    await useDesignStore.getState().startRun('g1');
    handlers.solver_progress({ run_id: 'r1', percent: 40, status: 'resolviendo' });
    useDesignStore.setState({ preflight: { ready: true }, historyOpen: true });
    expect(useDesignStore.getState().percentComplete).toBe(40);

    axios.get.mockResolvedValue({ data: { id: 'g2', name: 'B', nodes: [], edges: [] } });
    const progress = handlers.solver_progress;
    await useDesignStore.getState().loadGraph('g2');
    const st = useDesignStore.getState();
    expect(st.activeGraphId).toBe('g2');
    expect(st.activeRunId).toBeNull();
    expect(st.runStatus).toBe('idle');
    expect(st.preflight).toBeNull();
    expect(st.historyOpen).toBe(false);
    expect(socket.emit).toHaveBeenCalledWith('leave_run', { run_id: 'r1' });
    progress({ run_id: 'r1', percent: 90 });               // a late event of the old run
    expect(useDesignStore.getState().percentComplete).toBe(0);
  });

  it('reloading the same study keeps its run; graph and run errors are separate', async () => {
    useDesignStore.setState({ activeGraphId: 'g1', activeRunId: 'r9', runStatus: 'done', runError: 'x' });
    axios.get.mockResolvedValue({ data: { id: 'g1', nodes: [], edges: [] } });
    await useDesignStore.getState().loadGraph('g1');
    expect(useDesignStore.getState().activeRunId).toBe('r9');
    expect(useDesignStore.getState().error).toBeNull();
    expect(useDesignStore.getState().runError).toBe('x');
  });
});
