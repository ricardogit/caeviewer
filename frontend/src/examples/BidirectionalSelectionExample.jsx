/**
 * Bidirectional Selection Example
 * ================================
 *
 * Complete example demonstrating bidirectional selection between:
 * - 3D Viewer
 * - Entity Graph (Cytoscape)
 * - Entity Properties Panel
 *
 * Features:
 * - Click entity in 3D → highlights in graph → shows properties
 * - Click node in graph → highlights in 3D → shows properties
 * - Hover effects in both directions
 * - Navigate through entity relationships
 *
 * @module examples/BidirectionalSelectionExample
 */

import React, { useState, useRef, useEffect } from 'react';
import {
  Box,
  Grid,
  Paper,
  Typography,
  Drawer,
  IconButton,
  Divider,
  Alert,
  Chip,
  Stack,
} from '@mui/material';
import {
  Close as CloseIcon,
  Info as InfoIcon,
} from '@mui/icons-material';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import cytoscape from 'cytoscape';
import dagre from 'cytoscape-dagre';

import { useSelection, use3DSelection, useGraphSelection } from '../hooks/useSelection';
import { EntityProperties } from '../components/EntityProperties';

// Register Cytoscape layout
cytoscape.use(dagre);

/**
 * Mock 3D Model Component
 * In a real application, this would load GLB/GLTF models
 */
function MockModel({ onMeshClick, onMeshHover, onMeshUnhover, selectedEntityId, highlightedEntityId }) {
  // Mock entities (boxes representing different STEP entities)
  const mockEntities = [
    { id: 'entity-1', position: [-2, 0, 0], color: '#3f51b5', name: 'CARTESIAN_POINT' },
    { id: 'entity-2', position: [0, 0, 0], color: '#f50057', name: 'DIRECTION' },
    { id: 'entity-3', position: [2, 0, 0], color: '#00bcd4', name: 'AXIS2_PLACEMENT_3D' },
    { id: 'entity-4', position: [0, 2, 0], color: '#4caf50', name: 'CIRCLE' },
    { id: 'entity-5', position: [0, -2, 0], color: '#ff9800', name: 'ADVANCED_FACE' },
  ];

  return (
    <>
      {mockEntities.map((entity) => {
        const isSelected = selectedEntityId === entity.id;
        const isHighlighted = highlightedEntityId === entity.id;

        return (
          <mesh
            key={entity.id}
            position={entity.position}
            onClick={(e) => {
              e.stopPropagation();
              const mesh = e.object;
              mesh.userData = { entityId: entity.id };
              mesh.name = entity.name;
              onMeshClick(mesh);
            }}
            onPointerOver={(e) => {
              e.stopPropagation();
              const mesh = e.object;
              mesh.userData = { entityId: entity.id };
              onMeshHover(mesh);
            }}
            onPointerOut={(e) => {
              e.stopPropagation();
              onMeshUnhover();
            }}
          >
            <boxGeometry args={[1, 1, 1]} />
            <meshStandardMaterial
              color={isSelected ? '#ffeb3b' : isHighlighted ? '#ff5722' : entity.color}
              emissive={isSelected || isHighlighted ? '#ffffff' : '#000000'}
              emissiveIntensity={isSelected ? 0.5 : isHighlighted ? 0.3 : 0}
            />
          </mesh>
        );
      })}
    </>
  );
}

/**
 * 3D Viewer Component with Selection
 */
function Viewer3DWithSelection({ selectedEntityId, highlightedEntityId }) {
  const { handleMeshClick, handleMeshHover, handleMeshUnhover } = use3DSelection();

  return (
    <Canvas style={{ height: '100%', background: '#1a1a1a' }}>
      <PerspectiveCamera makeDefault position={[5, 5, 5]} />
      <OrbitControls />

      {/* Lights */}
      <ambientLight intensity={0.5} />
      <directionalLight position={[10, 10, 5]} intensity={1} />
      <hemisphereLight groundColor="#444444" intensity={0.3} />

      {/* Grid */}
      <gridHelper args={[10, 10]} />

      {/* Mock Model */}
      <MockModel
        onMeshClick={handleMeshClick}
        onMeshHover={handleMeshHover}
        onMeshUnhover={handleMeshUnhover}
        selectedEntityId={selectedEntityId}
        highlightedEntityId={highlightedEntityId}
      />
    </Canvas>
  );
}

