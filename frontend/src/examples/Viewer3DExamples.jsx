/**
 * Viewer3D Examples
 * ==================
 *
 * Ejemplos de uso del componente Viewer3D con diferentes configuraciones.
 *
 * @module examples/Viewer3DExamples
 */

import React, { useState } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Tabs,
  Tab,
  Button,
  Stack,
  Divider,
} from '@mui/material';

import Viewer3D, { SimpleViewer3D } from '../components/Viewer3D';
import { useViewerStore, RENDER_MODES } from '../stores/viewerStore';

/**
 * Tab Panel Helper
 */
function TabPanel({ children, value, index }) {
  return (
    <div hidden={value !== index}>
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

/**
 * Ejemplo 1: Viewer Básico
 */
function BasicViewerExample() {
  const [modelId, setModelId] = useState('example-model-001');

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        1. Basic Viewer
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Uso básico del visor 3D con controles por defecto.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Code:
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`<Viewer3D
  modelId="example-model-001"
  height="600px"
  showControls={true}
/>`}
        </Box>
      </Paper>

      <Viewer3D
        modelId={modelId}
        height="600px"
        showControls={true}
        onModelLoad={(gltf) => console.log('Model loaded:', gltf)}
      />
    </Box>
  );
}

/**
 * Ejemplo 2: Viewer Simple
 */
function SimpleViewerExample() {
  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        2. Simple Viewer
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Versión simplificada con opciones mínimas.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Code:
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`<SimpleViewer3D
  modelId="example-model-002"
  height="500px"
/>`}
        </Box>
      </Paper>

      <SimpleViewer3D modelId="example-model-002" height="500px" />
    </Box>
  );
}

/**
 * Ejemplo 3: Controles Programáticos
 */
function ProgrammaticControlsExample() {
  const {
    renderMode,
    setRenderMode,
    toggleGrid,
    toggleAxes,
    showGrid,
    showAxes,
    applyLightingPreset,
  } = useViewerStore();

  const handleSetRenderMode = (mode) => {
    setRenderMode(mode);
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        3. Programmatic Controls
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Controlar el visor programáticamente desde componentes externos.
      </Typography>

      {/* Controles externos */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          External Controls:
        </Typography>

        <Stack spacing={2}>
          {/* Render Mode */}
          <Box>
            <Typography variant="body2" gutterBottom>
              Render Mode:
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap">
              {Object.values(RENDER_MODES).map((mode) => (
                <Button
                  key={mode}
                  size="small"
                  variant={renderMode === mode ? 'contained' : 'outlined'}
                  onClick={() => handleSetRenderMode(mode)}
                >
                  {mode}
                </Button>
              ))}
            </Stack>
          </Box>

          {/* Display Options */}
          <Box>
            <Typography variant="body2" gutterBottom>
              Display Options:
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                variant={showGrid ? 'contained' : 'outlined'}
                onClick={toggleGrid}
              >
                Grid: {showGrid ? 'ON' : 'OFF'}
              </Button>
              <Button
                size="small"
                variant={showAxes ? 'contained' : 'outlined'}
                onClick={toggleAxes}
              >
                Axes: {showAxes ? 'ON' : 'OFF'}
              </Button>
            </Stack>
          </Box>

          {/* Lighting Presets */}
          <Box>
            <Typography variant="body2" gutterBottom>
              Lighting Presets:
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                variant="outlined"
                onClick={() => applyLightingPreset('studio')}
              >
                Studio
              </Button>
              <Button
                size="small"
                variant="outlined"
                onClick={() => applyLightingPreset('outdoor')}
              >
                Outdoor
              </Button>
              <Button
                size="small"
                variant="outlined"
                onClick={() => applyLightingPreset('dramatic')}
              >
                Dramatic
              </Button>
            </Stack>
          </Box>
        </Stack>
      </Paper>

      <Viewer3D modelId="example-model-003" height="600px" />
    </Box>
  );
}

/**
 * Ejemplo 4: Callbacks y Eventos
 */
function CallbacksExample() {
  const [events, setEvents] = useState([]);

  const addEvent = (eventName, data) => {
    setEvents((prev) => [
      { timestamp: new Date().toISOString(), name: eventName, data },
      ...prev.slice(0, 9), // Keep last 10 events
    ]);
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        4. Callbacks and Events
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Escuchar eventos del visor (carga, selección, etc.).
      </Typography>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Event Log:
        </Typography>
        <Box
          sx={{
            maxHeight: 200,
            overflow: 'auto',
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            fontFamily: 'monospace',
            fontSize: '0.875rem',
          }}
        >
          {events.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No events yet...
            </Typography>
          ) : (
            events.map((event, index) => (
              <Box key={index} sx={{ mb: 0.5 }}>
                <Typography
                  component="span"
                  variant="caption"
                  color="text.secondary"
                >
                  [{new Date(event.timestamp).toLocaleTimeString()}]
                </Typography>{' '}
                <Typography component="span" variant="body2" fontWeight="bold">
                  {event.name}
                </Typography>
                {event.data && (
                  <Typography
                    component="span"
                    variant="body2"
                    color="text.secondary"
                  >
                    {' '}
                    - {JSON.stringify(event.data)}
                  </Typography>
                )}
              </Box>
            ))
          )}
        </Box>
        <Button
          size="small"
          onClick={() => setEvents([])}
          sx={{ mt: 1 }}
          variant="outlined"
        >
          Clear Log
        </Button>
      </Paper>

      <Viewer3D
        modelId="example-model-004"
        height="500px"
        onModelLoad={(gltf) => addEvent('Model Loaded', { meshes: gltf.scene.children.length })}
        onSelectionChange={(entity) => addEvent('Selection Changed', { entity: entity?.name })}
      />
    </Box>
  );
}

