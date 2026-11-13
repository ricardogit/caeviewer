/**
 * Material store — FASE 6: material library, tensile-test fits and assignment to MATERIAL nodes.
 */
import { create } from 'zustand';
import axios from 'axios';

const API = '/api/design/material';

const useMaterialStore = create((set, get) => ({
  materials: [],
  current: null,           // full material (with calibration)
  fit: null,               // last fit response (all models, curves)
  files: [],               // File objects of the last fit (to refit with another model)
  fitOptions: { strain_unit: 'auto', stress_unit: 'auto', area_mm2: '', gauge_mm: '' },
  busy: false,
  error: null,

  list: async () => {
    const r = await axios.get(`${API}/`);
    set({ materials: r.data.materials || [] });
  },
  open: async (id) => {
    set({ busy: true, error: null, fit: null, files: [] });
    try {
      const r = await axios.get(`${API}/${id}`);
      set({ current: r.data, busy: false });
    } catch (e) {
      set({ busy: false, error: e.response?.data?.error || e.message });
    }
  },
  create: async (name, parameters = {}) => {
    set({ error: null });
    try {
      const r = await axios.post(`${API}/`, { name, parameters });
      await get().list();
      set({ current: r.data, fit: null, files: [] });
      return r.data;
    } catch (e) {
      set({ error: e.response?.data?.error || e.message });
      return null;
    }
  },
  save: async (patch) => {
    const { current } = get();
    if (!current) return null;
    set({ error: null });
    try {
      const r = await axios.put(`${API}/${current.id}`, patch);
      set({ current: r.data });
      get().list();
      return r.data;
    } catch (e) {
      set({ error: e.response?.data?.error || e.message });
      return null;
    }
  },
  remove: async (id) => {
    await axios.delete(`${API}/${id}`);
    set((s) => ({ current: s.current?.id === id ? null : s.current }));
    await get().list();
  },
  setFitOption: (k, v) => set((s) => ({ fitOptions: { ...s.fitOptions, [k]: v } })),

  /** Fit the curves (File list) and store the result in the current material. model: force a candidate. */
  fitFiles: async (files, model = null) => {
    const { current, fitOptions } = get();
    if (!current || !files?.length) return null;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append('files', f, f.name));
    Object.entries(fitOptions).forEach(([k, v]) => { if (v !== '' && v != null) form.append(k, v); });
    if (model) form.append('model', model);
    set({ busy: true, error: null, files: Array.from(files) });
    try {
      const r = await axios.post(`${API}/${current.id}/fit`, form);
      set({ fit: r.data, current: r.data.material, busy: false });
      get().list();
      return r.data;
    } catch (e) {
      set({ busy: false, error: e.response?.data?.error || e.message });
      return null;
    }
  },

  assign: async (graphId, nodeId) => {
    const { current } = get();
    if (!current) return null;
    try {
      const r = await axios.post(`${API}/${current.id}/assign`, { graph_id: graphId, node_id: nodeId });
      return r.data.properties;
    } catch (e) {
      set({ error: e.response?.data?.error || e.message });
      return null;
    }
  },
}));

export default useMaterialStore;
