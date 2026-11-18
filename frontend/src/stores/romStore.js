/**
 * ROM store — FASE 5: build POD ROMs and explore them in real time.
 *
 * Slider moves call setParam(); evaluations go through socket.io (`rom_evaluate` with ack) and
 * are coalesced: while one request is in flight only the latest parameters are kept, so the
 * view always converges to the slider position without flooding the server.
 */
import { create } from 'zustand';
import axios from 'axios';
import { getSocket } from '../services/socket';
import { parsePack } from '../utils/romPack';

const API = '/api/design/rom';

const useROMStore = create((set, get) => ({
  // build
  candidates: [],          // parameters offered by the study
  space: {},               // key → [min, max] selected for the build
  buildSettings: { n_snapshots: 20, n_test: 3 },
  building: null,          // { romId, percent, status }
  buildError: null,
  roms: [],

  // explorer
  activeROM: null,         // GET /<rom_id> payload
  pack: null,              // parsed surface pack
  params: {},
  result: null,            // last evaluation
  responseTime: null,      // client round-trip ms
  loadingROM: false,
  error: null,
  _inflight: false,
  _pending: null,
  _seq: 0,

  loadCandidates: async (graphId) => {
    const r = await axios.get(`${API}/${graphId}/parameters`);
    const space = {};
    r.data.parameters.forEach((p) => { if (p.default_on) space[p.key] = [...p.default_range]; });
    set({ candidates: r.data.parameters, space, buildError: null });
  },
  toggleParam: (key, on) => set((s) => {
    const space = { ...s.space };
    if (on) space[key] = [...s.candidates.find((p) => p.key === key).default_range];
    else delete space[key];
    return { space };
  }),
  setRange: (key, i, value) => set((s) => {
    const r = [...(s.space[key] || [0, 0])];
    r[i] = value;
    return { space: { ...s.space, [key]: r } };
  }),
  setBuildSetting: (k, v) => set((s) => ({ buildSettings: { ...s.buildSettings, [k]: v } })),

  listROMs: async (graphId) => {
    const r = await axios.get(`${API}/${graphId}/list`);
    set({ roms: r.data.roms || [] });
  },

  build: async (graphId) => {
    const { space, buildSettings } = get();
    set({ buildError: null, building: { percent: 0, status: 'En cola' } });
    try {
      const r = await axios.post(`${API}/${graphId}/build`, { parameter_space: space, ...buildSettings });
      const romId = r.data.rom_id;
      set({ building: { romId, percent: 0, status: 'En cola' } });
      const socket = getSocket();
      ['rom_build_progress', 'rom_build_done', 'rom_build_error'].forEach((ev) => socket.off(ev));
      socket.emit('join_run', { run_id: romId });
      socket.on('rom_build_progress', (d) => {
        if (d.run_id === romId) set({ building: { romId, percent: d.percent, status: d.status } });
      });
      socket.on('rom_build_done', (d) => {
        if (d.run_id !== romId) return;
        set({ building: null });
        socket.emit('leave_run', { run_id: romId });
        get().listROMs(graphId);
      });
      socket.on('rom_build_error', (d) => {
        if (d.run_id !== romId) return;
        set({ building: null, buildError: d.message });
        socket.emit('leave_run', { run_id: romId });
        get().listROMs(graphId);
      });
      get().listROMs(graphId);
      return romId;
    } catch (e) {
      const d = e.response?.data || {};
      set({ building: null, buildError: d.message || d.error || e.message });
      return null;
    }
  },

  openExplorer: async (romId) => {
    set({ loadingROM: true, error: null, activeROM: null, pack: null, result: null });
    try {
      const [info, pack] = await Promise.all([
        axios.get(`${API}/${romId}`),
        axios.get(`${API}/${romId}/pack`, { responseType: 'arraybuffer' }),
      ]);
      const params = {};
      info.data.parameters.forEach((p) => {
        params[p.key] = p.variable ? (p.range[0] + p.range[1]) / 2 : p.nominal;
      });
      set({ activeROM: info.data, pack: parsePack(pack.data), params, loadingROM: false });
      get()._evaluate(params);
    } catch (e) {
      set({ loadingROM: false, error: e.response?.data?.error || e.message });
    }
  },
  closeExplorer: () => set({ activeROM: null, pack: null, result: null }),

  setParam: (key, value) => {
    const params = { ...get().params, [key]: value };
    set({ params });
    get()._evaluate(params);
  },

  _evaluate: (params) => {
    if (get()._inflight) { set({ _pending: params }); return; }
    const { activeROM } = get();
    if (!activeROM) return;
    const seq = get()._seq + 1;
    const t0 = performance.now();
    set({ _inflight: true, _seq: seq });
    getSocket().timeout(5000).emit('rom_evaluate', { rom_id: activeROM.rom_id, params, seq }, (err, res) => {
      const done = { _inflight: false };
      if (err) done.error = 'Sin respuesta del servidor (rom_evaluate)';
      else if (res?.error) done.error = res.error;
      else { done.result = res; done.responseTime = performance.now() - t0; done.error = null; }
      set(done);
      const next = get()._pending;
      if (next) { set({ _pending: null }); get()._evaluate(next); }
    });
  },

  fullRun: async () => {
    const { activeROM, params } = get();
    const r = await axios.post(`${API}/${activeROM.rom_id}/full-run`, { params });
    return r.data;
  },
  compare: async (runId) => {
    const { activeROM } = get();
    const r = await axios.get(`${API}/${activeROM.rom_id}/compare/${runId}`);
    return r;
  },
}));

export default useROMStore;
