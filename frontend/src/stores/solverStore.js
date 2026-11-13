/**
 * Solver Store — simulation state + WebSocket streaming.
 * FASE 2: full implementation with socket.io-client.
 */
import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import axios from 'axios';
import { getSocket } from '../services/socket';

const useSolverStore = create(
  devtools(
    (set, get) => ({
      // ── Active run ──────────────────────────────────────────────────────────
      activeRunId: null,
      runStatus: 'idle',    // idle | queued | running | done | failed | cancelled

      // ── Physics ─────────────────────────────────────────────────────────────
      activePhysics: ['structural'],

      // ── Solver config ───────────────────────────────────────────────────────
      tolerance: 1e-8,
      maxIterations: 1000,
      tier: 1,

      // ── Convergence streaming ───────────────────────────────────────────────
      convergenceLog: [],   // [{ iter, residual, wall_time }]
      currentIter: 0,
      currentResidual: null,
      percentComplete: 0,
      currentStatus: '',

      // ── Adaptive meshing ────────────────────────────────────────────────────
      adaptiveLog: [],

      // ── Results ─────────────────────────────────────────────────────────────
      resultSummary: null,      // { max_displacement_mm, max_von_mises_mpa, ... }
      resultFields: [],         // [{ name, type, components, data_min, data_max }]
      selectedField: 'von_mises_nodal',

      // ── Cantilever test ─────────────────────────────────────────────────────
      cantileverParams: {
        length: 50, width: 10, height: 10,   // mm
        E: 210, nu: 0.3,                      // GPa, dimensionless
        force_y: 1000,                         // N
        n_div: 12,
      },
      cantileverResult: null,
      cantileverLoading: false,

      // ── Error ───────────────────────────────────────────────────────────────
      error: null,

      // ════════════════════════════════════════════════════════════════════════
      // Actions
      // ════════════════════════════════════════════════════════════════════════

      setActivePhysics: (p) => set({ activePhysics: p }),
      setTier: (t) => set({ tier: t }),
      setTolerance: (v) => set({ tolerance: v }),
      setSelectedField: (f) => set({ selectedField: f }),
      setAdaptiveLog: (log) => set({ adaptiveLog: log }),
      clearError: () => set({ error: null }),

      setCantileverParam: (key, value) =>
        set(s => ({ cantileverParams: { ...s.cantileverParams, [key]: value } })),

      // ── Start simulation ────────────────────────────────────────────────────
      startRun: async (graphId, extraSpec = {}) => {
        set({
          runStatus: 'queued',
          convergenceLog: [],
          currentIter: 0,
          currentResidual: null,
          percentComplete: 0,
          resultSummary: null,
          resultFields: [],
          error: null,
          currentStatus: 'Enviando solicitud...',
        });

        try {
          const spec = {
            physics: get().activePhysics,
            tier: get().tier,
            tolerance: get().tolerance,
            max_iterations: get().maxIterations,
            ...extraSpec,
          };
          const res = await axios.post(`/api/design/solver/${graphId}/run/`, spec);
          const runId = res.data.run_id;
          set({ activeRunId: runId, runStatus: 'queued' });
          get()._subscribeToRun(runId);
          return runId;
        } catch (e) {
          const msg = e.response?.data?.error || e.message;
          set({ runStatus: 'failed', error: msg });
          return null;
        }
      },

      // ── Cancel ──────────────────────────────────────────────────────────────
      cancelRun: async () => {
        const runId = get().activeRunId;
        if (!runId) return;
        try {
          await axios.post(`/api/design/solver/${runId}/cancel/`);
          set({ runStatus: 'cancelled' });
        } catch (e) {
          set({ error: e.message });
        }
      },

      // ── Cantilever test ─────────────────────────────────────────────────────
      runCantileverTest: async (graphId) => {
        const { cantileverParams: p } = get();
        set({ cantileverLoading: true, cantileverResult: null, error: null });

        try {
          // Launch via run endpoint with cantilever spec
          const spec = {
            physics: ['structural'],
            tier: 0,
            mesh_source: 'cantilever',
            mesh_params: {
              length: p.length / 1000,   // mm → m
              width:  p.width  / 1000,
              height: p.height / 1000,
              n_along_length: p.n_div,
            },
            material: {
              type: 'linear_elastic_isotropic',
              E:  p.E * 1e9,             // GPa → Pa
              nu: p.nu,
              rho: 7800,
            },
            bcs:  [{ node_set: 'fixed', dofs: [0, 1, 2], values: [0, 0, 0] }],
            loads: [{ node_set: 'tip',  force: [0, -p.force_y, 0] }],
          };

          // Quick validation via dedicated test endpoint (synchronous)
          const qp = new URLSearchParams({
            length: p.length / 1000, width: p.width / 1000,
            height: p.height / 1000, E: p.E * 1e9, nu: p.nu,
            force_y: p.force_y, n_div: p.n_div,
          });
          const res = await axios.get(`/api/design/solver/test/cantilever/?${qp}`);
          set({ cantileverResult: res.data, cantileverLoading: false });
          return res.data;
        } catch (e) {
          set({ cantileverLoading: false, error: e.response?.data?.error || e.message });
          return null;
        }
      },

      // ── WebSocket subscription ──────────────────────────────────────────────
      _subscribeToRun: (runId) => {
        const socket = getSocket();

        // Remove previous listeners (avoid duplicates)
        socket.off('solver_progress');
        socket.off('solver_done');
        socket.off('solver_error');

        socket.emit('join_run', { run_id: runId });

        socket.on('solver_progress', (data) => {
          if (data.run_id !== runId) return;
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
          if (data.run_id !== runId) return;
          set({
            runStatus: 'done',
            percentComplete: 100,
            currentStatus: 'Simulación completada',
            resultSummary: data,
          });
          // Load field list
          axios.get(`/api/design/solver/${runId}/results/`)
            .then(r => set({ resultFields: r.data.fields || [] }))
            .catch(() => {});
          socket.emit('leave_run', { run_id: runId });
        });

        socket.on('solver_error', (data) => {
          if (data.run_id !== runId) return;
          set({
            runStatus: 'failed',
            error: data.message,
            currentStatus: 'Error',
          });
          socket.emit('leave_run', { run_id: runId });
        });
      },

      // ── Reset ────────────────────────────────────────────────────────────────
      resetRun: () => set({
        activeRunId: null, runStatus: 'idle',
        convergenceLog: [], currentIter: 0, currentResidual: null,
        percentComplete: 0, currentStatus: '',
        resultSummary: null, resultFields: [],
        adaptiveLog: [],
        cantileverResult: null, error: null,
      }),
    }),
    { name: 'SolverStore' }
  )
);

export default useSolverStore;
