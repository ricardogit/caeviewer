import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Drawer,
  CssBaseline,
  ThemeProvider,
  createTheme,
  IconButton,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  CircularProgress,
} from '@mui/material';
import {
  Close,
  SquareFoot, ContentCut, Draw, GridOn, Hub, Share,
} from '@mui/icons-material';
import axios from 'axios';

import StepViewer3D from './components/StepViewer3D';
import FileList from './components/FileList';
import TopBar from './components/TopBar';
import MeasurementTools from './components/MeasurementTools';
import SectionCutPanel from './components/SectionCutPanel';
import MarkupPanel from './components/MarkupPanel';
import CAEViewer from './components/CAEViewer';
import CAEFileList from './components/CAEFileList';
import MeshFromStepDialog from './components/MeshFromStepDialog';
import GraphEditor from './components/DesignGraph/GraphEditor';
import GraphProjectList from './components/DesignGraph/GraphProjectList';
import SolverPanel from './components/Solver/SolverPanel';
import GeometryList from './components/Geometry/GeometryList';
import HubPage from './components/Hub/HubPage';
import HubFilters from './components/Hub/HubFilters';
import GeometryViewer from './components/Geometry/GeometryViewer';
import FacePanel from './components/Geometry/FacePanel';
import ResultsViewer from './components/Results/ResultsViewer';
import ResultsRunList from './components/Results/ResultsRunList';
import useWorkspaceStore from './stores/workspaceStore';
import useDesignStore from './stores/designStore';

const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#90caf9' },
    secondary: { main: '#f48fb1' },
    background: { default: '#121212', paper: '#1e1e1e' },
  },
});

const SIDEBAR_WIDTH = 300;

