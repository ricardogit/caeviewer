/**
 * Topology store — FASE 4: SIMP runs, live progress (socket.io) and extraction.
 */
import { create } from 'zustand';
import axios from 'axios';
import { getSocket } from '../services/socket';

const API = '/api/design/topology';

export const DEFAULT_SETTINGS = {
  volume_fraction: 0.4,
  p_penalization: 3,
  max_iter: 150,
  filter_factor: 2,
  projection: true,
  keep_bc_load_solid: true,
  mesh_size_mm: '',
};

const useTopologyStore = create((set, get) => ({
  settings: { ...DEFAULT_SETTINGS },
  runId: null,
  status: 'idle',          // idle | queued | running | done | failed | cancelled
  stage: '',
  history: [],             // [{ iter, compliance, volume_fraction, change, beta, grayness }]
  maxIter: null,
  snapshotIter: 0,         // bumps when a new density snapshot is on disk
  summary: null,
  meta: null,              // { n_elements, n_design, filter_radius }
  error: null,
  extracted: null,

  setSetting: (k, v) => set(s => ({ settings: { ...s.settings, [k]: v } })),
  clearError: () => set({ error: null }),

  start: async (graphId) => {
    const { settings } = get();
    const body = { ...settings };
    if (body.mesh_size_mm === '' || body.mesh_size_mm == null) delete body.mesh_size_mm;
    else body.mesh_size_mm = Number(body.mesh_size_mm);
    set({ status: 'queued', stage: 'En cola', history: [], summary: null, meta: null, error: null,
          extracted: null, snapshotIter: 0, maxIter: settings.max_iter });
    try {
      const r = await axios.post(`${API}/${graphId}/run-simp`, body);
      set({ runId: r.data.run_id });
      get()._subscribe(r.data.run_id);
      return r.data;
    } catch (e) {
      const d = e.response?.data || {};
      set({ status: 'failed', error: d.message || d.error || e.message });
      return null;
    }
  },

  cancel: async () => {
    const { runId } = get();
    if (!runId) return;
    await axios.post(`/api/design/solver/${runId}/cancel`).catch(() => {});
    set({ status: 'cancelled', stage: 'Cancelado' });
  },

  /** Load a past run (history dialog / page reload). */
  load: async (runId) => {
    const r = await axios.get(`${API}/${runId}/state`);
    const d = r.data;
    set({ runId, status: d.status, history: d.history || [], summary: d.summary || null,
          error: d.error || null, snapshotIter: d.iteration || 0, maxIter: d.settings?.max_iter ?? null,
          stage: d.status === 'done' ? 'Completada' : d.status });
    if (d.status === 'queued' || d.status === 'running') get()._subscribe(runId);
    return d;
  },

  extract: async (threshold) => {
    const { runId } = get();
    const r = await axios.post(`${API}/${runId}/extract-mesh`, { threshold });
    set({ extracted: r.data });
    return r.data;
  },

  _subscribe: (runId) => {
    const socket = getSocket();
    ['topology_progress', 'topology_snapshot', 'topology_done', 'topology_error'].forEach(ev => socket.off(ev));
    socket.emit('join_run', { run_id: runId });
    socket.on('topology_progress', (d) => {
      if (d.run_id !== runId) return;
      set(s => {
        const next = { status: 'running', stage: d.status === 'mesh' ? 'Mallando' : 'Optimizando' };
        if (d.n_elements) next.meta = { n_elements: d.n_elements, n_design: d.n_design, filter_radius: d.filter_radius };
        if (d.max_iter) next.maxIter = d.max_iter;
        if (d.compliance != null) {
          const h = s.history.filter(x => x.iter !== d.iter);
          next.history = [...h, {
            iter: d.iter, compliance: d.compliance, volume_fraction: d.volume_fraction, change: d.change,
            beta: d.beta, grayness: d.grayness, wall_time: d.wall_time,
          }];
        }
        return next;
      });
    });
    socket.on('topology_snapshot', (d) => {
      if (d.run_id === runId) set({ snapshotIter: d.iter });
    });
    socket.on('topology_done', (d) => {
      if (d.run_id !== runId) return;
      set(s => ({ status: 'done', stage: 'Completada', summary: d, snapshotIter: s.snapshotIter + 0.5 }));
      socket.emit('leave_run', { run_id: runId });
    });
    socket.on('topology_error', (d) => {
      if (d.run_id !== runId) return;
      set({ status: d.message === 'Cancelado' ? 'cancelled' : 'failed', error: d.message, stage: 'Error' });
      socket.emit('leave_run', { run_id: runId });
    });
  },
}));

export default useTopologyStore;
