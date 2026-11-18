/**
 * Run slice of the study store (plan §9.3) — simulation launch + WebSocket streaming (FASE 2/3).
 * Formerly solverStore. The run belongs to the active study: switching study resets it (designStore.loadGraph).
 */
import axios from 'axios';
import { getSocket } from '../../services/socket';

export const RUN_IDLE = {
  activeRunId: null, runStatus: 'idle',   // idle | queued | running | done | failed | cancelled
  convergenceLog: [], currentIter: 0, currentResidual: null,
  percentComplete: 0, currentStatus: '',
  resultSummary: null, resultFields: [],
  adaptiveLog: [],
  cantileverResult: null, runError: null,
};

const RUN_EVENTS = ['solver_progress', 'solver_done', 'solver_error', 'adaptive_progress'];

export const createRunSlice = (set, get) => ({
  ...RUN_IDLE,

  // ── Physics / solver config ─────────────────────────────────────────────
  activePhysics: ['structural'],
  tolerance: 1e-8,
  maxIterations: 1000,
  tier: 1,

  // ── Adaptive meshing (FASE 3) ───────────────────────────────────────────
  adaptiveSettings: { target_error: 0.05, max_cycles: 5, theta: 0.5 },

  selectedField: 'von_mises_nodal',

  // ── Cantilever test ─────────────────────────────────────────────────────
  // FASE 2 hito defaults: slender beam (L/h = 20), T10, compared with Timoshenko
  cantileverParams: {
    length: 200, width: 10, height: 10,  // mm
    E: 210, nu: 0.3,                      // GPa, dimensionless
    force_y: 1000,                         // N
    n_div: 20,
    order: 2,                              // 1 = T4, 2 = T10
  },
  cantileverLoading: false,

  setActivePhysics: (p) => set({ activePhysics: p }),
  setTier: (t) => set({ tier: t }),
  setTolerance: (v) => set({ tolerance: v }),
  setSelectedField: (f) => set({ selectedField: f }),
  setAdaptiveLog: (log) => set({ adaptiveLog: log }),
  setAdaptiveSetting: (key, value) =>
    set(s => ({ adaptiveSettings: { ...s.adaptiveSettings, [key]: value } })),
  clearRunError: () => set({ runError: null }),

  setCantileverParam: (key, value) =>
    set(s => ({ cantileverParams: { ...s.cantileverParams, [key]: value } })),

  // ── Start simulation ────────────────────────────────────────────────────
  startRun: async (graphId, extraSpec = {}, { adaptive = false } = {}) => {
    get()._unsubscribeRun();
    set({ ...RUN_IDLE, cantileverResult: get().cantileverResult, runStatus: 'queued',
      currentStatus: 'Enviando solicitud...' });

    try {
      const spec = {
        physics: get().activePhysics,
        tier: get().tier,
        tolerance: get().tolerance,
        max_iterations: get().maxIterations,
        ...extraSpec,
      };
      const url = adaptive ? 'run-adaptive' : 'run';
      const body = adaptive ? { tier: spec.tier, ...get().adaptiveSettings, ...extraSpec } : spec;
      const res = await axios.post(`/api/design/solver/${graphId}/${url}/`, body);
      const runId = res.data.run_id;
      if (get().activeGraphId && get().activeGraphId !== graphId) return runId;   // study switched meanwhile
      set({ activeRunId: runId, runStatus: 'queued' });
      get()._subscribeToRun(runId);
      return runId;
    } catch (e) {
      // 413 = tier exceeded (message + suggested tier), 422 = graph not solvable
      const d = e.response?.data || {};
      const msg = d.message
        ? `${d.message}${d.suggested_tier != null ? ` — usa Tier ${d.suggested_tier}` : ''}`
        : (d.error || e.message);
      set({ runStatus: 'failed', runError: msg });
      return null;
    }
  },

  // FASE 3: adaptive refinement of the study (queued job fem.adaptive)
  startAdaptiveRun: (graphId, extra = {}) => get().startRun(graphId, extra, { adaptive: true }),

  // ── Cancel ──────────────────────────────────────────────────────────────
  cancelRun: async () => {
    const runId = get().activeRunId;
    if (!runId) return;
    try {
      await axios.post(`/api/design/solver/${runId}/cancel/`);
      set({ runStatus: 'cancelled' });
    } catch (e) {
      set({ runError: e.message });
    }
  },

  // ── Cantilever test ─────────────────────────────────────────────────────
  runCantileverTest: async () => {
    const { cantileverParams: p } = get();
    set({ cantileverLoading: true, cantileverResult: null, runError: null });
    try {
      // Quick validation via dedicated test endpoint (synchronous)
      const qp = new URLSearchParams({
        length: p.length / 1000, width: p.width / 1000,
        height: p.height / 1000, E: p.E * 1e9, nu: p.nu,
        force_y: p.force_y, n_div: p.n_div, order: p.order ?? 2,
      });
      const res = await axios.get(`/api/design/solver/test/cantilever/?${qp}`);
      set({ cantileverResult: res.data, cantileverLoading: false });
      return res.data;
    } catch (e) {
      set({ cantileverLoading: false, runError: e.response?.data?.error || e.message });
      return null;
    }
  },

  // ── WebSocket subscription ──────────────────────────────────────────────
  // Every handler checks the run is still the active one: events of a run left behind (study switched,
  // new run started) never touch the state.
  _subscribeToRun: (runId) => {
    const socket = getSocket();
    RUN_EVENTS.forEach((ev) => socket.off(ev));     // avoid duplicate listeners
    socket.emit('join_run', { run_id: runId });
    const mine = (data) => data.run_id === runId && get().activeRunId === runId;

    socket.on('adaptive_progress', (data) => {
      if (!mine(data)) return;
      set(s => ({ adaptiveLog: [...s.adaptiveLog.filter(e => e.cycle !== data.cycle), data] }));
    });

    socket.on('solver_progress', (data) => {
      if (!mine(data)) return;
      set(s => ({
        runStatus: 'running',
        currentIter: data.iter ?? s.currentIter,
        currentResidual: data.residual ?? s.currentResidual,
        percentComplete: data.percent ?? s.percentComplete,
        currentStatus: data.status ?? s.currentStatus,
        convergenceLog: data.residual != null
          ? [...s.convergenceLog, { iter: data.iter, residual: data.residual, wall_time: data.wall_time }]
          : s.convergenceLog,
      }));
    });

    socket.on('solver_done', (data) => {
      if (!mine(data)) return;
      set(s => ({
        runStatus: 'done',
        percentComplete: 100,
        currentStatus: 'Simulación completada',
        resultSummary: data,
        adaptiveLog: data.adaptive_log || s.adaptiveLog,
      }));
      axios.get(`/api/design/solver/${runId}/results/`)
        .then(r => { if (get().activeRunId === runId) set({ resultFields: r.data.fields || [] }); })
        .catch(() => {});
      socket.emit('leave_run', { run_id: runId });
    });

    socket.on('solver_error', (data) => {
      if (!mine(data)) return;
      set({ runStatus: 'failed', runError: data.message, currentStatus: 'Error' });
      socket.emit('leave_run', { run_id: runId });
    });
  },

  _unsubscribeRun: () => {
    const runId = get().activeRunId;
    if (!runId) return;                              // listeners only exist for a subscribed run
    const socket = getSocket();
    RUN_EVENTS.forEach((ev) => socket.off(ev));
    socket.emit('leave_run', { run_id: runId });
  },

  // ── Reset ────────────────────────────────────────────────────────────────
  resetRun: () => {
    get()._unsubscribeRun();
    set({ ...RUN_IDLE });
  },
});
