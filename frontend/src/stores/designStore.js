/**
 * Design Store — state for the Design Graph editor.
 * FASE 1: graph CRUD, node/edge management, validation.
 */
import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { applyNodeChanges, applyEdgeChanges } from 'reactflow';
import axios from 'axios';

const BASE = '/api/design/graph/';

const useDesignStore = create(
  devtools(
    (set, get) => ({
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

      deleteGraph: async (graphId) => {
        await axios.delete(`${BASE}/${graphId}`);
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

      loadGraph: async (graphId) => {
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
