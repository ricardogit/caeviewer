/**
 * Design store — the single study store of plan §9.3 (FASE 9): the study (DesignGraph) is the context of
 * the whole UI, so its graph, its run and the workspace around it live together:
 *
 *   graph      (this file)                project list, active graph, selection, validation      FASE 1
 *   run        design/runSlice.js         simulation launch + WebSocket streaming (ex solverStore) FASE 2/3
 *   workspace  design/workspaceSlice.js   appMode, solver panel, history, preflight (ex workspaceStore)
 *
 * Opening another study resets the run state (the old run's socket events are ignored) and the preflight.
 * Tool stores (topology, ROM, uncertainty, validation, results, material, geometry, hub, jobs) stay separate:
 * they have their own lifecycles and are keyed by their own run ids.
 * Subscribe with selectors (``useShallow`` for several keys): run progress updates many times per second.
 */
import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';
import { applyNodeChanges, applyEdgeChanges } from 'reactflow';
import axios from 'axios';
import { createRunSlice, RUN_IDLE } from './design/runSlice';
import { createWorkspaceSlice } from './design/workspaceSlice';

const BASE = '/api/design/graph/';

const useDesignStore = create(
  devtools(
    (set, get, api) => ({
      ...createRunSlice(set, get, api),
      ...createWorkspaceSlice(set, get, api),

      // ── Project list ────────────────────────────────────────────────────────
      graphs: [],
      graphsLoading: false,

      // ── Active graph ────────────────────────────────────────────────────────
      activeGraphId: null,
      activeGraphMeta: null,         // { name, tier, status, version, hash }
      graphData: { nodes: [], edges: [] },   // ReactFlow format

      // ── Selection ───────────────────────────────────────────────────────────
      selectedNodeId: null,
      selectedEdgeId: null,

      // ── Validation ──────────────────────────────────────────────────────────
      validationErrors: [],          // [{ severity, message, node_id }]
      isValidating: false,
      readyForSimulation: false,

      // ── Status ──────────────────────────────────────────────────────────────
      isLoading: false,
      error: null,

      // ════════════════════════════════════════════════════════════════════════
      // Project list actions
      // ════════════════════════════════════════════════════════════════════════

      fetchGraphs: async () => {
        set({ graphsLoading: true, error: null });
        try {
          const res = await axios.get(`${BASE}/`);
          set({ graphs: res.data.graphs, graphsLoading: false });
        } catch (e) {
          set({ error: e.message, graphsLoading: false });
        }
      },

      createGraph: async (name, description = '', tier = 1) => {
        const res = await axios.post(`${BASE}/`, { name, description, tier });
        const g = res.data;
        set(s => ({ graphs: [g, ...s.graphs] }));
        return g;
      },

      /** FASE 9: copy the study into a new version (parent = graphId) and open it. */
      createVersion: async (graphId, note = '') => {
        const res = await axios.post(`${BASE}/${graphId}/versions`, { note });
        await get().fetchGraphs();
        await get().loadGraph(res.data.id);
        return res.data;
      },

      /** cascade: also delete the study's simulations and tests (the API answers 409 otherwise). */
      deleteGraph: async (graphId, cascade = false) => {
        await axios.delete(`${BASE}/${graphId}`, cascade ? { params: { cascade: 1 } } : undefined);
        if (get().activeGraphId === graphId) get()._leaveStudy();
        set(s => ({
          graphs: s.graphs.filter(g => g.id !== graphId),
          ...(s.activeGraphId === graphId
            ? { activeGraphId: null, activeGraphMeta: null, graphData: { nodes: [], edges: [] } }
            : {}),
        }));
      },

      // ════════════════════════════════════════════════════════════════════════
      // Active graph actions
      // ════════════════════════════════════════════════════════════════════════

      /** Run + preflight + history of the previous study do not apply to another one. */
      _leaveStudy: () => {
        get()._unsubscribeRun();
        set({ ...RUN_IDLE, preflight: null, historyOpen: false, showValidation: false });
      },

      loadGraph: async (graphId) => {
        if (get().activeGraphId !== graphId) get()._leaveStudy();
        set({ isLoading: true, error: null, activeGraphId: graphId,
              selectedNodeId: null, selectedEdgeId: null, validationErrors: [] });
        try {
          const res = await axios.get(`${BASE}/${graphId}`);
          const { nodes, edges, ...meta } = res.data;
          set({
            activeGraphMeta: meta,
            graphData: { nodes: nodes || [], edges: edges || [] },
            isLoading: false,
          });
        } catch (e) {
          set({ error: e.message, isLoading: false });
        }
      },

      // ── ReactFlow local change handlers (drag, select, etc.) ────────────────

      onNodesChange: (changes) => {
        set(s => ({
          graphData: {
            ...s.graphData,
            nodes: applyNodeChanges(changes, s.graphData.nodes),
          },
        }));
      },

      onEdgesChange: (changes) => {
        set(s => ({
          graphData: {
            ...s.graphData,
            edges: applyEdgeChanges(changes, s.graphData.edges),
          },
        }));
      },

      // Persist node position after drag
      persistNodePosition: async (nodeId, x, y) => {
        const graphId = get().activeGraphId;
        if (!graphId) return;
        try {
          await axios.put(`${BASE}/${graphId}/nodes/${nodeId}`, { pos_x: x, pos_y: y });
        } catch (e) {
          console.warn('Position persist failed:', e.message);
        }
      },

      // ════════════════════════════════════════════════════════════════════════
      // Node actions
      // ════════════════════════════════════════════════════════════════════════

      addNode: async (nodeType, label, position, properties = {}, level = 0) => {
        const graphId = get().activeGraphId;
        if (!graphId) return null;
        try {
          const res = await axios.post(`${BASE}/${graphId}/nodes`, {
            node_type: nodeType, label, level, properties,
            pos_x: position.x, pos_y: position.y,
          });
          const rfNode = {
            id: res.data.node_id,
            type: 'designNode',
            position,
            data: { node_type: nodeType, label, level, properties: properties || {} },
          };
          set(s => ({
            graphData: { ...s.graphData, nodes: [...s.graphData.nodes, rfNode] },
          }));
          return res.data;
        } catch (e) {
          set({ error: e.response?.data?.error || e.message });
          return null;
        }
      },

      updateNode: async (nodeId, updates) => {
        const graphId = get().activeGraphId;
        if (!graphId) return;
        try {
          await axios.put(`${BASE}/${graphId}/nodes/${nodeId}`, updates);
          set(s => ({
            graphData: {
              ...s.graphData,
              nodes: s.graphData.nodes.map(n =>
                n.id === nodeId
                  ? { ...n, data: { ...n.data, ...updates } }
                  : n
              ),
            },
          }));
        } catch (e) {
          set({ error: e.response?.data?.error || e.message });
        }
      },

      deleteNode: async (nodeId) => {
        const graphId = get().activeGraphId;
        if (!graphId) return;
        try {
          await axios.delete(`${BASE}/${graphId}/nodes/${nodeId}`);
          set(s => ({
            graphData: {
              nodes: s.graphData.nodes.filter(n => n.id !== nodeId),
              edges: s.graphData.edges.filter(e => e.source !== nodeId && e.target !== nodeId),
            },
            selectedNodeId: s.selectedNodeId === nodeId ? null : s.selectedNodeId,
          }));
        } catch (e) {
          set({ error: e.response?.data?.error || e.message });
        }
      },

      // ════════════════════════════════════════════════════════════════════════
      // Edge actions
      // ════════════════════════════════════════════════════════════════════════

      addEdge: async (sourceId, targetId, edgeType, weight = 1.0) => {
        const graphId = get().activeGraphId;
        if (!graphId) return null;
        try {
          const res = await axios.post(`${BASE}/${graphId}/edges`, {
            source_id: sourceId, target_id: targetId, edge_type: edgeType, weight,
          });
          const rfEdge = {
            id: res.data.edge_id,
            source: sourceId,
            target: targetId,
            type: 'designEdge',
            label: edgeType,
            data: { edge_type: edgeType, weight },
          };
          set(s => ({
            graphData: { ...s.graphData, edges: [...s.graphData.edges, rfEdge] },
          }));
          return res.data;
        } catch (e) {
          set({ error: e.response?.data?.error || e.message });
          return null;
        }
      },

      deleteEdge: async (edgeId) => {
        const graphId = get().activeGraphId;
        if (!graphId) return;
        try {
          await axios.delete(`${BASE}/${graphId}/edges/${edgeId}`);
          set(s => ({
            graphData: {
              ...s.graphData,
              edges: s.graphData.edges.filter(e => e.id !== edgeId),
            },
            selectedEdgeId: s.selectedEdgeId === edgeId ? null : s.selectedEdgeId,
          }));
        } catch (e) {
          set({ error: e.response?.data?.error || e.message });
        }
      },

      // ════════════════════════════════════════════════════════════════════════
      // Selection
      // ════════════════════════════════════════════════════════════════════════

      setSelectedNode: (nodeId) => set({ selectedNodeId: nodeId, selectedEdgeId: null }),
      setSelectedEdge: (edgeId) => set({ selectedEdgeId: edgeId, selectedNodeId: null }),
      clearSelection: () => set({ selectedNodeId: null, selectedEdgeId: null }),

      // ════════════════════════════════════════════════════════════════════════
      // Validation
      // ════════════════════════════════════════════════════════════════════════

      validateGraph: async () => {
        const graphId = get().activeGraphId;
        if (!graphId) return;
        set({ isValidating: true });
        try {
          const res = await axios.get(`${BASE}/${graphId}/validate`);
          set({
            validationErrors: res.data.errors,
            readyForSimulation: res.data.ready_for_simulation,
            isValidating: false,
          });
          return res.data;
        } catch (e) {
          set({ isValidating: false, error: e.message });
        }
      },

      clearError: () => set({ error: null }),
    }),
    { name: 'DesignStore' }
  )
);

export default useDesignStore;

/** Several keys of the study store with a shallow comparison: ``const { a, b } = useStudy('a', 'b')``. */
export const useStudy = (...keys) =>
  useDesignStore(useShallow((s) => Object.fromEntries(keys.map((k) => [k, s[k]]))));