/**
 * Graph Navigator Component with Selection
 */
function GraphNavigatorWithSelection({ selectedEntityId, highlightedEntityId }) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);

  // Initialize graph selection hook
  useGraphSelection(cyRef.current);

  useEffect(() => {
    if (!containerRef.current || cyRef.current) return;

    // Mock graph data (representing entity relationships)
    const elements = [
      // Nodes
      { data: { id: 'entity-1', label: 'CARTESIAN_POINT', type: 'geometric' } },
      { data: { id: 'entity-2', label: 'DIRECTION', type: 'geometric' } },
      { data: { id: 'entity-3', label: 'AXIS2_PLACEMENT_3D', type: 'geometric' } },
      { data: { id: 'entity-4', label: 'CIRCLE', type: 'geometric' } },
      { data: { id: 'entity-5', label: 'ADVANCED_FACE', type: 'topological' } },

      // Edges (relationships)
      { data: { source: 'entity-3', target: 'entity-1' } },
      { data: { source: 'entity-3', target: 'entity-2' } },
      { data: { source: 'entity-4', target: 'entity-3' } },
      { data: { source: 'entity-5', target: 'entity-4' } },
    ];

    // Create Cytoscape instance
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#666',
            'label': 'data(label)',
            'font-size': 10,
            'text-valign': 'center',
            'text-halign': 'center',
            'width': 40,
            'height': 40,
          },
        },
        {
          selector: 'node[type="geometric"]',
          style: {
            'background-color': '#3f51b5',
          },
        },
        {
          selector: 'node[type="topological"]',
          style: {
            'background-color': '#f50057',
          },
        },
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': '#999',
            'target-arrow-color': '#999',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
          },
        },
        {
          selector: 'node:selected',
          style: {
            'background-color': '#ffeb3b',
            'border-width': 3,
            'border-color': '#ff9800',
          },
        },
        {
          selector: 'node.highlighted',
          style: {
            'background-color': '#ff5722',
            'border-width': 2,
            'border-color': '#ff9800',
          },
        },
      ],
      layout: {
        name: 'dagre',
        rankDir: 'TB',
        nodeSep: 50,
        rankSep: 50,
      },
    });

    cyRef.current = cy;

    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
    };
  }, []);

  // Update visual state when selection changes
  useEffect(() => {
    if (!cyRef.current) return;

    // Clear previous selection
    cyRef.current.nodes().removeClass('highlighted');
    cyRef.current.nodes().unselect();

    // Highlight selected node
    if (selectedEntityId) {
      const node = cyRef.current.getElementById(selectedEntityId);
      if (node.length > 0) {
        node.select();
      }
    }

    // Highlight hovered node
    if (highlightedEntityId && highlightedEntityId !== selectedEntityId) {
      const node = cyRef.current.getElementById(highlightedEntityId);
      if (node.length > 0) {
        node.addClass('highlighted');
      }
    }
  }, [selectedEntityId, highlightedEntityId]);

  return (
    <Box
      ref={containerRef}
      sx={{
        width: '100%',
        height: '100%',
        bgcolor: 'white',
        borderRadius: 1,
      }}
    />
  );
}

/**
 * Main Example Component
 */
