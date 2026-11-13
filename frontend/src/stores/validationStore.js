/**
 * Validation store — FASE 8: experiments, correlation with simulations, recalibration.
 */
import { create } from 'zustand';
import axios from 'axios';

const API = '/api/design/validation';

const errMsg = (e) => {
  const d = e.response?.data || {};
  return d.message || d.error || e.message;
};

function formData(file, fields) {
  const fd = new FormData();
  if (file) fd.append('file', file);
  Object.entries(fields).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') fd.append(k, typeof v === 'object' ? JSON.stringify(v) : v);
  });
  return fd;
}

const useValidationStore = create((set, get) => ({
  experiments: [],
  correlations: [],
  confidence: null,
  preview: null,
  previewError: null,
  busy: false,
  error: null,
  // what the CorrelationView shows: { type: 'structural'|'material'|'recal_tensile'|'recal_structural', data }
  view: null,

  clearError: () => set({ error: null }),
  setView: (view) => set({ view }),

  load: async (graphId) => {
    if (!graphId) return;
    try {
      const [e, c] = await Promise.all([
        axios.get(`${API}/experiments`, { params: { graph_id: graphId } }),
        axios.get(`${API}/${graphId}/correlations`),
      ]);
      set({ experiments: e.data.experiments || [], correlations: c.data.correlations || [] });
    } catch (e) {
      set({ error: errMsg(e) });
    }
  },

  loadConfidence: async (graphId) => {
    if (!graphId) return;
    try {
      const r = await axios.get(`${API}/${graphId}/confidence`);
      set({ confidence: r.data });
    } catch (e) {
      set({ confidence: { error: errMsg(e) } });
    }
  },

  previewFile: async (file, fields) => {
    set({ preview: null, previewError: null });
    if (!file) return;
    try {
      const r = await axios.post(`${API}/experiments/preview`, formData(file, fields));
      set({ preview: r.data });
    } catch (e) {
      set({ previewError: errMsg(e) });
    }
  },
  clearPreview: () => set({ preview: null, previewError: null }),

  /** Store the experiment; with calibrate=1 the backend recalibrates (tensile) or correlates (structural). */
  upload: async (graphId, file, fields) => {
    set({ busy: true, error: null });
    try {
      const r = await axios.post(`${API}/experiments`, formData(file, { graph_id: graphId, ...fields }));
      const d = r.data;
      let view = null;
      if (d.recalibration && d.recalibration_status === 200) view = { type: 'recal_tensile', data: d.recalibration };
      else if (d.correlation && d.correlation_status === 200) view = { type: d.correlation.kind, data: d.correlation };
      const warn = (d.recalibration_status && d.recalibration_status !== 200 && d.recalibration?.error)
        || (d.correlation_status && d.correlation_status !== 200 && d.correlation?.error) || null;
      set({ busy: false, preview: null, view, error: warn });
      get().load(graphId);
      get().loadConfidence(graphId);
      return d.experiment;
    } catch (e) {
      set({ busy: false, error: errMsg(e) });
      return null;
    }
  },

  remove: async (graphId, experimentId) => {
    try {
      await axios.delete(`${API}/experiments/${experimentId}`);
      set((s) => ({ view: s.view?.data?.experiment_id === experimentId ? null : s.view }));
      get().load(graphId);
      get().loadConfidence(graphId);
    } catch (e) {
      set({ error: errMsg(e) });
    }
  },

  correlate: async (graphId, experimentId) => {
    set({ busy: true, error: null });
    try {
      const r = await axios.post(`${API}/${graphId}/correlate`, { experiment_id: experimentId });
      set({ busy: false, view: { type: r.data.kind, data: r.data } });
      get().load(graphId);
      get().loadConfidence(graphId);
    } catch (e) {
      set({ busy: false, error: errMsg(e) });
    }
  },

  openCorrelation: async (correlationId) => {
    try {
      const r = await axios.get(`${API}/correlations/${correlationId}`);
      set({ view: { type: r.data.kind, data: r.data } });
    } catch (e) {
      set({ error: errMsg(e) });
    }
  },

  /** apply=false → preview of the recalibration (nothing stored). */
  recalibrate: async (graphId, experiment, mode = 'replace', apply = true) => {
    set({ busy: true, error: null });
    try {
      const r = await axios.post(`${API}/${graphId}/recalibrate`, { experiment_id: experiment.id, mode, apply });
      const type = experiment.test_type === 'tensile' ? 'recal_tensile' : 'recal_structural';
      set({ busy: false, view: { type, data: { ...r.data, experiment_id: experiment.id } } });
      if (apply) {
        get().load(graphId);
        get().loadConfidence(graphId);
      }
      return r.data;
    } catch (e) {
      set({ busy: false, error: errMsg(e) });
      return null;
    }
  },
}));

export default useValidationStore;
