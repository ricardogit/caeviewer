import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  Box, Typography, CircularProgress, Alert, Slider, Button, Chip,
  Select, MenuItem, FormControl, InputLabel, Paper, Divider,
  IconButton, Tooltip, ToggleButton, ToggleButtonGroup,
} from '@mui/material';
import { GridOn, GpsFixed, Close, PlayArrow, Pause, SkipPrevious, SkipNext, ContentCut, CameraAlt, TableChart, FileDownload } from '@mui/icons-material';
import axios from 'axios';

// Profile MUST be imported first — registers WebGL rendering classes
import '@kitware/vtk.js/Rendering/Profiles/Geometry';

import vtkRenderWindow from '@kitware/vtk.js/Rendering/Core/RenderWindow';
import vtkRenderer from '@kitware/vtk.js/Rendering/Core/Renderer';
import vtkRenderWindowInteractor from '@kitware/vtk.js/Rendering/Core/RenderWindowInteractor';
import vtkOpenGLRenderWindow from '@kitware/vtk.js/Rendering/OpenGL/RenderWindow';
import vtkInteractorStyleTrackballCamera from '@kitware/vtk.js/Interaction/Style/InteractorStyleTrackballCamera';

import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData';
import vtkPoints from '@kitware/vtk.js/Common/Core/Points';
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray';
import vtkLookupTable from '@kitware/vtk.js/Common/Core/LookupTable';

import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkLight from '@kitware/vtk.js/Rendering/Core/Light';
import vtkPlane from '@kitware/vtk.js/Common/DataModel/Plane';

const COLORMAPS = ['viridis', 'rainbow', 'coolwarm', 'jet', 'grayscale'];

// 20 perceptually distinct colors for per-part rendering
const PART_COLORS = [
  [0.62, 0.73, 0.86], [0.96, 0.49, 0.31], [0.45, 0.77, 0.45], [0.95, 0.85, 0.36],
  [0.75, 0.50, 0.75], [0.29, 0.75, 0.85], [0.95, 0.36, 0.36], [0.60, 0.80, 0.60],
  [0.80, 0.60, 0.40], [0.60, 0.60, 0.80], [0.90, 0.70, 0.40], [0.40, 0.80, 0.80],
  [0.80, 0.40, 0.60], [0.50, 0.70, 0.90], [0.90, 0.60, 0.80], [0.70, 0.90, 0.50],
  [0.40, 0.60, 0.80], [0.80, 0.80, 0.40], [0.60, 0.40, 0.80], [0.40, 0.80, 0.60],
];

const COLORMAP_CSS = {
  viridis:  'linear-gradient(to right, #440154, #31688e, #35b779, #fde725)',
  rainbow:  'linear-gradient(to right, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000)',
  jet:      'linear-gradient(to right, #000080, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000, #800000)',
  coolwarm: 'linear-gradient(to right, #3b4cc0, #dddddd, #b40426)',
  grayscale: 'linear-gradient(to right, #000000, #ffffff)',
};

const RISK_COLOR = { low: 'success', medium: 'warning', high: 'error' };

// ---------------------------------------------------------------------------
// Statistics helpers
// ---------------------------------------------------------------------------

function computeHistogram(mags, min, max, bins) {
  const counts = new Array(bins).fill(0);
  const range = max - min;
  if (range === 0) { counts[0] = mags.length; return counts; }
  for (const v of mags) {
    const b = Math.min(bins - 1, Math.floor(((v - min) / range) * bins));
    counts[b]++;
  }
  return counts;
}

function MiniHistogram({ counts }) {
  const peak = Math.max(...counts, 1);
  const h = 44;
  const w = 4;
  const gap = 1;
  return (
    <svg width={counts.length * (w + gap)} height={h} style={{ display: 'block', overflow: 'visible' }}>
      {counts.map((c, i) => {
        const bh = (c / peak) * h;
        return (
          <rect key={i} x={i * (w + gap)} y={h - bh} width={w} height={bh}
            fill="#4fc3f7" opacity={0.75} rx={1} />
        );
      })}
    </svg>
  );
}

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