export default function BidirectionalSelectionExample() {
  const [showProperties, setShowProperties] = useState(false);

  const {
    selectedEntityId,
    highlightedEntityId,
    entityData,
    selectEntity,
    clearSelection,
  } = useSelection({
    onSelectionChange: ({ entityId, source }) => {
      console.log(`Entity ${entityId} selected from ${source}`);
      if (entityId) {
        setShowProperties(true);
      }
    },
    onHighlight: ({ entityId, source }) => {
      console.log(`Entity ${entityId} highlighted from ${source}`);
    },
  });

  const handleNavigateToEntity = (entityId) => {
    selectEntity(entityId, {
      source: 'properties',
      metadata: { navigationType: 'relationship' },
    });
  };

  const handleCloseProperties = () => {
    setShowProperties(false);
    clearSelection();
  };

  return (
    <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Paper elevation={2} sx={{ p: 2, borderRadius: 0 }}>
        <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between">
          <Box>
            <Typography variant="h5" gutterBottom>
              Bidirectional Selection Example
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Click entities in the 3D viewer or graph to see bidirectional selection
            </Typography>
          </Box>
          <Stack direction="row" spacing={1}>
            {selectedEntityId && (
              <Chip
                label={`Selected: ${selectedEntityId}`}
                color="primary"
                onDelete={clearSelection}
              />
            )}
            {highlightedEntityId && (
              <Chip
                label={`Highlighted: ${highlightedEntityId}`}
                color="secondary"
                variant="outlined"
              />
            )}
          </Stack>
        </Stack>
      </Paper>

      {/* Content */}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <Grid container sx={{ flex: 1 }}>
          {/* 3D Viewer */}
          <Grid item xs={12} md={6} sx={{ height: '100%' }}>
            <Paper
              elevation={0}
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                borderRadius: 0,
                borderRight: '1px solid',
                borderColor: 'divider',
              }}
            >
              <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                <Typography variant="h6">3D Viewer</Typography>
                <Typography variant="caption" color="text.secondary">
                  Click or hover over boxes
                </Typography>
              </Box>
              <Box sx={{ flex: 1 }}>
                <Viewer3DWithSelection
                  selectedEntityId={selectedEntityId}
                  highlightedEntityId={highlightedEntityId}
                />
              </Box>
            </Paper>
          </Grid>

          {/* Graph Navigator */}
          <Grid item xs={12} md={6} sx={{ height: '100%' }}>
            <Paper
              elevation={0}
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                borderRadius: 0,
              }}
            >
              <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                <Typography variant="h6">Entity Graph</Typography>
                <Typography variant="caption" color="text.secondary">
                  Click or hover over nodes
                </Typography>
              </Box>
              <Box sx={{ flex: 1, p: 2 }}>
                <GraphNavigatorWithSelection
                  selectedEntityId={selectedEntityId}
                  highlightedEntityId={highlightedEntityId}
                />
              </Box>
            </Paper>
          </Grid>
        </Grid>
      </Box>

      {/* Properties Drawer */}
      <Drawer
        anchor="right"
        open={showProperties}
        onClose={handleCloseProperties}
        variant="persistent"
        sx={{
          '& .MuiDrawer-paper': {
            width: 400,
            boxSizing: 'border-box',
          },
        }}
      >
        <Box sx={{ p: 2 }}>
          <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
            <Typography variant="h6">Entity Properties</Typography>
            <IconButton size="small" onClick={handleCloseProperties}>
              <CloseIcon />
            </IconButton>
          </Box>
          <Divider sx={{ mb: 2 }} />

          {entityData ? (
            <EntityProperties
              entityId={selectedEntityId}
              onClose={handleCloseProperties}
              onNavigateToEntity={handleNavigateToEntity}
              showCloseButton={false}
            />
          ) : (
            <Alert severity="info" icon={<InfoIcon />}>
              Select an entity in the 3D viewer or graph to see its properties
            </Alert>
          )}
        </Box>
      </Drawer>

      {/* Instructions */}
      <Paper
        elevation={3}
        sx={{
          position: 'absolute',
          bottom: 16,
          left: 16,
          p: 2,
          maxWidth: 300,
        }}
      >
        <Typography variant="subtitle2" gutterBottom>
          Instructions
        </Typography>
        <Typography variant="body2" component="div">
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            <li>Click a box in the 3D viewer → highlights in graph</li>
            <li>Click a node in the graph → highlights in 3D</li>
            <li>Hover for temporary highlight</li>
            <li>Properties panel shows entity details</li>
            <li>Navigate through relationships</li>
          </ul>
        </Typography>
      </Paper>
    </Box>
  );
}

/**
 * Usage in Application
 * ====================
 *
 * import BidirectionalSelectionExample from './examples/BidirectionalSelectionExample';
 *
 * function App() {
 *   return <BidirectionalSelectionExample />;
 * }
 */