/**
 * Ejemplo 5: Múltiples Visores
 */
function MultipleViewersExample() {
  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        5. Multiple Viewers
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Mostrar múltiples visores en la misma página.
      </Typography>

      <Stack spacing={2}>
        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Viewer A:
          </Typography>
          <SimpleViewer3D modelId="example-model-005a" height="400px" />
        </Box>

        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Viewer B:
          </Typography>
          <SimpleViewer3D modelId="example-model-005b" height="400px" />
        </Box>
      </Stack>
    </Box>
  );
}

/**
 * Componente principal de ejemplos
 */
export default function Viewer3DExamples() {
  const [currentTab, setCurrentTab] = useState(0);

  const handleTabChange = (event, newValue) => {
    setCurrentTab(newValue);
  };

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Typography variant="h3" gutterBottom>
        Viewer3D Examples
      </Typography>
      <Typography variant="body1" color="text.secondary" paragraph>
        Ejemplos completos de uso del componente de visualización 3D.
      </Typography>

      <Divider sx={{ my: 3 }} />

      <Paper sx={{ mt: 3 }}>
        <Tabs
          value={currentTab}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
        >
          <Tab label="1. Basic Viewer" />
          <Tab label="2. Simple Viewer" />
          <Tab label="3. Programmatic Controls" />
          <Tab label="4. Callbacks" />
          <Tab label="5. Multiple Viewers" />
        </Tabs>

        <TabPanel value={currentTab} index={0}>
          <BasicViewerExample />
        </TabPanel>
        <TabPanel value={currentTab} index={1}>
          <SimpleViewerExample />
        </TabPanel>
        <TabPanel value={currentTab} index={2}>
          <ProgrammaticControlsExample />
        </TabPanel>
        <TabPanel value={currentTab} index={3}>
          <CallbacksExample />
        </TabPanel>
        <TabPanel value={currentTab} index={4}>
          <MultipleViewersExample />
        </TabPanel>
      </Paper>

      {/* Code Examples */}
      <Paper sx={{ mt: 3, p: 3 }}>
        <Typography variant="h5" gutterBottom>
          Quick Start
        </Typography>

        <Typography variant="subtitle1" gutterBottom sx={{ mt: 2 }}>
          1. Install Dependencies
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`npm install @react-three/fiber @react-three/drei three zustand
npm install @mui/material @emotion/react @emotion/styled`}
        </Box>

        <Typography variant="subtitle1" gutterBottom sx={{ mt: 2 }}>
          2. Basic Usage
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`import Viewer3D from './components/Viewer3D';

function App() {
  return (
    <Viewer3D
      modelId="your-model-id"
      height="600px"
      showControls={true}
      onModelLoad={(gltf) => console.log('Loaded:', gltf)}
    />
  );
}`}
        </Box>

        <Typography variant="subtitle1" gutterBottom sx={{ mt: 2 }}>
          3. With Store
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`import { useViewerStore } from './stores/viewerStore';

function Controls() {
  const { renderMode, setRenderMode, toggleGrid } = useViewerStore();

  return (
    <div>
      <button onClick={() => setRenderMode('wireframe')}>
        Wireframe
      </button>
      <button onClick={toggleGrid}>
        Toggle Grid
      </button>
    </div>
  );
}`}
        </Box>
      </Paper>
    </Container>
  );
}
