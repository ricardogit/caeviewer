import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Drawer,
  CssBaseline,
  ThemeProvider,
  createTheme,
  IconButton,
  Tooltip,
} from '@mui/material';
import {
  AccountTree, Info, Close, Build,
  Straighten, SquareFoot, ContentCut, Draw, GridOn, Hub,
} from '@mui/icons-material';
import axios from 'axios';

import StepViewer3D from './components/StepViewer3D';
import FileList from './components/FileList';
import TopBar from './components/TopBar';
import EntityTree from './components/EntityTree';
import EntityDetails from './components/EntityDetails';
import FeaturePanel from './components/FeaturePanel';
import PMIPanel from './components/PMIPanel';
import MeasurementTools from './components/MeasurementTools';
import SectionCutPanel from './components/SectionCutPanel';
import MarkupPanel from './components/MarkupPanel';
import CAEViewer from './components/CAEViewer';
import CAEFileList from './components/CAEFileList';
import MeshFromStepDialog from './components/MeshFromStepDialog';

const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#90caf9' },
    secondary: { main: '#f48fb1' },
    background: { default: '#121212', paper: '#1e1e1e' },
  },
});

const SIDEBAR_WIDTH = 300;
const DETAILS_WIDTH = 350;

export default function App() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedEntityId, setSelectedEntityId] = useState(null);

  // ── Panel visibility ─────────────────────────────────────────────────────
  const [fileListOpen, setFileListOpen] = useState(true);
  const [entityTreeOpen, setEntityTreeOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [featurePanelOpen, setFeaturePanelOpen] = useState(false);
  const [pmiPanelOpen, setPmiPanelOpen] = useState(false);

  // ── CAE mode ─────────────────────────────────────────────────────────────
  const [caeMode, setCaeMode] = useState(true);
  const [meshDialogOpen, setMeshDialogOpen] = useState(false);
  const [selectedMesh, setSelectedMesh] = useState(null);
  const [measurementPanelOpen, setMeasurementPanelOpen] = useState(false);
  const [sectionCutOpen, setSectionCutOpen] = useState(false);
  const [markupOpen, setMarkupOpen] = useState(false);

  // ── 3D features state ────────────────────────────────────────────────────
  const [clippingPlane, setClippingPlane] = useState(null);

  // Picking mode: which input is requesting a 3D point
  const [pickingMode, setPickingMode] = useState(false);
  const [pickedPoint, setPickedPoint] = useState(null);

  // Measurements to render as 3D overlay
  const [measurements3D, setMeasurements3D] = useState([]);

  // PMI annotations to render as 3D labels
  const [pmiAnnotations, setPmiAnnotations] = useState([]);

  // Markup state
  const [markupActive, setMarkupActive] = useState(false);
  const [markupTool, setMarkupTool] = useState('pen');
  const [markupColor, setMarkupColor] = useState('#ff4444');
  const [markupStrokeWidth, setMarkupStrokeWidth] = useState(2);
  const [markupStrokes, setMarkupStrokes] = useState([]);

  // ── Handlers ─────────────────────────────────────────────────────────────

  function handleEntitySelect(entityId) {
    setSelectedEntityId(entityId);
    if (entityId && !detailsOpen) setDetailsOpen(true);
  }

  function handleFileSelect(file) {
    setSelectedFile(file);
    setSelectedEntityId(null);
    setDetailsOpen(false);
    setPickingMode(false);
    setPickedPoint(null);
    setMeasurements3D([]);
    setPmiAnnotations([]);
    setMarkupStrokes([]);
    if (file && !entityTreeOpen) setEntityTreeOpen(true);
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

  // Load PMI annotations when PMI panel opens
  useEffect(() => {
    if (!pmiPanelOpen || !selectedFile?.header_id) return;
    axios.get(`/api/step-view/pmi/${selectedFile.header_id}/list`)
      .then(res => setPmiAnnotations(res.data.annotations || []))
      .catch(() => {});
  }, [pmiPanelOpen, selectedFile]);

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
          caeMode={caeMode}
          onToggleCAE={() => { setCaeMode(!caeMode); setSelectedFile(null); setSelectedMesh(null); }}
        />

        {/* Left: File List */}
        <Drawer variant="persistent" anchor="left" open={fileListOpen}
          sx={{ width: SIDEBAR_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: SIDEBAR_WIDTH, boxSizing: 'border-box', mt: 8 } }}
        >
          {caeMode
            ? <CAEFileList onSelectMesh={setSelectedMesh} selectedMeshId={selectedMesh?.id} />
            : <FileList onSelectFile={handleFileSelect} selectedFileId={selectedFile?.id} />
          }
        </Drawer>

        {/* Main: 3D Viewer */}
        <Box component="main" sx={{
          position: 'fixed',
          top: '64px',
          left: fileListOpen ? `${SIDEBAR_WIDTH}px` : 0,
          right: 0,
          bottom: 0,
          overflow: 'hidden',
          transition: 'left 0.2s',
        }}>
          {caeMode ? (
            <CAEViewer mesh={selectedMesh} />
          ) : selectedFile ? (
            <StepViewer3D
              headerId={headerId}
              filename={selectedFile.original_filename}
              selectedEntityId={selectedEntityId}
              onEntitySelect={handleEntitySelect}
              pickingMode={pickingMode}
              onPointPicked={handlePointPicked}
              clippingPlane={clippingPlane}
              measurements={measurements3D}
              pmiAnnotations={pmiAnnotations}
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
          {selectedFile && !caeMode && (
            <Box sx={{ position: 'absolute', top: 16, right: detailsOpen ? DETAILS_WIDTH + 16 : 16, display: 'flex', gap: 1, transition: 'right 0.2s' }}>

              <Tooltip title="Manufacturing Features">
                <IconButton onClick={() => setFeaturePanelOpen(!featurePanelOpen)} sx={{ bgcolor: featurePanelOpen ? 'warning.main' : 'background.paper', '&:hover': { bgcolor: 'warning.dark' } }}>
                  <Build />
                </IconButton>
              </Tooltip>

              <Tooltip title="Entity Graph">
                <IconButton onClick={() => setEntityTreeOpen(!entityTreeOpen)} sx={{ bgcolor: entityTreeOpen ? 'primary.main' : 'background.paper', '&:hover': { bgcolor: 'primary.dark' } }}>
                  <AccountTree />
                </IconButton>
              </Tooltip>

              <Tooltip title="PMI Annotations">
                <IconButton onClick={() => setPmiPanelOpen(!pmiPanelOpen)} sx={{ bgcolor: pmiPanelOpen ? 'info.main' : 'background.paper', '&:hover': { bgcolor: 'info.dark' } }}>
                  <Straighten />
                </IconButton>
              </Tooltip>

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

              {selectedEntityId && (
                <Tooltip title="Entity Details">
                  <IconButton onClick={() => setDetailsOpen(!detailsOpen)} sx={{ bgcolor: detailsOpen ? 'secondary.main' : 'background.paper', '&:hover': { bgcolor: 'secondary.dark' } }}>
                    <Info />
                  </IconButton>
                </Tooltip>
              )}
            </Box>
          )}
        </Box>

        {/* ── Left drawers ──────────────────────────────────────────────── */}

        {selectedFile && !caeMode && (
          <Drawer variant="persistent" anchor="left" open={featurePanelOpen}
            sx={{ width: SIDEBAR_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: SIDEBAR_WIDTH, boxSizing: 'border-box', mt: 8, left: leftOffset(), zIndex: 1060, transition: 'left 0.2s' } }}
          >
            <Box sx={{ position: 'relative', height: '100%' }}>
              <IconButton onClick={() => setFeaturePanelOpen(false)} sx={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }} size="small"><Close /></IconButton>
              <FeaturePanel headerId={headerId} onFeatureSelect={handleEntitySelect} selectedFeatureId={null} />
            </Box>
          </Drawer>
        )}

        {/* ── Right drawers ─────────────────────────────────────────────── */}

        {selectedFile && (
          <Drawer variant="persistent" anchor="right" open={pmiPanelOpen}
            sx={{ width: SIDEBAR_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: SIDEBAR_WIDTH, boxSizing: 'border-box', mt: 8, zIndex: 1090 } }}
          >
            <Box sx={{ position: 'relative', height: '100%' }}>
              <IconButton onClick={() => setPmiPanelOpen(false)} sx={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }} size="small"><Close /></IconButton>
              <PMIPanel
                headerId={headerId}
                onAnnotationSelect={handleEntitySelect}
                onAnnotationsLoaded={setPmiAnnotations}
              />
            </Box>
          </Drawer>
        )}

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

        {selectedFile && (
          <Drawer variant="persistent" anchor="right" open={entityTreeOpen}
            sx={{ width: SIDEBAR_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: SIDEBAR_WIDTH, boxSizing: 'border-box', mt: 8, zIndex: 1100 } }}
          >
            <Box sx={{ position: 'relative', height: '100%' }}>
              <IconButton onClick={() => setEntityTreeOpen(false)} sx={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }} size="small"><Close /></IconButton>
              <EntityTree headerId={headerId} selectedEntityId={selectedEntityId} onEntitySelect={handleEntitySelect} />
            </Box>
          </Drawer>
        )}

        {selectedFile && selectedEntityId && (
          <Drawer variant="persistent" anchor="right" open={detailsOpen}
            sx={{ width: DETAILS_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: DETAILS_WIDTH, boxSizing: 'border-box', mt: 8, zIndex: 1200 } }}
          >
            <EntityDetails
              headerId={headerId}
              entityId={selectedEntityId}
              onClose={() => { setDetailsOpen(false); setSelectedEntityId(null); }}
              onEntityClick={handleEntitySelect}
            />
          </Drawer>
        )}

      </Box>

      <MeshFromStepDialog
        open={meshDialogOpen}
        onClose={() => setMeshDialogOpen(false)}
        stepFile={selectedFile}
        onMeshCreated={(newMesh) => {
          setSelectedMesh(newMesh);
          setCaeMode(true);
          setMeshDialogOpen(false);
        }}
      />

    </ThemeProvider>
  );
}
