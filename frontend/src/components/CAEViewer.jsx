import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box, Typography, CircularProgress, Alert, Slider, Button, Chip,
  Select, MenuItem, FormControl, InputLabel, Paper, Divider,
} from '@mui/material';
import axios from 'axios';

// Profile MUST be imported first — registers WebGL rendering classes
import '@kitware/vtk.js/Rendering/Profiles/Geometry';

import vtkRenderWindow from '@kitware/vtk.js/Rendering/Core/RenderWindow';
import vtkRenderer from '@kitware/vtk.js/Rendering/Core/Renderer';
import vtkRenderWindowInteractor from '@kitware/vtk.js/Rendering/Core/RenderWindowInteractor';
import vtkOpenGLRenderWindow from '@kitware/vtk.js/Rendering/OpenGL/RenderWindow';
import vtkInteractorStyleTrackballCamera from '@kitware/vtk.js/Interaction/Style/InteractorStyleTrackballCamera';

import vtkUnstructuredGrid from '@kitware/vtk.js/Common/DataModel/UnstructuredGrid.js';
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData.js';

import vtkPoints from '@kitware/vtk.js/Common/Core/Points.js';
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray.js';
import vtkLookupTable from '@kitware/vtk.js/Common/Core/LookupTable.js';

import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper.js';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor.js';

// meshio element type → VTK cell type constant
const CELL_TYPE = {
  vertex: 1,
  line: 3, line2: 3,
  triangle: 5, tri: 5, tri3: 5,
  triangle6: 22,
  quad: 9, quad4: 9,
  quad8: 23,
  tetra: 10, tet4: 10,
  tetra10: 24,
  hexahedron: 12, hex8: 12,
  hexahedron20: 25,
  wedge: 13, penta6: 13, prism6: 13,
  pyramid: 14,
};

const COLORMAPS = ['viridis', 'rainbow', 'coolwarm', 'jet', 'grayscale'];

const COLORMAP_CSS = {
  viridis:  'linear-gradient(to right, #440154, #31688e, #35b779, #fde725)',
  rainbow:  'linear-gradient(to right, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000)',
  jet:      'linear-gradient(to right, #000080, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000, #800000)',
  coolwarm: 'linear-gradient(to right, #3b4cc0, #dddddd, #b40426)',
  grayscale: 'linear-gradient(to right, #000000, #ffffff)',
};

const RISK_COLOR = { low: 'success', medium: 'warning', high: 'error' };

// ---------------------------------------------------------------------------
// VTK helpers
// ---------------------------------------------------------------------------

function buildLUT(name) {
  const lut = vtkLookupTable.newInstance();
  lut.setNumberOfColors(256);
  switch (name) {
    case 'rainbow':
      lut.setHueRange(0.667, 0.0); lut.setSaturationRange(1.0, 1.0); lut.setValueRange(1.0, 1.0); break;
    case 'jet':
      lut.setHueRange(0.667, 0.0); lut.setSaturationRange(1.0, 1.0); lut.setValueRange(0.9, 1.0); break;
    case 'coolwarm':
      lut.setHueRange(0.58, 0.02); lut.setSaturationRange(0.75, 0.75); lut.setValueRange(0.88, 0.88); break;
    case 'grayscale':
      lut.setHueRange(0.0, 0.0); lut.setSaturationRange(0.0, 0.0); lut.setValueRange(0.0, 1.0); break;
    default: // viridis
      lut.setHueRange(0.76, 0.10); lut.setSaturationRange(0.85, 0.90); lut.setValueRange(0.45, 0.95); break;
  }
  lut.build();
  return lut;
}

