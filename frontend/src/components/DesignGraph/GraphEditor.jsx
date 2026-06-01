/**
 * GraphEditor — ReactFlow canvas for the design concept graph.
 * FASE 1: nodes, edges, custom renderers, toolbar, edge-type dialog.
 */
import React, { useCallback, useRef, useState, useEffect } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Panel,
  useReactFlow,
  ReactFlowProvider,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Box, Typography, Alert, Snackbar, CircularProgress } from '@mui/material';

import useDesignStore from '../../stores/designStore';
import ConceptToolbar from './ConceptToolbar';
import NodePanel from './NodePanel';
import EdgePanel from './EdgePanel';
import EdgeTypeDialog from './EdgeTypeDialog';
import DesignNodeComponent from './DesignNodeComponent';
import DesignEdgeComponent from './DesignEdgeComponent';
import ValidationOverlay from './ValidationOverlay';

// Register custom types once (outside component to avoid re-renders)
const NODE_TYPES = { designNode: DesignNodeComponent };
const EDGE_TYPES = { designEdge: DesignEdgeComponent };

// ── Inner editor (needs useReactFlow hook) ─────────────────────────────────

function GraphEditorInner() {
  const { screenToFlowPosition } = useReactFlow();
  const connectingRef = useRef({ sourceId: null });
  const [edgeDialog, setEdgeDialog] = useState(null); // { sourceId, targetId }
  const [showValidation, setShowValidation] = useState(false);

  const {
    activeGraphId: graphId,
    graphData, isLoading, error,
    selectedNodeId, selectedEdgeId,
    validationErrors, readyForSimulation, isValidating,
    onNodesChange, onEdgesChange,
    setSelectedNode, setSelectedEdge, clearSelection,
    addNode, addEdge, deleteNode, deleteEdge,
    persistNodePosition, validateGraph, clearError,
  } = useDesignStore();

  const selectedNode = graphData.nodes.find(n => n.id === selectedNodeId) || null;
  const selectedEdge = graphData.edges.find(e => e.id === selectedEdgeId) || null;

  // ── Keyboard delete ──────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (selectedNodeId) deleteNode(selectedNodeId);
      if (selectedEdgeId) deleteEdge(selectedEdgeId);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedNodeId, selectedEdgeId, deleteNode, deleteEdge]);

  // ── Connection handling ──────────────────────────────────────────────────
  const onConnectStart = useCallback((_, { nodeId }) => {
    connectingRef.current.sourceId = nodeId;
  }, []);

  const onConnectEnd = useCallback((event) => {
    const sourceId = connectingRef.current.sourceId;
    if (!sourceId) return;
    const targetEl = event.target.closest('.react-flow__node');
    const targetId = targetEl?.dataset?.id;
    if (targetId && targetId !== sourceId) {
      setEdgeDialog({ sourceId, targetId });
    }
    connectingRef.current.sourceId = null;
  }, []);

  // ── Drop new node from toolbar ───────────────────────────────────────────
  const onDrop = useCallback((event) => {
    event.preventDefault();
    const nodeType = event.dataTransfer.getData('application/design-node-type');
    const label    = event.dataTransfer.getData('application/design-node-label');
    if (!nodeType) return;

    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    addNode(nodeType, label, position, {}, 0);
  }, [screenToFlowPosition, addNode]);

  const onDragOver = useCallback((e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  // ── Node drag stop — persist position ───────────────────────────────────
  const onNodeDragStop = useCallback((_, node) => {
    persistNodePosition(node.id, node.position.x, node.position.y);
  }, [persistNodePosition]);

  // ── Selection ────────────────────────────────────────────────────────────
  const onNodeClick = useCallback((_, node) => setSelectedNode(node.id), [setSelectedNode]);
  const onEdgeClick = useCallback((_, edge) => setSelectedEdge(edge.id), [setSelectedEdge]);
  const onPaneClick = useCallback(() => clearSelection(), [clearSelection]);

  // ── Edge dialog confirm ──────────────────────────────────────────────────
  const handleEdgeConfirm = useCallback((edgeType) => {
    if (edgeDialog) {
      addEdge(edgeDialog.sourceId, edgeDialog.targetId, edgeType);
    }
    setEdgeDialog(null);
  }, [edgeDialog, addEdge]);

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!graphId) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
                 height: '100%', flexDirection: 'column', gap: 2, color: 'text.secondary' }}>
        <Typography variant="h5">CAE Lab — Design Graph</Typography>
        <Typography variant="body2">Selecciona o crea un proyecto en el panel izquierdo</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ width: '100%', height: '100%', position: 'relative' }}>
      <ReactFlow
        nodes={graphData.nodes}
        edges={graphData.edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnectStart={onConnectStart}
        onConnectEnd={onConnectEnd}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onPaneClick={onPaneClick}
        onNodeDragStop={onNodeDragStop}
        onDrop={onDrop}
        onDragOver={onDragOver}
        fitView
        deleteKeyCode={null}   // handled manually above
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#333" gap={20} />
        <Controls />
        <MiniMap
          nodeColor={n => NODE_COLORS[n.data?.node_type] || '#666'}
          style={{ background: '#1e1e1e', border: '1px solid #333' }}
        />

        {/* Validate button */}
        <Panel position="top-right">
          <Box sx={{ display: 'flex', gap: 1 }}>
            <button
              onClick={() => { validateGraph(); setShowValidation(true); }}
              style={{
                background: '#1e1e1e', color: '#90caf9', border: '1px solid #90caf9',
                borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 12,
              }}
            >
              {isValidating ? '...' : '✓ Validar grafo'}
            </button>
          </Box>
        </Panel>
      </ReactFlow>

      {/* Toolbar palette (left side of canvas) */}
      <ConceptToolbar />

      {/* Right panel: node or edge properties */}
      {selectedNode && (
        <NodePanel
          node={selectedNode}
          graphId={graphId}
          onClose={clearSelection}
        />
      )}
      {selectedEdge && !selectedNode && (
        <EdgePanel
          edge={selectedEdge}
          graphId={graphId}
          onClose={clearSelection}
        />
      )}

      {/* Validation overlay */}
      {showValidation && validationErrors.length > 0 && (
        <ValidationOverlay
          errors={validationErrors}
          readyForSimulation={readyForSimulation}
          onClose={() => setShowValidation(false)}
        />
      )}
      {showValidation && validationErrors.length === 0 && readyForSimulation && (
        <Snackbar
          open
          autoHideDuration={4000}
          onClose={() => setShowValidation(false)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert severity="success" onClose={() => setShowValidation(false)}>
            Grafo válido — listo para simulación
          </Alert>
        </Snackbar>
      )}

      {/* Edge type selection dialog */}
      <EdgeTypeDialog
        open={Boolean(edgeDialog)}
        onConfirm={handleEdgeConfirm}
        onCancel={() => setEdgeDialog(null)}
      />

      {/* Error snackbar */}
      <Snackbar
        open={Boolean(error)}
        autoHideDuration={5000}
        onClose={clearError}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      >
        <Alert severity="error" onClose={clearError}>{error}</Alert>
      </Snackbar>
    </Box>
  );
}

export const NODE_COLORS = {
  CONCEPT:      '#3f51b5',
  GEOMETRY:     '#4caf50',
  MATERIAL:     '#ff9800',
  BC:           '#f44336',
  LOAD:         '#fdd835',
  RESULT:       '#00bcd4',
  OPTIMIZATION: '#9c27b0',
};

// ── Public wrapper (provides ReactFlow context) ────────────────────────────

export default function GraphEditor() {
  return (
    <ReactFlowProvider>
      <GraphEditorInner />
    </ReactFlowProvider>
  );
}