function buildSurfacePD(meshData, fieldData, warpScale = 0, triSubset = null) {
  const pd = vtkPolyData.newInstance();
  const allNodes = meshData.nodes;
  const nNodes = allNodes.length;
  const triangles = triSubset !== null ? triSubset : (meshData.surface_triangles || []);
  const isVec = fieldData?.values?.length > 0 && Array.isArray(fieldData.values[0]);

  // Build compact points array from only surface-referenced nodes.
  // Interior nodes are excluded so VTK.js actor bounds (and initial camera)
  // are derived from the visible surface, not the full node cloud.
  // Guard: TypedArray out-of-bounds returns undefined in JS (not -1),
  // so we check idx range explicitly before touching remap.
  const remap = new Int32Array(nNodes).fill(-1);
  const surfOld = [];  // surfOld[newIdx] = originalIdx
  for (const tri of triangles) {
    for (const idx of tri) {
      if (idx < 0 || idx >= nNodes) continue;   // guard invalid indices
      if (remap[idx] < 0) { remap[idx] = surfOld.length; surfOld.push(idx); }
    }
  }

  // nodeMap[compact_idx] = original_idx — needed for field/warp value lookups
  // because field data from the server is still indexed by original node position.
  const nodeMap = meshData.node_map || null;
  const coords = new Float32Array(surfOld.length * 3);
  for (let i = 0; i < surfOld.length; i++) {
    const compactIdx = surfOld[i];
    const [x, y, z] = allNodes[compactIdx];
    let dx = 0, dy = 0, dz = 0;
    if (warpScale > 0 && isVec) {
      const origIdx = nodeMap ? nodeMap[compactIdx] : compactIdx;
      const v = fieldData.values[origIdx];
      if (v) { dx = v[0] * warpScale; dy = v[1] * warpScale; dz = v[2] * warpScale; }
    }
    coords[i * 3]     = x + dx;
    coords[i * 3 + 1] = y + dy;
    coords[i * 3 + 2] = z + dz;
  }
  const pts = vtkPoints.newInstance();
  pts.setData(coords, 3);
  pd.setPoints(pts);

  // Triangle connectivity — skip any triangle whose remapped index is -1
  // (out-of-range or missing node).
  const polyBuf = [];
  for (const tri of triangles) {
    const a = (tri[0] >= 0 && tri[0] < nNodes) ? remap[tri[0]] : -1;
    const b = (tri[1] >= 0 && tri[1] < nNodes) ? remap[tri[1]] : -1;
    const c = (tri[2] >= 0 && tri[2] < nNodes) ? remap[tri[2]] : -1;
    if (a < 0 || b < 0 || c < 0) continue;
    polyBuf.push(3, a, b, c);
  }
  pd.getPolys().setData(new Uint32Array(polyBuf));

  // Scalar field — look up values by original (pre-compaction) node index.
  // nodeMap is already declared above; reuse it here for field data alignment.
  if (fieldData?.values?.length > 0) {
    const vals = fieldData.values;
    const scalars = new Float32Array(surfOld.length);
    if (isVec) {
      for (let i = 0; i < surfOld.length; i++) {
        const origIdx = nodeMap ? nodeMap[surfOld[i]] : surfOld[i];
        const v = vals[origIdx];
        if (v) scalars[i] = Math.sqrt(v.reduce((s, c) => s + c * c, 0));
      }
    } else {
      for (let i = 0; i < surfOld.length; i++) {
        const origIdx = nodeMap ? nodeMap[surfOld[i]] : surfOld[i];
        scalars[i] = vals[origIdx] ?? 0;
      }
    }
    const da = vtkDataArray.newInstance({ name: 'result', values: scalars, numberOfComponents: 1 });
    pd.getPointData().setScalars(da);
  }

  return pd;
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

// Build a world-space ray from a mouse event using camera math (no vtk.js picker).
function screenToWorldRay(e, container, renderer) {
  const rect = container.getBoundingClientRect();
  const ndcX =  ((e.clientX - rect.left) / rect.width)  * 2 - 1;
  const ndcY = -((e.clientY - rect.top)  / rect.height) * 2 + 1;

  const camera = renderer.getActiveCamera();
  const pos    = camera.getPosition();
  const focal  = camera.getFocalPoint();
  const viewUp = camera.getViewUp();

  // view direction (−Z of camera space)
  const vd = [focal[0]-pos[0], focal[1]-pos[1], focal[2]-pos[2]];
  const vl = Math.sqrt(vd[0]**2+vd[1]**2+vd[2]**2);
  vd[0]/=vl; vd[1]/=vl; vd[2]/=vl;

  // right = vd × up
  const r = [
    vd[1]*viewUp[2]-vd[2]*viewUp[1],
    vd[2]*viewUp[0]-vd[0]*viewUp[2],
    vd[0]*viewUp[1]-vd[1]*viewUp[0],
  ];
  const rl = Math.sqrt(r[0]**2+r[1]**2+r[2]**2);
  r[0]/=rl; r[1]/=rl; r[2]/=rl;

  // up = r × vd
  const u = [r[1]*vd[2]-r[2]*vd[1], r[2]*vd[0]-r[0]*vd[2], r[0]*vd[1]-r[1]*vd[0]];

  const tanH   = Math.tan((camera.getViewAngle() * Math.PI / 180) / 2);
  const aspect = rect.width / rect.height;

  const dir = [
    vd[0] + ndcX*tanH*aspect*r[0] + ndcY*tanH*u[0],
    vd[1] + ndcX*tanH*aspect*r[1] + ndcY*tanH*u[1],
    vd[2] + ndcX*tanH*aspect*r[2] + ndcY*tanH*u[2],
  ];
  const dl = Math.sqrt(dir[0]**2+dir[1]**2+dir[2]**2);
  return { origin: [...pos], direction: [dir[0]/dl, dir[1]/dl, dir[2]/dl] };
}

function findNearestNodeToRay(nodes, origin, direction) {
  let minD = Infinity, idx = -1;
  for (let i = 0; i < nodes.length; i++) {
    const [px, py, pz] = nodes[i];
    const vx = px-origin[0], vy = py-origin[1], vz = pz-origin[2];
    const t  = vx*direction[0] + vy*direction[1] + vz*direction[2];
    if (t < 0) continue; // behind camera
    const cx = origin[0]+t*direction[0], cy = origin[1]+t*direction[1], cz = origin[2]+t*direction[2];
    const d  = (px-cx)**2 + (py-cy)**2 + (pz-cz)**2;
    if (d < minD) { minD = d; idx = i; }
  }
  return idx;
}

// ---------------------------------------------------------------------------
// Camera helpers
// ---------------------------------------------------------------------------

/**
 * Apply a named camera preset to a VTK renderer.
 * preset: 'iso' | '+x' | '-x' | '+y' | '-y' | '+z' | '-z'
 * bbox: { min_x, max_x, min_y, max_y, min_z, max_z }
 *
 * Strategy: set direction (unit offset from scene center), then call resetCamera()
 * which repositions the camera along that direction at the correct fit distance.
 */
function applyCameraPreset(renderer, renderWindow, preset, bbox) {
  if (!bbox) return;
  const cx = (bbox.min_x + bbox.max_x) / 2;
  const cy = (bbox.min_y + bbox.max_y) / 2;
  const cz = (bbox.min_z + bbox.max_z) / 2;

  const camera = renderer.getActiveCamera();
  camera.setFocalPoint(cx, cy, cz);

  // Place camera in the desired direction (distance doesn't matter — resetCamera fixes it)
  switch (preset) {
    case '+x': camera.setPosition(cx + 1, cy,     cz    ); camera.setViewUp(0, 1,  0); break;
    case '-x': camera.setPosition(cx - 1, cy,     cz    ); camera.setViewUp(0, 1,  0); break;
    case '+y': camera.setPosition(cx,     cy + 1, cz    ); camera.setViewUp(0, 0, -1); break;
    case '-y': camera.setPosition(cx,     cy - 1, cz    ); camera.setViewUp(0, 0,  1); break;
    case '+z': camera.setPosition(cx,     cy,     cz + 1); camera.setViewUp(0, 1,  0); break;
    case '-z': camera.setPosition(cx,     cy,     cz - 1); camera.setViewUp(0, 1,  0); break;
    default: // 'iso' — equal components, above-right-front
      camera.setPosition(cx + 1, cy + 1, cz + 1); camera.setViewUp(0, 1, 0); break;
  }
  // resetCamera() recomputes distance along the current direction to fit all actors
  renderer.resetCamera();
  renderWindow.render();
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
  const [wireframe,      setWireframe]      = useState(false);
  const [pickMode,       setPickMode]       = useState(false);
  const [pickedNode,     setPickedNode]     = useState(null);
  const [timeSteps,      setTimeSteps]      = useState([0]);
  const [currentStep,    setCurrentStep]    = useState(0);
  const [playing,        setPlaying]        = useState(false);
  const [clipEnabled,    setClipEnabled]    = useState(false);
  const [clipAxis,       setClipAxis]       = useState('X');
  const [clipPos,        setClipPos]        = useState(0.5);
  const [clipFlip,       setClipFlip]       = useState(false);
  const [statsOpen,      setStatsOpen]      = useState(false);
  const [threshold,      setThreshold]      = useState([0, 1]);
  const [solversOpen,    setSolversOpen]    = useState(false);
  const [partsOpen,      setPartsOpen]      = useState(false);
  const [partsVisible,   setPartsVisible]   = useState([]);
  const pickModeRef  = useRef(false);
  const mouseDragRef = useRef({ x: 0, y: 0 });
  const playTimerRef = useRef(null);

  const isVector = fieldData != null && Array.isArray(fieldData.values?.[0]);

  const stats = useMemo(() => {
    if (!fieldData?.values?.length) return null;
    const vals = fieldData.values;
    const mags = isVector
      ? vals.map(v => Math.sqrt(v.reduce((s, c) => s + c * c, 0)))
      : vals.slice();
    const n = mags.length;
    const sorted = [...mags].sort((a, b) => a - b);
    const mean = mags.reduce((s, v) => s + v, 0) / n;
    const std  = Math.sqrt(mags.reduce((s, v) => s + (v - mean) ** 2, 0) / n);
    const pct  = (p) => sorted[Math.min(n - 1, Math.floor(p * n))];
    return {
      n, mean, std,
      min: sorted[0], max: sorted[n - 1],
      p5: pct(0.05), p25: pct(0.25), p50: pct(0.50), p75: pct(0.75), p95: pct(0.95),
      histogram: computeHistogram(mags, sorted[0], sorted[n - 1], 24),
    };
  }, [fieldData, isVector]);

  // ── Data loading ───────────────────────────────────────────────────────────

  useEffect(() => {
    if (!mesh) {
      setMeshData(null); setFields([]); setFieldData(null);
      setSelectedField(''); setHotspots(null);
      setTimeSteps([0]); setCurrentStep(0); setPlaying(false);
      return;
    }
    const ctrl = new AbortController();
    setMeshData(null);
    setLoading(true);
    setError(null);
    setFieldData(null);
    setSelectedField('');
    setHotspots(null);
    setCurrentStep(0);
    setPlaying(false);
    setClipEnabled(false);
    setClipPos(0.5);
    setClipFlip(false);
    Promise.all([
      axios.get(`/api/cae/meshes/${mesh.id}`,        { signal: ctrl.signal }),
      axios.get(`/api/cae/meshes/${mesh.id}/fields`,  { signal: ctrl.signal }),
    ]).then(([meshRes, fieldsRes]) => {
      setMeshData(meshRes.data);
      setTimeSteps(meshRes.data.time_steps || [0]);
      const nparts = meshRes.data.parts?.length || 0;
      setPartsVisible(nparts > 0 ? meshRes.data.parts.map(() => true) : []);
      const flds = fieldsRes.data.fields || [];
      setFields(flds);
      if (flds.length > 0) setSelectedField(flds[0].name);
    }).catch(e => {
      if (axios.isCancel(e)) return;
      setError(e.response?.data?.error || e.message);
    }).finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [mesh]);

  useEffect(() => {
    if (!mesh || !selectedField) { setFieldData(null); setHotspots(null); return; }
    const ctrl = new AbortController();
    setHotspots(null);
    setThreshold([0, 1]);
    axios.get(`/api/cae/meshes/${mesh.id}/field/${selectedField}?step=${currentStep}`,
              { signal: ctrl.signal })
      .then(res => setFieldData(res.data))
      .catch(e => { if (!axios.isCancel(e)) console.error('Field load error:', e); });
    return () => ctrl.abort();
  }, [mesh, selectedField, currentStep]);

  // ── vtk.js lifecycle ───────────────────────────────────────────────────────

  // Create WebGL context ONCE on mount — never destroy it between mesh switches.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const renderWindow = vtkRenderWindow.newInstance();
    const renderer    = vtkRenderer.newInstance({ background: [0.14, 0.14, 0.16] });
    renderWindow.addRenderer(renderer);

    // Two-light setup: headlight + fill from below. Adding any light disables the
    // auto headlight, so both must be explicit.
    const keyLight = vtkLight.newInstance();
    keyLight.setLightTypeToHeadLight();
    keyLight.setIntensity(0.8);
    const fillLight = vtkLight.newInstance();
    fillLight.setLightTypeToCameraLight();
    fillLight.setPosition(0.2, -0.8, 0.5);   // below-right in camera space
    fillLight.setFocalPoint(0, 0, 0);
    fillLight.setIntensity(0.3);
    renderer.addLight(keyLight);
    renderer.addLight(fillLight);

    const glWindow = vtkOpenGLRenderWindow.newInstance();
    glWindow.setContainer(container);
    glWindow.setSize(container.offsetWidth, container.offsetHeight);
    renderWindow.addView(glWindow);

    const interactor = vtkRenderWindowInteractor.newInstance();
    interactor.setView(glWindow);
    interactor.setInteractorStyle(vtkInteractorStyleTrackballCamera.newInstance());
    interactor.initialize();
    interactor.bindEvents(container);

    const ro = new ResizeObserver(() => {
      glWindow.setSize(container.offsetWidth, container.offsetHeight);
      renderWindow.render();
    });
    ro.observe(container);

    vtkRef.current = {
      renderWindow, renderer, glWindow, interactor, ro,
      actors: [],   // [{actor, mapper, pd, name, part}]
      lut: null,
      hotspotActor: null, hotspotMapper: null, hotspotPd: null,
    };

    return () => {
      ro.disconnect();
      interactor.unbindEvents();
      interactor.delete();
      const v = vtkRef.current;
      if (v) {
        if (v.hotspotActor) { renderer.removeActor(v.hotspotActor); v.hotspotActor.delete(); }
        v.hotspotMapper?.delete(); v.hotspotPd?.delete();
        (v.actors || []).forEach(a => {
          renderer.removeActor(a.actor); a.actor.delete();
          a.mapper?.delete(); a.pd?.delete();
        });
        v.lut?.delete?.();
      }
      glWindow.delete();
      renderWindow.delete();
      vtkRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Swap geometry when mesh data changes — create one actor per part when available.
  useEffect(() => {
    if (!vtkRef.current) return;
    const { renderer, renderWindow } = vtkRef.current;

    // Remove hotspot overlay
    if (vtkRef.current.hotspotActor) {
      renderer.removeActor(vtkRef.current.hotspotActor);
      vtkRef.current.hotspotActor.delete();
      vtkRef.current.hotspotMapper?.delete();
      vtkRef.current.hotspotPd?.delete();
      vtkRef.current.hotspotActor = null;
      vtkRef.current.hotspotMapper = null;
      vtkRef.current.hotspotPd = null;
    }
    // Remove previous geometry actors
    (vtkRef.current.actors || []).forEach(a => {
      renderer.removeActor(a.actor); a.actor.delete();
      a.mapper?.delete(); a.pd?.delete();
    });
    vtkRef.current.lut?.delete?.();
    vtkRef.current.actors = [];
    vtkRef.current.lut = null;

    if (!meshData) { renderWindow.render(); return; }

    const parts = meshData.parts || [];
    const useParts = parts.length > 1;
    const tris = meshData.surface_triangles || [];

    const newActors = useParts
      ? parts.map((part, i) => {
          const partTris = tris.slice(part.tri_start, part.tri_start + part.tri_count);
          const pd = buildSurfacePD(meshData, null, 0, partTris);
          const mapper = vtkMapper.newInstance();
          mapper.setInputData(pd);
          mapper.setScalarVisibility(false);
          const actor = vtkActor.newInstance();
          actor.setMapper(mapper);
          const prop = actor.getProperty();
          const color = PART_COLORS[i % PART_COLORS.length];
          prop.setColor(...color);
          prop.setAmbient(0.12); prop.setSpecular(0.35); prop.setSpecularPower(25);
          renderer.addActor(actor);
          return { actor, mapper, pd, name: part.name, part };
        })
      : (() => {
          const pd = buildSurfacePD(meshData, null);
          const mapper = vtkMapper.newInstance();
          mapper.setInputData(pd);
          mapper.setScalarVisibility(false);
          const actor = vtkActor.newInstance();
          actor.setMapper(mapper);
          const prop = actor.getProperty();
          prop.setColor(0.62, 0.73, 0.86);
          prop.setAmbient(0.12); prop.setSpecular(0.35); prop.setSpecularPower(25);
          renderer.addActor(actor);
          return [{ actor, mapper, pd, name: 'mesh', part: null }];
        })();

    vtkRef.current.actors = newActors;
    applyCameraPreset(renderer, renderWindow, 'iso', meshData.bounding_box);
  }, [meshData]);

  // Colormap change: update LUT only — no mesh rebuild
  useEffect(() => {
    colormapRef.current = colormap;
    if (!vtkRef.current?.actors?.length || !fieldData?.values?.length) return;
    const { actors, renderWindow } = vtkRef.current;
    vtkRef.current.lut?.delete?.();
    const lut = buildLUT(colormap);
    actors.forEach(a => a.mapper.setLookupTable(lut));
    vtkRef.current.lut = lut;
    renderWindow.render();
  }, [colormap]);

  // Wireframe overlay toggle
  useEffect(() => {
    if (!vtkRef.current?.actors?.length) return;
    const { actors, renderWindow } = vtkRef.current;
    actors.forEach(a => {
      const prop = a.actor.getProperty();
      prop.setEdgeVisibility(wireframe);
      if (wireframe) { prop.setEdgeColor(0.08, 0.08, 0.08); prop.setLineWidth(0.8); }
    });
    renderWindow.render();
  }, [wireframe]);

  // Per-part visibility toggle
  useEffect(() => {
    if (!vtkRef.current?.actors?.length) return;
    const { actors, renderWindow } = vtkRef.current;
    actors.forEach((a, i) => a.actor.setVisibility(partsVisible[i] !== false));
    renderWindow.render();
  }, [partsVisible]);

  // Keep ref in sync so the click handler always sees the latest value
  useEffect(() => { pickModeRef.current = pickMode; }, [pickMode]);

  // Play animation — advance one step every 300 ms
  useEffect(() => {
    if (!playing || timeSteps.length <= 1) return;
    playTimerRef.current = setInterval(() => {
      setCurrentStep(s => {
        const next = s + 1;
        if (next >= timeSteps.length) { setPlaying(false); return 0; }
        return next;
      });
    }, 300);
    return () => clearInterval(playTimerRef.current);
  }, [playing, timeSteps.length]);

  // Section cut — clipping plane on all mappers
  useEffect(() => {
    if (!vtkRef.current?.actors?.length || !meshData?.bounding_box) return;
    const { actors, renderWindow } = vtkRef.current;
    actors.forEach(a => a.mapper.removeAllClippingPlanes());

    if (clipEnabled) {
      const b = meshData.bounding_box;
      const axes = {
        X: { min: b.min_x, max: b.max_x, normal: [1, 0, 0] },
        Y: { min: b.min_y, max: b.max_y, normal: [0, 1, 0] },
        Z: { min: b.min_z, max: b.max_z, normal: [0, 0, 1] },
      };
      const { min, max, normal } = axes[clipAxis];
      const pos = min + clipPos * (max - min);
      const origin = clipAxis === 'X' ? [pos, 0, 0] : clipAxis === 'Y' ? [0, pos, 0] : [0, 0, pos];
      const n = clipFlip ? normal.map(v => -v) : normal;
      actors.forEach(a => {
        const plane = vtkPlane.newInstance();
        plane.setOrigin(...origin);
        plane.setNormal(...n);
        a.mapper.addClippingPlane(plane);
      });
    }

    renderWindow.render();
  }, [clipEnabled, clipAxis, clipPos, clipFlip, meshData]);

  // Threshold: remap scalar range on all mappers
  useEffect(() => {
    if (!vtkRef.current?.actors?.length || !fieldData?.values?.length) return;
    const { actors, renderWindow } = vtkRef.current;
    const dMin = fieldData.data_min;
    const dMax = fieldData.data_max;
    const lo = dMin + threshold[0] * (dMax - dMin);
    const hi = dMin + threshold[1] * (dMax - dMin);
    actors.forEach(a => a.mapper.setScalarRange(lo === hi ? lo - 1e-10 : lo, hi));
    renderWindow.render();
  }, [threshold, fieldData]);

  // Field data or warp change: rebuild per-part polydata
  useEffect(() => {
    if (!vtkRef.current || !meshData) return;
    const { renderWindow, actors } = vtkRef.current;
    if (!actors?.length) return;

    let actualWarp = 0;
    if (warp > 0 && isVector && meshData.bounding_box) {
      const absMax = Math.abs(fieldData?.data_max ?? 0);
      if (absMax > 0) {
        const b    = meshData.bounding_box;
        const diag = Math.hypot(b.max_x - b.min_x, b.max_y - b.min_y, b.max_z - b.min_z);
        actualWarp = warp * (diag / (absMax * 5));
      }
    }

    vtkRef.current.lut?.delete?.();
    vtkRef.current.lut = null;

    const parts = meshData.parts || [];
    const useParts = parts.length > 1;
    const tris = meshData.surface_triangles || [];

    actors.forEach((a, i) => {
      const triSubset = useParts && a.part
        ? tris.slice(a.part.tri_start, a.part.tri_start + a.part.tri_count)
        : null;
      const newPd = buildSurfacePD(meshData, fieldData, actualWarp, triSubset);
      a.mapper.setInputData(newPd);
      a.pd?.delete?.();
      a.pd = newPd;
    });

    if (fieldData?.values?.length > 0) {
      const lut = buildLUT(colormapRef.current);
      actors.forEach(a => {
        a.mapper.setLookupTable(lut);
        a.mapper.setScalarRange(fieldData.data_min, fieldData.data_max);
        a.mapper.setScalarVisibility(true);
        a.mapper.setColorByArrayName('result');
        a.mapper.setScalarModeToUsePointData();
      });
      vtkRef.current.lut = lut;
    } else {
      actors.forEach((a, i) => {
        a.mapper.setScalarVisibility(false);
        const color = useParts ? PART_COLORS[i % PART_COLORS.length] : [0.62, 0.73, 0.86];
        a.actor.getProperty().setColor(...color);
      });
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

  // ── Picking ────────────────────────────────────────────────────────────────

  const handleMouseDown = useCallback((e) => {
    mouseDragRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleContainerClick = useCallback((e) => {
    if (!pickModeRef.current || !vtkRef.current || !meshData?.nodes?.length) return;
    const dx = e.clientX - mouseDragRef.current.x;
    const dy = e.clientY - mouseDragRef.current.y;
    if (dx * dx + dy * dy > 25) return; // was a drag, not a click

    const { renderer } = vtkRef.current;
    const { origin, direction } = screenToWorldRay(e, containerRef.current, renderer);
    const idx = findNearestNodeToRay(meshData.nodes, origin, direction);
    if (idx < 0) return;

    const [nx, ny, nz] = meshData.nodes[idx];
    let value = null;
    if (fieldData?.values?.[idx] !== undefined) {
      const v = fieldData.values[idx];
      value = Array.isArray(v) ? Math.sqrt(v.reduce((s, c) => s + c * c, 0)) : v;
    }
    setPickedNode({ idx, x: nx, y: ny, z: nz, value });
  }, [meshData, fieldData]);

  // ── Export ─────────────────────────────────────────────────────────────────

  const handleScreenshot = useCallback(() => {
    if (!vtkRef.current?.renderWindow) return;
    const shots = vtkRef.current.renderWindow.captureImages();
    if (!shots?.length) return;
    shots[0].then(dataUrl => {
      const a = document.createElement('a');
      a.href = dataUrl;
      a.download = `${mesh?.original_filename ?? 'view'}.png`;
      a.click();
    }).catch(err => console.warn('Screenshot failed:', err));
  }, [mesh]);

  const handleCsvExport = useCallback(() => {
    if (!meshData?.nodes?.length) return;
    const isVec = fieldData && Array.isArray(fieldData.values?.[0]);
    const headers = ['node_id', 'x', 'y', 'z'];
    if (fieldData?.values?.length) {
      if (isVec) headers.push('fx', 'fy', 'fz', 'magnitude');
      else headers.push(fieldData.field_name || 'value');
    }
    const rows = meshData.nodes.map((pt, i) => {
      const row = [i, pt[0], pt[1], pt[2]];
      if (fieldData?.values?.[i] !== undefined) {
        const v = fieldData.values[i];
        if (Array.isArray(v)) row.push(...v, Math.sqrt(v.reduce((s, c) => s + c * c, 0)));
        else row.push(v);
      }
      return row.join(',');
    });
    const csv = [headers.join(','), ...rows].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `${mesh?.original_filename ?? 'mesh'}_nodes.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, [mesh, meshData, fieldData]);

  const handleMeshDownload = useCallback(() => {
    if (!mesh?.id) return;
    const a = document.createElement('a');
    a.href = `/api/cae/meshes/${mesh.id}/download`;
    a.download = mesh.original_filename;
    a.click();
  }, [mesh]);

  // ── Render ─────────────────────────────────────────────────────────────────
  // The vtk div MUST always be in the DOM so the mount effect ([] deps) can
  // attach the WebGL context on first render, regardless of whether a mesh is
  // selected yet. The "no mesh" state is shown as an overlay instead.

  return (
    <Box sx={{ height: '100%', position: 'relative', bgcolor: '#111' }}>

      {/* No-mesh placeholder — overlay so the vtk canvas stays mounted */}
      {!mesh && (
        <Box sx={{
          position: 'absolute', inset: 0, zIndex: 20,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          bgcolor: 'background.default', color: 'text.secondary',
        }}>
          <div style={{ textAlign: 'center' }}>
            <Typography variant="h6" gutterBottom>Modo CAE / FEA</Typography>
            <Typography variant="body2">Selecciona una malla en el panel izquierdo</Typography>
            <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 1 }}>
              Formatos: VTK, Abaqus .inp, Nastran .bdf, GMSH .msh, MED, Exodus…
            </Typography>
          </div>
        </Box>
      )}


      {/* Controls panel — only when a mesh is loaded */}
      {mesh && <Paper sx={{
        position: 'absolute', top: 16, right: 16, zIndex: 10,
        p: 2, minWidth: 230, maxWidth: 270,
        maxHeight: 'calc(100vh - 48px)', overflowY: 'auto',
        bgcolor: 'rgba(18,18,18,0.93)', backdropFilter: 'blur(8px)',
      }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
          <Typography variant="subtitle2" noWrap sx={{ maxWidth: 170 }}>
            {mesh.original_filename}
          </Typography>
          <Box sx={{ display: 'flex' }}>
            <Tooltip title={wireframe ? 'Ocultar aristas' : 'Mostrar aristas'}>
              <IconButton size="small" onClick={() => setWireframe(w => !w)}
                sx={{ color: wireframe ? 'info.main' : 'text.disabled' }}>
                <GridOn fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title={pickMode ? 'Salir del modo pick' : 'Seleccionar nodo'}>
              <IconButton size="small" onClick={() => { setPickMode(m => !m); setPickedNode(null); }}
                sx={{ color: pickMode ? 'warning.main' : 'text.disabled' }}>
                <GpsFixed fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>

        {/* Camera presets */}
        {meshData && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.3, mb: 0.5 }}>
            <Typography variant="caption" color="text.disabled" sx={{ mr: 0.5, fontSize: '0.65rem' }}>Vista:</Typography>
            {[
              { label: 'ISO', tip: 'Vista isométrica', preset: 'iso' },
              { label: '+Y',  tip: 'Vista superior (desde arriba)', preset: '+y' },
              { label: '-Y',  tip: 'Vista inferior (desde abajo) — muestra cabezas de tornillos y arandelas bajo la placa', preset: '-y' },
              { label: '+X',  tip: 'Vista lateral derecha', preset: '+x' },
              { label: '-X',  tip: 'Vista lateral izquierda', preset: '-x' },
              { label: '+Z',  tip: 'Vista frontal', preset: '+z' },
              { label: '-Z',  tip: 'Vista trasera', preset: '-z' },
            ].map(({ label, tip, preset }) => (
              <Tooltip key={preset} title={tip}>
                <Button
                  size="small" variant="outlined"
                  onClick={() => {
                    if (vtkRef.current) {
                      applyCameraPreset(vtkRef.current.renderer, vtkRef.current.renderWindow, preset, meshData.bounding_box);
                    }
                  }}
                  sx={{ minWidth: 0, px: 0.6, py: 0.1, fontSize: '0.60rem', lineHeight: 1.4,
                        color: 'text.secondary', borderColor: 'divider' }}
                >
                  {label}
                </Button>
              </Tooltip>
            ))}
          </Box>
        )}

        {meshData && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            {meshData.node_count?.toLocaleString()} nodos · {meshData.element_count?.toLocaleString()} elementos
          </Typography>
        )}

        {meshData && Object.keys(meshData.element_types || {}).length > 0 && (
          <Typography variant="caption" color="text.disabled" display="block" sx={{ mb: 0.5 }}>
            {Object.entries(meshData.element_types).map(([t, c]) => `${t}(${c})`).join(' · ')}
          </Typography>
        )}

        {/* Solver recommendations */}
        {meshData?.recommended_solvers?.length > 0 && (
          <>
            <Button
              fullWidth size="small" variant="text"
              onClick={() => setSolversOpen(o => !o)}
              sx={{ justifyContent: 'space-between', color: 'text.secondary', px: 0, py: 0.3, minHeight: 0, mb: solversOpen ? 0.5 : 0 }}
            >
              <span style={{ fontSize: '0.72rem' }}>Solvers recomendados</span>
              <span style={{ fontSize: '0.65rem' }}>{solversOpen ? '▲' : '▼'}</span>
            </Button>
            {solversOpen && (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 1 }}>
                {meshData.recommended_solvers.map(s => (
                  <Tooltip key={s.solver} title={`${s.description} · ${Math.round(s.confidence * 100)}%`}>
                    <Chip
                      label={s.solver}
                      size="small"
                      color={s.level === 'excellent' ? 'success' : s.level === 'good' ? 'info' : 'default'}
                      sx={{ height: 20, fontSize: '0.65rem', cursor: 'default' }}
                    />
                  </Tooltip>
                ))}
              </Box>
            )}
          </>
        )}

        {/* Mesh quality */}
        {meshData?.quality?.aspect_ratio_mean != null && (
          <Box sx={{ mb: 0.5 }}>
            {[
              ['A.R. medio',     meshData.quality.aspect_ratio_mean, 5],
              ['A.R. P95',       meshData.quality.aspect_ratio_p95,  10],
              ['Elem. defic. %', meshData.quality.bad_elements_pct,  5],
            ].map(([label, val, threshold]) => (
              <Box key={label} sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Typography variant="caption" color="text.disabled">{label}</Typography>
                <Typography variant="caption"
                  sx={{ fontFamily: 'monospace', color: val > threshold ? 'warning.main' : 'success.main' }}>
                  {val}
                </Typography>
              </Box>
            ))}
          </Box>
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

        {/* Field statistics */}
        {stats && (
          <>
            <Button
              fullWidth size="small" variant="text"
              onClick={() => setStatsOpen(o => !o)}
              sx={{ justifyContent: 'space-between', color: 'text.secondary', px: 0, mt: 0.5, mb: statsOpen ? 0.5 : 0 }}
            >
              <span>Estadísticas</span>
              <span style={{ fontSize: '0.7rem' }}>{statsOpen ? '▲' : '▼'}</span>
            </Button>

            {statsOpen && (
              <Box sx={{ mb: 1 }}>
                <Box sx={{ mb: 1 }}>
                  <MiniHistogram counts={stats.histogram} />
                </Box>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                  Umbral: [{(stats.min + threshold[0] * (stats.max - stats.min)).toExponential(2)},
                  {' '}{(stats.min + threshold[1] * (stats.max - stats.min)).toExponential(2)}]
                </Typography>
                <Slider
                  value={threshold}
                  onChange={(_, v) => setThreshold(v)}
                  min={0} max={1} step={0.01}
                  size="small"
                  sx={{ mb: 1.5, color: 'info.main' }}
                />
                {[
                  ['Min',     stats.min],
                  ['Max',     stats.max],
                  ['Media',   stats.mean],
                  ['Desv.',   stats.std],
                  ['P5',      stats.p5],
                  ['P25',     stats.p25],
                  ['Mediana', stats.p50],
                  ['P75',     stats.p75],
                  ['P95',     stats.p95],
                ].map(([label, val]) => (
                  <Box key={label} sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.2 }}>
                    <Typography variant="caption" color="text.disabled">{label}</Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                      {typeof val === 'number' ? val.toExponential(3) : '—'}
                    </Typography>
                  </Box>
                ))}
                <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 0.5 }}>
                  n = {stats.n.toLocaleString()}
                </Typography>
              </Box>
            )}
          </>
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

        {/* Per-part visibility */}
        {meshData?.parts?.length > 1 && (
          <>
            <Divider sx={{ my: 1 }} />
            <Button
              fullWidth size="small" variant="text"
              onClick={() => setPartsOpen(o => !o)}
              sx={{ justifyContent: 'space-between', color: 'text.secondary', px: 0, py: 0.3, minHeight: 0, mb: partsOpen ? 0.5 : 0 }}
            >
              <span style={{ fontSize: '0.72rem' }}>Piezas ({meshData.parts.length})</span>
              <span style={{ fontSize: '0.65rem' }}>{partsOpen ? '▲' : '▼'}</span>
            </Button>
            {partsOpen && (
              <Box>
                <Box sx={{ maxHeight: 200, overflowY: 'auto', mb: 0.5 }}>
                  {meshData.parts.map((part, i) => {
                    const vis = partsVisible[i] !== false;
                    const rgb = PART_COLORS[i % PART_COLORS.length].map(v => Math.round(v * 255));
                    const shortName = part.name.replace(/ T=\(.*?\)$/, '');
                    return (
                      <Box
                        key={i}
                        sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.25, cursor: 'pointer',
                              '&:hover': { bgcolor: 'action.hover' }, px: 0.5, borderRadius: 0.5 }}
                        onClick={() => setPartsVisible(prev => {
                          const next = [...prev];
                          next[i] = !next[i];
                          return next;
                        })}
                      >
                        <Box sx={{ width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                                   bgcolor: `rgb(${rgb.join(',')})`, opacity: vis ? 1 : 0.3 }} />
                        <Tooltip title={part.name}>
                          <Typography variant="caption" noWrap
                            sx={{ flex: 1, color: vis ? 'text.secondary' : 'text.disabled',
                                  textDecoration: vis ? 'none' : 'line-through' }}>
                            {shortName}
                          </Typography>
                        </Tooltip>
                      </Box>
                    );
                  })}
                </Box>
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                  <Button size="small" variant="outlined" sx={{ flex: 1, fontSize: '0.6rem', py: 0.2 }}
                    onClick={() => setPartsVisible(meshData.parts.map(() => true))}>
                    Todos
                  </Button>
                  <Button size="small" variant="outlined" sx={{ flex: 1, fontSize: '0.6rem', py: 0.2 }}
                    onClick={() => setPartsVisible(meshData.parts.map(() => false))}>
                    Ninguno
                  </Button>
                </Box>
              </Box>
            )}
          </>
        )}

        {/* Section cut */}
        {meshData && (
          <>
            <Divider sx={{ my: 1 }} />
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="caption" color={clipEnabled ? 'warning.main' : 'text.secondary'}>
                Corte
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <ToggleButtonGroup
                  value={clipAxis}
                  exclusive
                  size="small"
                  onChange={(_, v) => { if (v) setClipAxis(v); }}
                  sx={{ '& .MuiToggleButton-root': { py: 0, px: 0.7, fontSize: '0.65rem', minWidth: 0 } }}
                >
                  {['X', 'Y', 'Z'].map(a => (
                    <ToggleButton key={a} value={a} disabled={!clipEnabled}>{a}</ToggleButton>
                  ))}
                </ToggleButtonGroup>
                <Tooltip title={clipFlip ? 'Invertir lado' : 'Invertir lado'}>
                  <span>
                    <IconButton size="small" disabled={!clipEnabled}
                      onClick={() => setClipFlip(f => !f)}
                      sx={{ color: clipFlip ? 'warning.main' : 'text.disabled' }}>
                      <ContentCut sx={{ fontSize: 14, transform: clipFlip ? 'scaleX(-1)' : 'none' }} />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={clipEnabled ? 'Desactivar corte' : 'Activar corte'}>
                  <IconButton size="small" onClick={() => setClipEnabled(c => !c)}
                    sx={{ color: clipEnabled ? 'warning.main' : 'text.disabled' }}>
                    <ContentCut sx={{ fontSize: 14 }} />
                  </IconButton>
                </Tooltip>
              </Box>
            </Box>
            <Slider
              value={clipPos}
              onChange={(_, v) => setClipPos(v)}
              min={0} max={1} step={0.01}
              size="small"
              disabled={!clipEnabled}
              sx={{ mb: 0.5, color: clipEnabled ? 'warning.main' : undefined }}
            />
          </>
        )}

        {/* Time steps — always visible; controls disabled for single-step meshes */}
        {meshData && (
          <>
            <Divider sx={{ my: 1 }} />
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="caption" color={timeSteps.length > 1 ? 'text.secondary' : 'text.disabled'}>
                {timeSteps.length > 1
                  ? `Paso ${currentStep + 1} / ${timeSteps.length}${typeof timeSteps[currentStep] === 'number' && timeSteps[currentStep] !== currentStep ? ` · t=${timeSteps[currentStep].toFixed(3)}` : ''}`
                  : '1 paso (estático)'}
              </Typography>
              <Box sx={{ display: 'flex', gap: 0 }}>
                <Tooltip title="Primer paso">
                  <span>
                    <IconButton size="small" onClick={() => { setPlaying(false); setCurrentStep(0); }}
                      disabled={timeSteps.length <= 1 || currentStep === 0}>
                      <SkipPrevious sx={{ fontSize: 16 }} />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={playing ? 'Pausar' : 'Reproducir'}>
                  <span>
                    <IconButton size="small" onClick={() => setPlaying(p => !p)}
                      disabled={timeSteps.length <= 1}
                      color={playing ? 'warning' : 'default'}>
                      {playing ? <Pause sx={{ fontSize: 16 }} /> : <PlayArrow sx={{ fontSize: 16 }} />}
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title="Último paso">
                  <span>
                    <IconButton size="small" onClick={() => { setPlaying(false); setCurrentStep(timeSteps.length - 1); }}
                      disabled={timeSteps.length <= 1 || currentStep === timeSteps.length - 1}>
                      <SkipNext sx={{ fontSize: 16 }} />
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
            </Box>
            <Slider
              value={currentStep}
              onChange={(_, v) => { setPlaying(false); setCurrentStep(v); }}
              min={0}
              max={Math.max(1, timeSteps.length - 1)}
              step={1}
              size="small"
              marks={timeSteps.length <= 20}
              disabled={timeSteps.length <= 1}
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

        {/* Export */}
        <Divider sx={{ my: 1 }} />
        <Typography variant="caption" color="text.disabled" display="block" sx={{ mb: 0.5 }}>
          Exportar
        </Typography>
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Tooltip title="Captura PNG">
            <IconButton size="small" onClick={handleScreenshot} sx={{ color: 'text.secondary' }}>
              <CameraAlt sx={{ fontSize: 18 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title={fieldData ? 'Exportar nodos + campo CSV' : 'Exportar nodos CSV'}>
            <IconButton size="small" onClick={handleCsvExport} disabled={!meshData} sx={{ color: 'text.secondary' }}>
              <TableChart sx={{ fontSize: 18 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="Descargar malla original">
            <IconButton size="small" onClick={handleMeshDownload} disabled={!mesh} sx={{ color: 'text.secondary' }}>
              <FileDownload sx={{ fontSize: 18 }} />
            </IconButton>
          </Tooltip>
        </Box>
      </Paper>}

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

      {/* Picked node info */}
      {pickedNode && (
        <Paper sx={{
          position: 'absolute', bottom: 16, left: 16, zIndex: 10,
          p: 1.5, minWidth: 200,
          bgcolor: 'rgba(18,18,18,0.93)', backdropFilter: 'blur(8px)',
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
            <Typography variant="caption" color="warning.main" fontWeight="bold">
              Nodo #{pickedNode.idx.toLocaleString()}
            </Typography>
            <IconButton size="small" onClick={() => setPickedNode(null)} sx={{ p: 0.25 }}>
              <Close sx={{ fontSize: 14 }} />
            </IconButton>
          </Box>
          <Typography variant="caption" color="text.secondary" display="block">
            X: {pickedNode.x.toExponential(4)}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            Y: {pickedNode.y.toExponential(4)}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            Z: {pickedNode.z.toExponential(4)}
          </Typography>
          {pickedNode.value !== null && (
            <Typography variant="caption" color="info.main" display="block" sx={{ mt: 0.5 }}>
              Valor: {pickedNode.value.toExponential(4)}
            </Typography>
          )}
        </Paper>
      )}

      {/* vtk.js canvas — never receives mouse events when overlay is active */}
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

      {/* Transparent pick overlay — sits on top so vtk.js interactor never sees the click */}
      {pickMode && (
        <div
          style={{
            position: 'absolute', inset: 0,
            cursor: 'crosshair', zIndex: 2,
            background: 'transparent',
          }}
          onMouseDown={handleMouseDown}
          onClick={handleContainerClick}
        />
      )}
    </Box>
  );
}
