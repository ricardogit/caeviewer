/**
 * Results store — FASE 9: finished runs of the active study and the 3D surface of the selected one.
 */
import { create } from 'zustand';
import axios from 'axios';
import { parsePack } from '../utils/romPack';

const API = '/api/design/solver';
export const FIELD_RUN_PURPOSES = ['run', 'reproduce', 'adaptive'];

const useResultsStore = create((set, get) => ({
  runs: [],
  runsLoading: false,
  runId: null,
  pack: null,
  loading: false,
  error: null,
  field: 'vm',          // vm | umag | ux | uy | uz
  scale: null,          // deformation scale (null = auto)

  setField: (field) => set({ field }),
  setScale: (scale) => set({ scale }),

  listRuns: async (graphId) => {
    if (!graphId) {
      set({ runs: [] });
      return [];
    }
    set({ runsLoading: true });
    try {
      const r = await axios.get(`${API}/runs`, { params: { graph_id: graphId, limit: 100 } });
      const runs = (r.data.runs || []).filter((x) => FIELD_RUN_PURPOSES.includes(x.purpose));
      set({ runs, runsLoading: false });
      return runs;
    } catch (e) {
      set({ runsLoading: false, error: e.response?.data?.error || e.message });
      return [];
    }
  },

  open: async (runId) => {
    if (!runId) {
      set({ runId: null, pack: null, error: null });
      return;
    }
    set({ runId, loading: true, error: null, pack: null, scale: null });
    try {
      const r = await axios.get(`${API}/${runId}/surface`, { responseType: 'arraybuffer' });
      if (get().runId !== runId) return;
      set({ pack: parsePack(r.data), loading: false });
    } catch (e) {
      if (get().runId !== runId) return;
      let msg = e.message;
      const d = e.response?.data;
      if (d instanceof ArrayBuffer) {
        try { msg = JSON.parse(new TextDecoder().decode(d)).error || msg; } catch { /* binary */ }
      } else if (d?.error) msg = d.error;
      set({ loading: false, error: msg });
    }
  },
}));

export default useResultsStore;