export default function App() {
  const [selectedFile, setSelectedFile] = useState(null);

  // ── Panel visibility ─────────────────────────────────────────────────────
  const [fileListOpen, setFileListOpen] = useState(true);

  // ── App mode (FASE 9: workspace store, so TopBar actions and panels can switch it) ──
  // design | results | geometry | step | cae | hub — Design Graph is the default (§1.5)
  const { appMode, setAppMode, solverOpen, setSolverOpen, toggleSolver, loadPreflight } = useWorkspaceStore();
  const activeGraphId = useDesignStore((st) => st.activeGraphId);
  useEffect(() => { loadPreflight(activeGraphId); }, [activeGraphId, loadPreflight]);
  const caeMode = appMode === 'cae';     // kept for internal logic compatibility

  // ── CAE mode ─────────────────────────────────────────────────────────────
  const [meshDialogOpen, setMeshDialogOpen] = useState(false);
  const [selectedMesh, setSelectedMesh] = useState(null);
  const [measurementPanelOpen, setMeasurementPanelOpen] = useState(false);
  const [sectionCutOpen, setSectionCutOpen] = useState(false);
  const [markupOpen, setMarkupOpen] = useState(false);

  // ── 3D features state ────────────────────────────────────────────────────
  const [clippingPlane, setClippingPlane] = useState(null);

  // ── Cross-mode integration ───────────────────────────────────────────────
  const [sendToDesignDialogOpen, setSendToDesignDialogOpen] = useState(false);

  // Picking mode: which input is requesting a 3D point
  const [pickingMode, setPickingMode] = useState(false);
  const [pickedPoint, setPickedPoint] = useState(null);

  // Measurements to render as 3D overlay
  const [measurements3D, setMeasurements3D] = useState([]);


  // Markup state
  const [markupActive, setMarkupActive] = useState(false);
  const [markupTool, setMarkupTool] = useState('pen');
  const [markupColor, setMarkupColor] = useState('#ff4444');
  const [markupStrokeWidth, setMarkupStrokeWidth] = useState(2);
  const [markupStrokes, setMarkupStrokes] = useState([]);

  // ── Handlers ─────────────────────────────────────────────────────────────

  function handleFileSelect(file) {
    setSelectedFile(file);
    setPickingMode(false);
    setPickedPoint(null);
    setMeasurements3D([]);
    setMarkupStrokes([]);
  }

  // Called when user clicks "Pick from 3D" in MeasurementTools
  const handleActivatePicking = useCallback(() => {
    setPickingMode(true);
  }, []);

  // Called when a point is clicked in 3D viewer
  function handlePointPicked(point) {
    setPickedPoint(point);
    setPickingMode(false);
  }

  // Called by MeasurementTools after consuming the picked point
  function handlePickConsumed() {
    setPickedPoint(null);
  }

  // Cancel picking on Escape
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === 'Escape') {
        setPickingMode(false);
        setPickedPoint(null);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Load measurements from backend when measurement panel opens
  useEffect(() => {
    if (!measurementPanelOpen || !selectedFile?.header_id) return;
    axios.get(`/api/step-view/measurement/${selectedFile.header_id}/list`)
      .then(res => setMeasurements3D(res.data.measurements || []))
      .catch(() => {});
  }, [measurementPanelOpen, selectedFile]);

  // Auto-load part from CAPP integration
  useEffect(() => {
    const partId = window.PART_ID;
    if (partId && !selectedFile) {
      axios.get('/api/step-view/files')
        .then(res => {
          const files = res.data.files || [];
          const target = files.find(f => f.id === partId);
          if (target) handleFileSelect(target);
        })
        .catch(console.error);
    }
  }, []);

  const headerId = selectedFile?.header_id || selectedFile?.id;

  // ── Drawer layer helpers ──────────────────────────────────────────────────

  function leftOffset(extras = 0) {
    return (fileListOpen ? SIDEBAR_WIDTH : 0) + extras;
  }

  return (
    <ThemeProvider theme={darkTheme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>

        {/* Top Bar */}
        <TopBar
          onMenuClick={() => setFileListOpen(!fileListOpen)}
          selectedFile={selectedFile}
          selectedMesh={selectedMesh}
          onSetMode={(mode) => {
            setAppMode(mode);
            if (mode === 'design' || mode === 'results') { setSelectedFile(null); setSelectedMesh(null); }
            // Keep selectedFile when switching to CAE (for mesh provenance display)
          }}
        />

        {/* Left: sidebar — changes by mode */}
        <Drawer variant="persistent" anchor="left" open={fileListOpen}
          sx={{ width: SIDEBAR_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: SIDEBAR_WIDTH, boxSizing: 'border-box', mt: 8 } }}
        >
          {appMode === 'hub'
            ? <HubFilters />
            : appMode === 'design'
            ? <GraphProjectList />
            : appMode === 'results'
            ? <ResultsRunList />
            : appMode === 'geometry'
            ? <GeometryList />
            : appMode === 'cae'
              ? <CAEFileList onSelectMesh={setSelectedMesh} selectedMeshId={selectedMesh?.id} />
              : <FileList onSelectFile={handleFileSelect} selectedFileId={selectedFile?.id} />
          }
        </Drawer>

        {/* Main viewport */}
        <Box component="main" sx={{
          position: 'fixed',
          top: '64px',
          left: fileListOpen ? `${SIDEBAR_WIDTH}px` : 0,
          right: 0,
          bottom: 0,
          overflow: 'hidden',
          transition: 'left 0.2s',
        }}>
          {appMode === 'hub' ? (
            <HubPage onLaunch={(launch) => {
              if (!launch?.mode) return;
              if (launch.mode === 'design') { setSelectedFile(null); setSelectedMesh(null); }
              setAppMode(launch.mode);
            }} />
          ) : appMode === 'results' ? (
            <ResultsViewer />
          ) : appMode === 'design' ? (
            <Box sx={{ width: '100%', height: '100%', position: 'relative' }}>
              <GraphEditor />
              {/* Solver panel toggle */}
              <Box sx={{ position: 'absolute', top: 16, right: 16, zIndex: 25 }}>
                <IconButton
                  onClick={toggleSolver}
                  sx={{
                    bgcolor: solverOpen ? '#1565c0' : '#1e1e1e',
                    border: `1px solid ${solverOpen ? '#2196f3' : '#444'}`,
                    color: '#90caf9',
                    '&:hover': { bgcolor: '#1976d2' },
                  }}
                >
                  <Tooltip title="Panel de simulación FEM">
                    <span style={{ fontSize: 18 }}>⚡</span>
                  </Tooltip>
                </IconButton>
              </Box>
              {/* Solver panel */}
              {solverOpen && (
                <Box sx={{ position: 'absolute', top: 0, right: 0, bottom: 0, zIndex: 30 }}>
                  <SolverPanel onClose={() => setSolverOpen(false)} />
                </Box>
              )}
            </Box>
          ) : appMode === 'geometry' ? (
            <Box sx={{ width: '100%', height: '100%', position: 'relative' }}>
              <GeometryViewer />
              <FacePanel />
            </Box>
          ) : caeMode ? (
            <CAEViewer mesh={selectedMesh} />
          ) : selectedFile ? (
            <StepViewer3D
              headerId={headerId}
              filename={selectedFile.original_filename}
              pickingMode={pickingMode}
              onPointPicked={handlePointPicked}
              clippingPlane={clippingPlane}
              measurements={measurements3D}
              markupActive={markupActive}
              markupTool={markupTool}
              markupColor={markupColor}
              markupStrokeWidth={markupStrokeWidth}
              markupStrokes={markupStrokes}
              onMarkupStrokesChange={setMarkupStrokes}
            />
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'text.secondary' }}>
              <div style={{ textAlign: 'center' }}>
                <h2>CAE Viewer</h2>
                <p>Selecciona un archivo STEP en el panel izquierdo</p>
              </div>
            </Box>
          )}

          {/* Floating Action Buttons */}
          {selectedFile && appMode === 'step' && (
            <Box sx={{ position: 'absolute', top: 16, right: 16, display: 'flex', gap: 1 }}>

              <Tooltip title="Measurement Tools">
                <IconButton onClick={() => setMeasurementPanelOpen(!measurementPanelOpen)} sx={{ bgcolor: measurementPanelOpen ? 'success.main' : 'background.paper', '&:hover': { bgcolor: 'success.dark' } }}>
                  <SquareFoot />
                </IconButton>
              </Tooltip>

              <Tooltip title="Section Cut">
                <IconButton onClick={() => setSectionCutOpen(!sectionCutOpen)} sx={{ bgcolor: sectionCutOpen ? 'warning.main' : 'background.paper', '&:hover': { bgcolor: 'warning.dark' } }}>
                  <ContentCut />
                </IconButton>
              </Tooltip>

              <Tooltip title="Markup / Annotations">
                <IconButton onClick={() => setMarkupOpen(!markupOpen)} sx={{ bgcolor: markupOpen ? 'error.main' : 'background.paper', '&:hover': { bgcolor: 'error.dark' } }}>
                  <Draw />
                </IconButton>
              </Tooltip>

              <Tooltip title="Generar Malla FEA">
                <IconButton onClick={() => setMeshDialogOpen(true)} sx={{ bgcolor: 'background.paper', '&:hover': { bgcolor: 'info.dark' } }}>
                  <Hub />
                </IconButton>
              </Tooltip>

              {selectedFile && appMode === 'step' && (
                <Tooltip title="Enviar a Design Graph">
                  <IconButton onClick={() => setSendToDesignDialogOpen(true)} sx={{ bgcolor: 'background.paper', '&:hover': { bgcolor: 'warning.dark' } }}>
                    <Share />
                  </IconButton>
                </Tooltip>
              )}

            </Box>
          )}
        </Box>

        {/* ── Left drawers ──────────────────────────────────────────────── */}

        {/* ── Right drawers ─────────────────────────────────────────────── */}

        {selectedFile && (
          <Drawer variant="persistent" anchor="right" open={measurementPanelOpen}
            sx={{ width: SIDEBAR_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: SIDEBAR_WIDTH, boxSizing: 'border-box', mt: 8, zIndex: 1085 } }}
          >
            <Box sx={{ position: 'relative', height: '100%' }}>
              <IconButton onClick={() => setMeasurementPanelOpen(false)} sx={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }} size="small"><Close /></IconButton>
              <MeasurementTools
                headerId={headerId}
                onMeasurementCreate={(m) => setMeasurements3D(prev => [...prev, m.measurement || m])}
                pickingMode={pickingMode}
                onActivatePicking={handleActivatePicking}
                pickedPoint={pickedPoint}
                onPickConsumed={handlePickConsumed}
              />
            </Box>
          </Drawer>
        )}

        {selectedFile && (
          <Drawer variant="persistent" anchor="right" open={sectionCutOpen}
            sx={{ width: SIDEBAR_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: SIDEBAR_WIDTH, boxSizing: 'border-box', mt: 8, zIndex: 1080 } }}
          >
            <Box sx={{ position: 'relative', height: '100%' }}>
              <IconButton onClick={() => setSectionCutOpen(false)} sx={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }} size="small"><Close /></IconButton>
              <SectionCutPanel onPlaneChange={setClippingPlane} />
            </Box>
          </Drawer>
        )}

        {selectedFile && (
          <Drawer variant="persistent" anchor="right" open={markupOpen}
            sx={{ width: SIDEBAR_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: SIDEBAR_WIDTH, boxSizing: 'border-box', mt: 8, zIndex: 1075 } }}
          >
            <Box sx={{ position: 'relative', height: '100%' }}>
              <IconButton onClick={() => setMarkupOpen(false)} sx={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }} size="small"><Close /></IconButton>
              <MarkupPanel
                headerId={headerId}
                active={markupActive}
                onActiveChange={setMarkupActive}
                tool={markupTool}
                onToolChange={setMarkupTool}
                color={markupColor}
                onColorChange={setMarkupColor}
                strokeWidth={markupStrokeWidth}
                onStrokeWidthChange={setMarkupStrokeWidth}
                strokes={markupStrokes}
                onStrokesChange={setMarkupStrokes}
              />
            </Box>
          </Drawer>
        )}


      </Box>

      <MeshFromStepDialog
        open={meshDialogOpen}
        onClose={() => setMeshDialogOpen(false)}
        stepFile={selectedFile}
        onMeshCreated={(newMesh) => {
          setSelectedMesh(newMesh);
          setAppMode('cae');
          setMeshDialogOpen(false);
        }}
      />

      {/* Send STEP file to Design Graph */}
      {selectedFile && (
        <SendToDesignDialog
          open={sendToDesignDialogOpen}
          onClose={() => setSendToDesignDialogOpen(false)}
          stepFile={selectedFile}
        />
      )}

    </ThemeProvider>
  );
}

