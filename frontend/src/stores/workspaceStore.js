/**
 * Workspace store — FASE 9: the unified workspace state shared by TopBar, App and panels.
 *
 *   appMode      design | results | geometry | step | cae | hub
 *   solverOpen   right context panel (SolverPanel) visible in Design
 *   solverMode   which SolverPanel section: graph | cantilever | topology | rom | uncertainty | validation
 *   historyOpen  simulation history dialog (FASE 7)
 *   preflight    GET /api/design/solver/<graph_id>/preflight — graph status strip (plan §9.4)
 *
 * Kept separate from designStore (graph data) and solverStore (run streaming) on purpose:
 * the plan's single store §9.3 would mix three lifecycles; these are the cross-mode bits.
 */
import { create } from 'zustand';
import axios from 'axios';

const useWorkspaceStore = create((set, get) => ({
  appMode: 'design',
  solverOpen: false,
  solverMode: 'graph',
  historyOpen: false,
  showValidation: false,
  preflight: null,
  preflightLoading: false,
  _preflightSeq: 0,

  setAppMode: (appMode) => set({ appMode }),
  setSolverOpen: (solverOpen) => set({ solverOpen }),
  toggleSolver: () => set((s) => ({ solverOpen: !s.solverOpen })),
  setSolverMode: (solverMode) => set({ solverMode }),
  /** Open the context panel on a section (from TopBar actions, results, etc.). */
  openSolver: (mode = 'graph') => set({ appMode: 'design', solverOpen: true, solverMode: mode }),
  setHistoryOpen: (historyOpen) => set({ historyOpen }),
  setShowValidation: (showValidation) => set({ showValidation }),

  loadPreflight: async (graphId) => {
    if (!graphId) {
      set({ preflight: null });
      return null;
    }
    const seq = get()._preflightSeq + 1;
    set({ preflightLoading: true, _preflightSeq: seq });
    try {
      const r = await axios.get(`/api/design/solver/${graphId}/preflight`);
      if (get()._preflightSeq === seq) set({ preflight: r.data, preflightLoading: false });
      return r.data;
    } catch (e) {
      if (get()._preflightSeq === seq) {
        set({ preflight: { error: e.response?.data?.error || e.message }, preflightLoading: false });
      }
      return null;
    }
  },
}));

export default useWorkspaceStore;
