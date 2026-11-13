/**
 * Uncertainty store — FASE 6: Monte Carlo propagation of material/load uncertainty.
 */
import { create } from 'zustand';
import axios from 'axios';
import { getSocket } from '../services/socket';
import { parsePack } from '../utils/romPack';

const API = '/api/design/material/uncertainty';

const useUncertaintyStore = create((set, get) => ({
  setup: null,
  vars: {},                // key → { on, mean, std }
  failure: { on: false, yield_mean: null, yield_std: 0 },
  settings: { n_samples: 1000, confidence: 0.95, method: 'auto', rom_id: '', seed: 0 },
  running: null,           // { runId, percent, status, method, n }
  runError: null,
  runs: [],
  result: null,            // GET /run/<id>
  surface: null,           // parsed pack for the band view

  loadSetup: async (graphId) => {
    const r = await axios.get(`${API}/${graphId}/setup`);
    const vars = {};
    r.data.parameters.forEach((p) => {
      vars[p.key] = { on: p.std > 0, mean: p.nominal, std: p.std || 0.05 * Math.abs(p.nominal) };
    });
    const f = r.data.failure;
    set({
      setup: r.data, vars, runError: null,
      failure: f ? { on: true, yield_mean: f.yield_mean, yield_std: f.yield_std } : { on: false, yield_mean: null, yield_std: 0 },
    });
  },
  setVar: (key, patch) => set((s) => ({ vars: { ...s.vars, [key]: { ...s.vars[key], ...patch } } })),
  setFailure: (patch) => set((s) => ({ failure: { ...s.failure, ...patch } })),
  setSetting: (k, v) => set((s) => ({ settings: { ...s.settings, [k]: v } })),

  listRuns: async (graphId) => {
    const r = await axios.get(`${API}/${graphId}/list`);
    set({ runs: r.data.runs || [] });
  },

  run: async (graphId) => {
    const { vars, failure, settings } = get();
    const distributions = {};
    Object.entries(vars).forEach(([k, v]) => { if (v.on && v.std > 0) distributions[k] = { mean: v.mean, std: v.std }; });
    const body = {
      distributions, n_samples: settings.n_samples, confidence: settings.confidence, seed: settings.seed,
      method: settings.method, ...(settings.method === 'rom' && settings.rom_id ? { rom_id: settings.rom_id } : {}),
      failure: failure.on && failure.yield_mean ? { yield_mean: failure.yield_mean, yield_std: failure.yield_std || 0 } : null,
    };
    set({ runError: null, running: { percent: 0, status: 'En cola' } });
    try {
      const r = await axios.post(`${API}/${graphId}/run`, body);
      const runId = r.data.run_id;
      set({ running: { runId, percent: 0, status: 'En cola', method: r.data.method, n: r.data.n_samples } });
      const socket = getSocket();
      ['uncertainty_progress', 'uncertainty_done', 'uncertainty_error'].forEach((ev) => socket.off(ev));
      socket.emit('join_run', { run_id: runId });
      socket.on('uncertainty_progress', (d) => {
        if (d.run_id === runId) set((s) => ({ running: { ...s.running, percent: d.percent, status: d.status } }));
      });
      socket.on('uncertainty_done', (d) => {
        if (d.run_id !== runId) return;
        set({ running: null });
        socket.emit('leave_run', { run_id: runId });
        get().listRuns(graphId);
        get().loadResult(runId);
      });
      socket.on('uncertainty_error', (d) => {
        if (d.run_id !== runId) return;
        set({ running: null, runError: d.message });
        socket.emit('leave_run', { run_id: runId });
        get().listRuns(graphId);
      });
      get().listRuns(graphId);
      return runId;
    } catch (e) {
      const d = e.response?.data || {};
      set({ running: null, runError: d.message || d.error || e.message });
      return null;
    }
  },

  loadResult: async (runId) => {
    const r = await axios.get(`${API}/run/${runId}`);
    set({ result: r.data });
    return r.data;
  },
  loadSurface: async (runId) => {
    const r = await axios.get(`${API}/run/${runId}/surface`, { responseType: 'arraybuffer' });
    const surface = parsePack(r.data);
    set({ surface });
    return surface;
  },
  closeSurface: () => set({ surface: null }),
}));

export default useUncertaintyStore;