function buildUG(meshData, fieldData, warpScale = 0) {
  const ug = vtkUnstructuredGrid.newInstance();
  const nodes = meshData.nodes;
  const isVec = fieldData?.values?.length > 0 && Array.isArray(fieldData.values[0]);

  // Node coordinates, optionally warped by displacement
  const coords = new Float32Array(nodes.length * 3);
  nodes.forEach(([x, y, z], i) => {
    let dx = 0, dy = 0, dz = 0;
    if (warpScale > 0 && isVec) {
      const v = fieldData.values[i];
      if (v) { dx = v[0] * warpScale; dy = v[1] * warpScale; dz = v[2] * warpScale; }
    }
    coords[i * 3]     = x + dx;
    coords[i * 3 + 1] = y + dy;
    coords[i * 3 + 2] = z + dz;
  });
  const pts = vtkPoints.newInstance();
  pts.setData(coords, 3);
  ug.setPoints(pts);

  // Cell connectivity
  const flatCells = [];
  const cellTypeArr = [];
  for (const [etype, conns] of Object.entries(meshData.elements || {})) {
    const vtype = CELL_TYPE[etype];
    if (vtype == null) continue;
    for (const conn of conns) {
      flatCells.push(conn.length, ...conn);
      cellTypeArr.push(vtype);
    }
  }
  ug.getCells().setData(new Uint32Array(flatCells));
  ug.getCellTypes().setData(new Uint8Array(cellTypeArr));

  // Scalar field (magnitude for vectors)
  if (fieldData?.values?.length > 0) {
    const vals = fieldData.values;
    const scalars = new Float32Array(vals.length);
    if (isVec) {
      vals.forEach((v, i) => { scalars[i] = Math.sqrt(v.reduce((s, c) => s + c * c, 0)); });
    } else {
      vals.forEach((v, i) => { scalars[i] = v; });
    }
    const da = vtkDataArray.newInstance({ name: 'result', values: scalars, numberOfComponents: 1 });
    if (fieldData.field_type === 'nodal') {
      ug.getPointData().setScalars(da);
    } else {
      ug.getCellData().setScalars(da);
    }
  }

  return ug;
}