// Helper component for sending STEP file to Design mode
function SendToDesignDialog({ open, onClose, stepFile }) {
  const [graphs, setGraphs] = useState([]);
  const [selectedGraphId, setSelectedGraphId] = useState(null);
  const [loading, setLoading] = useState(false);

  React.useEffect(() => {
    if (open) {
      axios.get('/api/design/graph/')
        .then(res => {
          setGraphs(res.data.graphs || []);
          if (res.data.graphs?.length > 0) {
            setSelectedGraphId(res.data.graphs[0].id);
          }
        })
        .catch(console.error);
    }
  }, [open]);

  const handleSend = async () => {
    if (!selectedGraphId || !stepFile?.id) return;
    setLoading(true);
    try {
      await axios.post(
        `/api/design/graph/${selectedGraphId}/import/step`,
        { step_file_id: stepFile.id }
      );
      alert(`STEP file enviado a grafo: ${graphs.find(g => g.id === selectedGraphId)?.name}`);
      onClose();
    } catch (e) {
      alert(`Error: ${e.response?.data?.error || e.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Enviar {stepFile?.original_filename} a Design</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
        <Typography variant="body2" color="textSecondary">
          Selecciona el grafo de diseño donde deseas importar este archivo STEP como nodo GEOMETRY.
        </Typography>
        <FormControl fullWidth size="small">
          <InputLabel>Grafo destino</InputLabel>
          <Select
            value={selectedGraphId || ''}
            onChange={e => setSelectedGraphId(e.target.value)}
            label="Grafo destino"
            disabled={graphs.length === 0}
          >
            {graphs.map(g => (
              <MenuItem key={g.id} value={g.id}>
                {g.name} (v{g.version})
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {graphs.length === 0 && (
          <Typography variant="body2" color="error">
            No hay grafos disponibles. Crea uno primero en el modo Design.
          </Typography>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading}>Cancelar</Button>
        <Button
          onClick={handleSend}
          variant="contained"
          disabled={!selectedGraphId || loading}
          startIcon={loading ? <CircularProgress size={16} /> : undefined}
        >
          {loading ? 'Enviando...' : 'Enviar a Design'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
