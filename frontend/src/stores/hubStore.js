/**
 * Hub Store — data-driven tool catalog + filters (Engineering Hub, H1d).
 * Filters are OR within a group and AND across groups (same semantics as GET /api/catalog).
 * Non-matching cards are dimmed (plan: "al pulsar Multiphysics se resaltan las herramientas"),
 * or hidden when `hideNonMatching` is on.
 */
import { create } from 'zustand';
import axios from 'axios';

const EMPTY = { category: [], level: [], availability: [], analysis: [], method: [], deployment: [] };

const useHubStore = create((set, get) => ({
  tools: [],
  facets: null,
  loading: false,
  error: null,
  filters: { ...EMPTY },
  hideNonMatching: false,

  load: async () => {
    if (get().tools.length || get().loading) return;
    set({ loading: true });
    try {
      const [{ data: list }, { data: facets }] = await Promise.all([
        axios.get('/api/catalog'), axios.get('/api/catalog/facets'),
      ]);
      set({ tools: list.tools, facets, error: null });
    } catch (e) {
      set({ error: e.response?.data?.error || e.message });
    } finally {
      set({ loading: false });
    }
  },

  toggle: (group, value) => set((s) => {
    const cur = s.filters[group];
    const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
    return { filters: { ...s.filters, [group]: next } };
  }),
  clearFilters: () => set({ filters: { ...EMPTY } }),
  setHideNonMatching: (v) => set({ hideNonMatching: v }),
}));

export function activeFilterCount(filters) {
  return Object.values(filters).reduce((n, v) => n + v.length, 0);
}

export function matches(tool, filters) {
  const caps = tool.capabilities || {};
  const attr = { category: tool.category, level: tool.integration_level, availability: tool.availability };
  for (const [group, values] of Object.entries(filters)) {
    if (!values.length) continue;
    if (group in attr) {
      if (!values.includes(attr[group])) return false;
    } else if (!values.some((v) => (caps[group] || []).includes(v))) {
      return false;
    }
  }
  return true;
}

export default useHubStore;