// Builds a vtkPolyData with one vertex cell per hotspot node (rendered as red spheres)
function buildHotspotActor(meshNodes, hotspotIndices) {
  const n = hotspotIndices.length;
  if (n === 0) return null;

  const coords = new Float32Array(n * 3);
  hotspotIndices.forEach((nodeIdx, i) => {
    const pt = meshNodes[nodeIdx];
    if (!pt) return;
    coords[i * 3]     = pt[0];
    coords[i * 3 + 1] = pt[1];
    coords[i * 3 + 2] = pt[2];
  });

  const pts = vtkPoints.newInstance();
  pts.setData(coords, 3);

  const pd = vtkPolyData.newInstance();
  pd.setPoints(pts);

  // [npts, idx0, npts, idx1, ...] for vertex cells
  const vertData = new Uint32Array(n * 2);
  for (let i = 0; i < n; i++) {
    vertData[i * 2]     = 1;
    vertData[i * 2 + 1] = i;
  }
  pd.getVerts().setData(vertData);

  const hMapper = vtkMapper.newInstance();
  hMapper.setInputData(pd);
  hMapper.setScalarVisibility(false);

  const hActor = vtkActor.newInstance();
  hActor.setMapper(hMapper);
  hActor.getProperty().setColor(1.0, 0.15, 0.1);
  hActor.getProperty().setPointSize(6);
  hActor.getProperty().setRenderPointsAsSpheres(true);

  return { pd, mapper: hMapper, actor: hActor };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CAEViewer({ mesh }) {
  const containerRef = useRef(null);
  const vtkRef      = useRef(null);
  // Tracks current colormap without triggering mesh rebuild in the field effect
  const colormapRef = useRef('viridis');

  const [meshData,       setMeshData]       = useState(null);
  const [fields,         setFields]         = useState([]);
  const [selectedField,  setSelectedField]  = useState('');
  const [fieldData,      setFieldData]      = useState(null);
  const [colormap,       setColormap]       = useState('viridis');
  const [warp,           setWarp]           = useState(0);
  const [hotspots,       setHotspots]       = useState(null);
  const [analyzing,      setAnalyzing]      = useState(false);
  const [loading,        setLoading]        = useState(false);
  const [error,          setError]          = useState(null);

  const isVector = fieldData != null && Array.isArray(fieldData.values?.[0]);

  // ── Data loading ───────────────────────────────────────────────────────────

  useEffect(() => {
    if (!mesh) {
      setMeshData(null); setFields([]); setFieldData(null);
      setSelectedField(''); setHotspots(null);
      return;
    }
    setLoading(true);
    setError(null);
    setFieldData(null);
    setSelectedField('');
    setHotspots(null);
    Promise.all([
      axios.get(`/api/cae/meshes/${mesh.id}`),
      axios.get(`/api/cae/meshes/${mesh.id}/fields`),
    ]).then(([meshRes, fieldsRes]) => {
      setMeshData(meshRes.data);
      const flds = fieldsRes.data.fields || [];
      setFields(flds);
      if (flds.length > 0) setSelectedField(flds[0].name);
    }).catch(e => setError(e.response?.data?.error || e.message))
      .finally(() => setLoading(false));
  }, [mesh]);

  useEffect(() => {
    if (!mesh || !selectedField) { setFieldData(null); setHotspots(null); return; }
    setHotspots(null);
    axios.get(`/api/cae/meshes/${mesh.id}/field/${selectedField}`)
      .then(res => setFieldData(res.data))
      .catch(e => console.error('Field load error:', e));
  }, [mesh, selectedField]);

  // ── vtk.js lifecycle ───────────────────────────────────────────────────────

  const teardown = useCallback(() => {
    if (!vtkRef.current) return;
    const { renderer, interactor, actor, mapper, ug, lut,
            renderWindow, glWindow, ro,
            hotspotActor, hotspotMapper, hotspotPd } = vtkRef.current;
    ro?.disconnect?.();
    interactor?.unbindEvents?.();
    interactor?.delete?.();
    if (hotspotActor) { renderer?.removeActor?.(hotspotActor); hotspotActor.delete(); }
    hotspotMapper?.delete?.();
    hotspotPd?.delete?.();
    actor?.delete?.();
    mapper?.delete?.();
    ug?.delete?.();
    lut?.delete?.();
    glWindow?.delete?.();
    renderWindow?.delete?.();
    vtkRef.current = null;
  }, []);

  // Build VTK pipeline when mesh geometry arrives
  useEffect(() => {
    if (!meshData || !containerRef.current) return;
    teardown();

    const container = containerRef.current;
    const renderWindow = vtkRenderWindow.newInstance();
    const renderer    = vtkRenderer.newInstance({ background: [0.07, 0.07, 0.07] });
    renderWindow.addRenderer(renderer);

    const glWindow = vtkOpenGLRenderWindow.newInstance();
    glWindow.setContainer(container);
    glWindow.setSize(container.offsetWidth, container.offsetHeight);
    renderWindow.addView(glWindow);

    const interactor = vtkRenderWindowInteractor.newInstance();
    interactor.setView(glWindow);
    interactor.setInteractorStyle(vtkInteractorStyleTrackballCamera.newInstance());
    interactor.initialize();
    interactor.bindEvents(container);

    const ug     = buildUG(meshData, null);
    const mapper = vtkMapper.newInstance();
    mapper.setInputData(ug);
    mapper.setScalarVisibility(false);
    const actor  = vtkActor.newInstance();
    actor.setMapper(mapper);
    actor.getProperty().setColor(0.62, 0.73, 0.86);
    renderer.addActor(actor);
    renderer.resetCamera();
    renderWindow.render();

    const ro = new ResizeObserver(() => {
      glWindow.setSize(container.offsetWidth, container.offsetHeight);
      renderWindow.render();
    });
    ro.observe(container);

    vtkRef.current = {
      renderWindow, renderer, glWindow, interactor,
      ug, mapper, actor, lut: null, ro,
      hotspotActor: null, hotspotMapper: null, hotspotPd: null,
    };

    return teardown;
  }, [meshData]);

  // Colormap change: update LUT only — no mesh rebuild
  useEffect(() => {
    colormapRef.current = colormap;
    if (!vtkRef.current?.mapper || !fieldData?.values?.length) return;
    const { mapper, renderWindow } = vtkRef.current;
    vtkRef.current.lut?.delete?.();
    const lut = buildLUT(colormap);
    mapper.setLookupTable(lut);
    vtkRef.current.lut = lut;
    renderWindow.render();
  }, [colormap]);

  // Field data or warp change: rebuild UG
  useEffect(() => {
    if (!vtkRef.current || !meshData) return;
    const { renderWindow, mapper, actor } = vtkRef.current;

    // Compute physical warp multiplier: at warp=1 the max displacement ≈ 20% of bounding box
    let actualWarp = 0;
    if (warp > 0 && isVector && fieldData?.data_max > 0 && meshData.bounding_box) {
      const b    = meshData.bounding_box;
      const diag = Math.hypot(b.max_x - b.min_x, b.max_y - b.min_y, b.max_z - b.min_z);
      actualWarp = warp * (diag / (fieldData.data_max * 5));
    }

    vtkRef.current.lut?.delete?.();
    vtkRef.current.lut = null;

    const newUg = buildUG(meshData, fieldData, actualWarp);
    mapper.setInputData(newUg);
    vtkRef.current.ug?.delete?.();
    vtkRef.current.ug = newUg;

    if (fieldData?.values?.length > 0) {
      const lut = buildLUT(colormapRef.current);
      mapper.setLookupTable(lut);
      mapper.setScalarRange(fieldData.data_min, fieldData.data_max);
      mapper.setScalarVisibility(true);
      mapper.setColorByArrayName('result');
      if (fieldData.field_type === 'nodal') {
        mapper.setScalarModeToUsePointData();
      } else {
        mapper.setScalarModeToUseCellData();
      }
      vtkRef.current.lut = lut;
    } else {
      mapper.setScalarVisibility(false);
      actor.getProperty().setColor(0.62, 0.73, 0.86);
    }

    renderWindow.render();
  }, [meshData, fieldData, warp, isVector]);

  // Hotspot overlay: add/remove red point actor
  useEffect(() => {
    if (!vtkRef.current) return;
    const { renderer, renderWindow } = vtkRef.current;

    if (vtkRef.current.hotspotActor) {
      renderer.removeActor(vtkRef.current.hotspotActor);
      vtkRef.current.hotspotActor.delete();
      vtkRef.current.hotspotMapper?.delete?.();
      vtkRef.current.hotspotPd?.delete?.();
      vtkRef.current.hotspotActor  = null;
      vtkRef.current.hotspotMapper = null;
      vtkRef.current.hotspotPd     = null;
    }

    if (hotspots?.indices?.length > 0 && meshData?.nodes) {
      const result = buildHotspotActor(meshData.nodes, hotspots.indices);
      if (result) {
        renderer.addActor(result.actor);
        vtkRef.current.hotspotActor  = result.actor;
        vtkRef.current.hotspotMapper = result.mapper;
        vtkRef.current.hotspotPd     = result.pd;
      }
    }

    renderWindow?.render?.();
  }, [hotspots, meshData]);

  // ── AI analysis ────────────────────────────────────────────────────────────

  const analyzeAI = useCallback(async () => {
    if (!fieldData?.values?.length) return;
    setAnalyzing(true);
    setError(null);
    try {
      const res = await axios.post('/api/cae/ai/analyze', {
        values:     fieldData.values,
        field_type: fieldData.field_type,
      });
      setHotspots({
        indices:       res.data.hotspot_indices,
        count:         res.data.hotspot_count,
        risk:          res.data.risk_level,
        recommendation: res.data.recommendation,
        stats:         res.data.statistics,
        concentration: res.data.concentration_ratio,
      });
    } catch (e) {
      setError(e.response?.data?.error || 'AI analysis failed');
    } finally {
      setAnalyzing(false);
    }
  }, [fieldData]);

  // ── Render ─────────────────────────────────────────────────────────────────

  if (!mesh) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'text.secondary' }}>
        <div style={{ textAlign: 'center' }}>
          <Typography variant="h6" gutterBottom>Modo CAE / FEA</Typography>
          <Typography variant="body2">Selecciona una malla en el panel izquierdo</Typography>
          <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 1 }}>
            Formatos: VTK, Abaqus .inp, Nastran .bdf, GMSH .msh, MED, Exodus…
          </Typography>
        </div>
      </Box>
    );
  }

  return (
    <Box sx={{ height: '100%', position: 'relative', bgcolor: '#111' }}>

      {/* Controls panel */}
      <Paper sx={{
        position: 'absolute', top: 16, right: 16, zIndex: 10,
        p: 2, minWidth: 230, maxWidth: 270,
        bgcolor: 'rgba(18,18,18,0.93)', backdropFilter: 'blur(8px)',
      }}>
        <Typography variant="subtitle2" gutterBottom noWrap sx={{ maxWidth: 220 }}>
          {mesh.original_filename}
        </Typography>

        {meshData && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            {meshData.node_count?.toLocaleString()} nodos · {meshData.element_count?.toLocaleString()} elementos
          </Typography>
        )}

        {meshData && Object.keys(meshData.elements || {}).length > 0 && (
          <Typography variant="caption" color="text.disabled" display="block" sx={{ mb: 1 }}>
            {Object.entries(meshData.elements).map(([t, c]) => `${t}(${c.length})`).join(' · ')}
          </Typography>
        )}

        <Divider sx={{ my: 1 }} />

        {fields.length > 0 && (
          <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
            <InputLabel>Campo</InputLabel>
            <Select value={selectedField} onChange={e => setSelectedField(e.target.value)} label="Campo">
              <MenuItem value=""><em>Sin campo</em></MenuItem>
              {fields.map(f => (
                <MenuItem key={f.name} value={f.name}>
                  {f.name} ({f.field_type === 'nodal' ? 'nod.' : 'elem.'})
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}

        <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
          <InputLabel>Colormap</InputLabel>
          <Select value={colormap} onChange={e => setColormap(e.target.value)} label="Colormap">
            {COLORMAPS.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}
          </Select>
        </FormControl>

        {/* Colorbar */}
        {fieldData?.values?.length > 0 && (
          <Box sx={{ mb: 1.5 }}>
            <div style={{
              height: 12, borderRadius: 3,
              background: COLORMAP_CSS[colormap] || COLORMAP_CSS.viridis,
              marginBottom: 3,
            }} />
            <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
              <Typography variant="caption" color="text.secondary">
                {fieldData.data_min?.toExponential(2)}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {fieldData.data_max?.toExponential(2)}
              </Typography>
            </Box>
            {isVector && (
              <Typography variant="caption" color="info.main" display="block" sx={{ mt: 0.5 }}>
                magnitud vectorial
              </Typography>
            )}
          </Box>
        )}

        {/* Warp deformation — vector fields only */}
        {isVector && (
          <>
            <Divider sx={{ mb: 1 }} />
            <Typography variant="caption" color="text.secondary">
              Deformación: {warp > 0 ? `×${warp.toFixed(2)}` : 'off'}
            </Typography>
            <Slider
              value={warp}
              onChange={(_, v) => setWarp(v)}
              min={0} max={1} step={0.05}
              size="small"
              sx={{ mb: 1 }}
            />
          </>
        )}

        <Divider sx={{ mb: 1 }} />

        {/* AI analysis */}
        <Button
          fullWidth
          size="small"
          variant="outlined"
          disabled={!fieldData?.values?.length || analyzing}
          onClick={analyzeAI}
          sx={{ mb: hotspots ? 1.5 : 0 }}
        >
          {analyzing && <CircularProgress size={12} sx={{ mr: 1 }} />}
          {analyzing ? 'Analizando…' : 'Analizar IA'}
        </Button>

        {hotspots && (
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
              <Chip
                label={hotspots.risk}
                color={RISK_COLOR[hotspots.risk] || 'default'}
                size="small"
              />
              <Typography variant="caption" color="text.secondary">
                {hotspots.count.toLocaleString()} hotspots
              </Typography>
            </Box>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
              {(hotspots.concentration * 100).toFixed(1)}% nodos críticos
            </Typography>
            <Typography variant="caption" color="text.disabled" display="block" sx={{ lineHeight: 1.4 }}>
              {hotspots.recommendation}
            </Typography>
          </Box>
        )}
      </Paper>

      {loading && (
        <Box sx={{
          position: 'absolute', inset: 0, display: 'flex',
          alignItems: 'center', justifyContent: 'center', zIndex: 5,
          bgcolor: 'rgba(0,0,0,0.55)',
        }}>
          <CircularProgress />
        </Box>
      )}

      {error && (
        <Box sx={{ position: 'absolute', top: 16, left: 16, zIndex: 5, maxWidth: 420 }}>
          <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>
        </Box>
      )}

      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </Box>
  );
}
