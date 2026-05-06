import React, { useState, useEffect, useRef } from 'react';
import { Canvas, useThree, useFrame } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Grid, GizmoHelper, GizmoViewport } from '@react-three/drei';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader';
import { CSS2DRenderer, CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer';
import { Box, CircularProgress, Alert, IconButton, Paper, Typography, Chip, Tooltip } from '@mui/material';
import { ZoomIn, ZoomOut, CenterFocusStrong, MyLocation, Layers } from '@mui/icons-material';

// ─── In-memory GLB cache (persists across file switches) ─────────────────────
const glbCache = new Map();

// ─── Inner Canvas components (use useThree / useFrame) ───────────────────────

function ClippingSetup({ plane }) {
  const { gl } = useThree();
  useEffect(() => {
    gl.localClippingEnabled = true;
    gl.clippingPlanes = plane ? [plane] : [];
    return () => { gl.clippingPlanes = []; };
  }, [plane, gl]);
  return null;
}

function LabelRenderLoop({ labelRendererRef }) {
  const { scene, camera } = useThree();
  useFrame(() => {
    labelRendererRef.current?.render(scene, camera);
  });
  return null;
}

function PMILabels({ annotations }) {
  const { scene } = useThree();
  const groupRef = useRef(null);

  useEffect(() => {
    if (groupRef.current) {
      scene.remove(groupRef.current);
      groupRef.current = null;
    }
    if (!annotations || annotations.length === 0) return;

    const group = new THREE.Group();
    group.name = 'PMIOverlay';

    const typeColors = {
      DIMENSION: '#64b5f6',
      'GD&T': '#ce93d8',
      SURFACE_FINISH: '#a5d6a7',
      DATUM: '#ffcc02',
      NOTE: '#90a4ae',
    };

    annotations.slice(0, 30).forEach((ann, i) => {
      const text = formatPMIValue(ann);
      if (!text) return;

      const color = typeColors[ann.pmi_type] || '#90caf9';
      const div = document.createElement('div');
      div.textContent = text;
      Object.assign(div.style, {
        color,
        background: 'rgba(0,0,0,0.78)',
        padding: '2px 7px',
        borderRadius: '3px',
        fontSize: '11px',
        fontFamily: 'monospace',
        border: `1px solid ${color}`,
        whiteSpace: 'nowrap',
        userSelect: 'none',
      });

      const obj = new CSS2DObject(div);
      // Spread annotations in an arc above the model; real geometry positions need face data
      const angle = (i / Math.max(annotations.length - 1, 1)) * Math.PI * 2;
      const r = 25 + Math.floor(i / 8) * 12;
      obj.position.set(Math.cos(angle) * r, 30 + Math.floor(i / 8) * 8, Math.sin(angle) * r);
      group.add(obj);
    });

    scene.add(group);
    groupRef.current = group;

    return () => {
      scene.remove(group);
      group.traverse(obj => {
        if (obj.element) obj.element.remove();
      });
    };
  }, [annotations, scene]);

  return null;
}

function MeasurementLines({ measurements }) {
  const { scene } = useThree();
  const groupRef = useRef(null);

  useEffect(() => {
    if (groupRef.current) {
      scene.remove(groupRef.current);
      groupRef.current = null;
    }
    if (!measurements || measurements.length === 0) return;

    const group = new THREE.Group();
    group.name = 'MeasurementLines';

    measurements.forEach((m) => {
      const type = (m.type || m.measurement_type || '').toLowerCase();

      if (type === 'distance' && m.points?.length >= 2) {
        const p1 = new THREE.Vector3(...m.points[0]);
        const p2 = new THREE.Vector3(...m.points[1]);
        const geo = new THREE.BufferGeometry().setFromPoints([p1, p2]);
        const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xff4444, depthTest: false }));
        line.renderOrder = 999;
        group.add(line);

        [p1, p2].forEach(pos => {
          const sphere = new THREE.Mesh(
            new THREE.SphereGeometry(0.4, 12, 12),
            new THREE.MeshBasicMaterial({ color: 0xff4444, depthTest: false })
          );
          sphere.position.copy(pos);
          sphere.renderOrder = 1000;
          group.add(sphere);
        });
      } else if (type === 'bbox' && m.min && m.max) {
        const box = new THREE.Box3(new THREE.Vector3(...m.min), new THREE.Vector3(...m.max));
        const helper = new THREE.Box3Helper(box, 0x4488ff);
        helper.renderOrder = 999;
        group.add(helper);
      } else if (type === 'angle' && m.vectors?.length >= 2) {
        const origin = new THREE.Vector3(0, 0, 0);
        const v1 = new THREE.Vector3(...m.vectors[0]).normalize().multiplyScalar(10);
        const v2 = new THREE.Vector3(...m.vectors[1]).normalize().multiplyScalar(10);
        const mat = new THREE.LineBasicMaterial({ color: 0x44ff88, depthTest: false });
        [v1, v2].forEach(v => {
          const geo = new THREE.BufferGeometry().setFromPoints([origin, v]);
          const line = new THREE.Line(geo, mat.clone());
          line.renderOrder = 999;
          group.add(line);
        });
      }
    });

    scene.add(group);
    groupRef.current = group;
    return () => { scene.remove(group); };
  }, [measurements, scene]);

  return null;
}

const VIEW_MODES = ['realistic', 'wireframe', 'xray', 'normals'];
const VIEW_MODE_LABELS = { realistic: 'Realista', wireframe: 'Malla', xray: 'Rayos X', normals: 'Normales' };

function ViewModeEffect({ scene, viewMode }) {
  useEffect(() => {
    if (!scene) return;
    scene.traverse(obj => {
      if (!obj.isMesh) return;
      if (!obj.userData.originalMaterial) {
        obj.userData.originalMaterial = Array.isArray(obj.material)
          ? obj.material.map(m => m.clone())
          : obj.material.clone();
      }
      switch (viewMode) {
        case 'wireframe':
          obj.material = new THREE.MeshBasicMaterial({ color: 0x00cc66, wireframe: true });
          break;
        case 'xray':
          obj.material = new THREE.MeshPhysicalMaterial({
            color: 0x0088ff, transparent: true, opacity: 0.25,
            side: THREE.DoubleSide, depthWrite: false,
          });
          break;
        case 'normals':
          obj.material = new THREE.MeshNormalMaterial({ side: THREE.DoubleSide });
          break;
        case 'realistic':
        default: {
          const orig = obj.userData.originalMaterial;
          obj.material = Array.isArray(orig) ? orig.map(m => m.clone()) : orig.clone();
          if (!Array.isArray(obj.material)) obj.material.side = THREE.DoubleSide;
          break;
        }
      }
    });
  }, [scene, viewMode]);
  return null;
}

function GLBModel({ modelId, onLoaded, onError, onProgress, pickingMode, onPointPicked, viewMode }) {
  const [gltfScene, setGltfScene] = useState(null);

  useEffect(() => {
    if (!modelId) return;
    setGltfScene(null);

    // Serve from in-memory cache when switching back to a previously loaded file
    if (glbCache.has(modelId)) {
      const cached = glbCache.get(modelId);
      setGltfScene(cached.scene);
      onLoaded(cached);
      return;
    }

    const dracoLoader = new DRACOLoader();
    dracoLoader.setDecoderPath('/step-view/draco/');
    const loader = new GLTFLoader();
    loader.setDRACOLoader(dracoLoader);

    async function fetchAndLoad() {
      // Poll until GLB is ready (server returns 202 while converting in background)
      const MAX_POLLS = 120;   // 120 × 5 s = 10 minutes ceiling
      const POLL_MS  = 5000;

      for (let poll = 0; poll < MAX_POLLS; poll++) {
        let resp;
        try {
          resp = await fetch(`/api/step-view/model/${modelId}/glb`);
        } catch (netErr) {
          onError('Error de red al cargar el modelo 3D.');
          return;
        }

        if (resp.status === 202) {
          // Server is converting in background — wait then retry
          let retryAfter = POLL_MS;
          try {
            const data = await resp.json();
            if (data.retry_after) retryAfter = data.retry_after * 1000;
          } catch {}
          await new Promise(res => setTimeout(res, retryAfter));
          continue;
        }

        if (!resp.ok) {
          let msg = `Error del servidor (HTTP ${resp.status})`;
          try {
            const data = await resp.json();
            const raw = data.message || data.error || msg;
            if (resp.status === 503 && raw.toLowerCase().includes('pythonocc')) {
              msg = 'El servidor no tiene OpenCASCADE instalado. '
                  + 'Instale pythonocc-core vía conda:\n'
                  + '  conda install -c conda-forge pythonocc-core=7.7.2 trimesh numpy\n'
                  + 'y reinicie el servidor desde ese entorno conda.';
            } else if (resp.status === 422 && raw.toLowerCase().includes('too large')) {
              msg = raw;
            } else if (raw.toLowerCase().includes('no transferable') || raw.toLowerCase().includes('no shapes')) {
              msg = 'El archivo STEP no contiene geometría sólida válida. Suba un STEP con cuerpos sólidos directos.';
            } else if (raw.toLowerCase().includes('trimesh')) {
              msg = 'GLB export requiere trimesh. Instale: pip install trimesh numpy';
            } else {
              msg = raw;
            }
          } catch {}
          onError(msg);
          return;
        }

        // 200 — GLB is ready
        const blob = await resp.blob();
        const objectUrl = URL.createObjectURL(blob);
        loader.load(
          objectUrl,
          (gltf) => {
            URL.revokeObjectURL(objectUrl);
            gltf.scene.traverse(obj => {
              if (obj.isMesh) {
                if (!obj.material) {
                  obj.material = new THREE.MeshStandardMaterial({ color: 0x8899aa, side: THREE.DoubleSide });
                } else {
                  obj.material.side = THREE.DoubleSide;
                }
                obj.castShadow = true;
                obj.receiveShadow = true;
              }
            });
            glbCache.set(modelId, gltf);
            setGltfScene(gltf.scene);
            onLoaded(gltf);
          },
          (xhr) => { if (xhr.total > 0) onProgress?.(Math.round(xhr.loaded / xhr.total * 100)); },
          (err) => { URL.revokeObjectURL(objectUrl); console.error('GLB parse error:', err); onError('Error al parsear el modelo 3D.'); }
        );
        return; // loader.load is callback-based; exit the poll loop
      } // end for-loop

      onError('Tiempo de espera agotado. El archivo puede ser demasiado grande o complejo.');
    }
    fetchAndLoad();
  }, [modelId]);

  if (!gltfScene) return null;

  return (
    <>
      <ViewModeEffect scene={gltfScene} viewMode={viewMode} />
      <primitive
        object={gltfScene}
        onClick={pickingMode ? (e) => {
          e.stopPropagation();
          onPointPicked?.([
            parseFloat(e.point.x.toFixed(3)),
            parseFloat(e.point.y.toFixed(3)),
            parseFloat(e.point.z.toFixed(3)),
          ]);
        } : undefined}
      />
    </>
  );
}

// ─── Markup canvas overlay (2D drawing on top of 3D) ─────────────────────────

function MarkupCanvas({ active, tool, color, strokeWidth, strokes, onStrokesChange }) {
  const canvasRef = useRef();
  const drawing = useRef(false);
  const currentStroke = useRef([]);
  const startPos = useRef(null);

  useEffect(() => {
    redraw();
  }, [strokes, active]);

  function getPos(e) {
    const rect = canvasRef.current.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function redraw(extraStroke = null) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    [...strokes, ...(extraStroke ? [extraStroke] : [])].forEach(s => {
      if (!s.points || s.points.length === 0) return;
      ctx.strokeStyle = s.color || '#ff0000';
      ctx.lineWidth = s.width || 2;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';

      if (s.type === 'pen') {
        ctx.beginPath();
        ctx.moveTo(s.points[0].x, s.points[0].y);
        s.points.forEach(p => ctx.lineTo(p.x, p.y));
        ctx.stroke();
      } else if (s.type === 'arrow' && s.points.length >= 2) {
        const p1 = s.points[0];
        const p2 = s.points[s.points.length - 1];
        drawArrow(ctx, p1.x, p1.y, p2.x, p2.y, s.color || '#ff0000', s.width || 2);
      } else if (s.type === 'rect' && s.points.length >= 2) {
        const p1 = s.points[0];
        const p2 = s.points[s.points.length - 1];
        ctx.beginPath();
        ctx.rect(p1.x, p1.y, p2.x - p1.x, p2.y - p1.y);
        ctx.stroke();
      } else if (s.type === 'text' && s.points.length >= 1) {
        ctx.fillStyle = s.color || '#ff0000';
        ctx.font = `${(s.width || 2) * 7 + 10}px sans-serif`;
        ctx.fillText(s.text || '...', s.points[0].x, s.points[0].y);
      }
    });
  }

  function drawArrow(ctx, x1, y1, x2, y2, color, width) {
    const headLen = Math.max(12, width * 4);
    const angle = Math.atan2(y2 - y1, x2 - x1);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6));
    ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6));
    ctx.closePath();
    ctx.fill();
  }

  function onMouseDown(e) {
    if (!active) return;
    drawing.current = true;
    const pos = getPos(e);
    startPos.current = pos;
    currentStroke.current = [pos];
  }

  function onMouseMove(e) {
    if (!drawing.current || !active) return;
    const pos = getPos(e);
    if (tool === 'pen') {
      currentStroke.current.push(pos);
      redraw({ type: tool, color, width: strokeWidth, points: [...currentStroke.current] });
    } else if (tool === 'arrow' || tool === 'rect') {
      redraw({ type: tool, color, width: strokeWidth, points: [startPos.current, pos] });
    }
  }

  function onMouseUp(e) {
    if (!drawing.current || !active) return;
    drawing.current = false;
    const pos = getPos(e);

    if (tool === 'text') {
      const text = prompt('Enter text:');
      if (text) {
        onStrokesChange([...strokes, { type: 'text', color, width: strokeWidth, points: [startPos.current], text }]);
      }
      return;
    }

    const points = tool === 'pen'
      ? [...currentStroke.current, pos]
      : [startPos.current, pos];

    if (points.length > 1 || tool !== 'pen') {
      onStrokesChange([...strokes, { type: tool, color, width: strokeWidth, points }]);
    }
    currentStroke.current = [];
  }

  if (!active) return null;

  return (
    <canvas
      ref={canvasRef}
      width={window.innerWidth}
      height={window.innerHeight}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      style={{
        position: 'absolute', inset: 0, zIndex: 20,
        cursor: tool === 'text' ? 'text' : 'crosshair',
        background: 'transparent',
      }}
    />
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function StepViewer3D({
  headerId,
  filename,
  selectedEntityId,
  onEntitySelect,
  pickingMode = false,
  onPointPicked,
  clippingPlane = null,
  measurements = [],
  pmiAnnotations = [],
  markupActive = false,
  markupTool = 'pen',
  markupColor = '#ff0000',
  markupStrokeWidth = 2,
  markupStrokes = [],
  onMarkupStrokesChange,
}) {
  const [gltf, setGltf] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadProgress, setLoadProgress] = useState(null);
  const [loadingMsg, setLoadingMsg] = useState('Requesting model...');
  const [error, setError] = useState(null);
  const [viewMode, setViewMode] = useState('realistic');
  const containerRef = useRef();
  const controlsRef = useRef();
  const cameraRef = useRef();
  const labelRendererRef = useRef();

  function cycleViewMode() {
    setViewMode(prev => {
      const idx = VIEW_MODES.indexOf(prev);
      return VIEW_MODES[(idx + 1) % VIEW_MODES.length];
    });
  }

  // Reset loading state when headerId changes (user switches file)
  useEffect(() => {
    if (!headerId) return;
    setGltf(null);
    setError(null);
    setLoading(true);
    setLoadProgress(null);
  }, [headerId]);

  // Loading message progression + hard timeout
  // GLB conversion runs in a background thread so first load can take several minutes.
  useEffect(() => {
    if (!loading) return;
    setLoadingMsg('Requesting model...');
    const t1 = setTimeout(() => setLoadingMsg('Converting STEP → 3D (first load: 30-120 s)...'), 4000);
    const t2 = setTimeout(() => setLoadingMsg('Still converting — large file, please wait...'), 30000);
    const t3 = setTimeout(() => setLoadingMsg('Almost there — finalising mesh...'), 120000);
    const t4 = setTimeout(() => {
      setError('Model load timed out after 10 min. The STEP file may be too large, or check server logs.');
      setLoading(false);
    }, 600000);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); clearTimeout(t4); };
  }, [loading]);

  // CSS2DRenderer lifecycle
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const lr = new CSS2DRenderer();
    lr.setSize(container.clientWidth, container.clientHeight);
    Object.assign(lr.domElement.style, {
      position: 'absolute', top: '0', left: '0', pointerEvents: 'none',
    });
    container.appendChild(lr.domElement);
    labelRendererRef.current = lr;

    const ro = new ResizeObserver(() => {
      lr.setSize(container.clientWidth, container.clientHeight);
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      if (container.contains(lr.domElement)) container.removeChild(lr.domElement);
    };
  }, []);

  function fitCameraToScene(scene) {
    if (!scene || !cameraRef.current || !controlsRef.current) return;
    scene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(scene);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    if (maxDim <= 0 || !isFinite(maxDim)) return;

    const fov = cameraRef.current.fov * (Math.PI / 180);
    const dist = Math.max((maxDim / (2 * Math.tan(fov / 2))) * 1.5, maxDim);

    // Expand clipping planes so large-unit models (e.g. mils) are never clipped
    cameraRef.current.near = Math.max(0.01, dist / 10000);
    cameraRef.current.far  = dist * 20;
    cameraRef.current.updateProjectionMatrix();

    cameraRef.current.position.set(center.x + dist, center.y + dist * 0.5, center.z + dist);
    controlsRef.current.target.copy(center);
    controlsRef.current.minDistance = dist / 100;
    controlsRef.current.maxDistance = dist * 10;
    controlsRef.current.update();
  }

  function handleModelLoaded(loadedGltf) {
    setGltf(loadedGltf);
    setLoading(false);
    fitCameraToScene(loadedGltf.scene);
  }

  function handleZoomIn() { cameraRef.current?.position.multiplyScalar(0.8); controlsRef.current?.update(); }
  function handleZoomOut() { cameraRef.current?.position.multiplyScalar(1.2); controlsRef.current?.update(); }
  function handleResetView() {
    if (!gltf?.scene || !cameraRef.current || !controlsRef.current) return;
    fitCameraToScene(gltf.scene);
  }
  const cursor = markupActive ? 'crosshair' : pickingMode ? 'cell' : 'default';

  return (
    <Box ref={containerRef} sx={{ position: 'relative', width: '100%', height: '100%', cursor }}>

      {/* Loading overlay */}
      {loading && (
        <Box sx={{ position: 'absolute', inset: 0, zIndex: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', bgcolor: 'background.default', gap: 2 }}>
          <CircularProgress variant={loadProgress != null ? 'determinate' : 'indeterminate'} value={loadProgress} />
          <Typography variant="body1">{loadingMsg}</Typography>
          {loadProgress != null && (
            <Typography variant="caption" color="text.secondary">{loadProgress}%</Typography>
          )}
        </Box>
      )}

      {/* Error overlay */}
      {error && (
        <Box sx={{ position: 'absolute', inset: 0, zIndex: 10, p: 3 }}>
          <Alert severity="error"><strong>Error loading 3D model:</strong><br />{error}</Alert>
        </Box>
      )}

      {/* 3D Canvas */}
      <Canvas shadows>
        <ClippingSetup plane={clippingPlane} />
        <LabelRenderLoop labelRendererRef={labelRendererRef} />

        {/* near/far are overridden in fitCameraToScene once the model is loaded */}
        <PerspectiveCamera ref={cameraRef} makeDefault fov={45} near={0.01} far={1000000} position={[500, 500, 500]} />
        <OrbitControls
          ref={controlsRef}
          enableDamping
          dampingFactor={0.05}
          enabled={!pickingMode && !markupActive}
        />

        <ambientLight intensity={0.6} />
        <hemisphereLight skyColor="#b1e1ff" groundColor="#4a4a4a" intensity={0.5} />
        <directionalLight position={[10, 10, 5]} intensity={0.8} castShadow shadow-mapSize-width={2048} shadow-mapSize-height={2048} />
        <directionalLight position={[-10, -10, -5]} intensity={0.3} />
        <directionalLight position={[0, -10, 0]} intensity={0.2} />

        {/* Grid size adapts to model: update via fitCameraToScene → gridRef in future; fixed large default for now */}
        <Grid args={[10000, 100]} cellSize={100} cellColor="#6f6f6f" sectionSize={1000} sectionColor="#9d4b4b" />

        {headerId && (
          <GLBModel
            modelId={headerId}
            onLoaded={handleModelLoaded}
            onProgress={setLoadProgress}
            onError={(msg) => { setError(msg || 'Failed to load 3D model. The STEP file may not exist on the server, or conversion failed.'); setLoading(false); }}
            pickingMode={pickingMode}
            onPointPicked={onPointPicked}
            viewMode={viewMode}
          />
        )}

        <MeasurementLines measurements={measurements} />
        {pmiAnnotations.length > 0 && <PMILabels annotations={pmiAnnotations} />}

        <GizmoHelper alignment="bottom-left" margin={[72, 72]}>
          <GizmoViewport axisColors={['#ff4060', '#80ff40', '#4080ff']} labelColor="white" />
        </GizmoHelper>
      </Canvas>

      {/* 2D Markup canvas overlay */}
      <MarkupCanvas
        active={markupActive}
        tool={markupTool}
        color={markupColor}
        strokeWidth={markupStrokeWidth}
        strokes={markupStrokes}
        onStrokesChange={onMarkupStrokesChange}
      />

      {/* Picking mode indicator */}
      {pickingMode && (
        <Box sx={{ position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 15 }}>
          <Paper sx={{ px: 2, py: 0.5 }} elevation={4}>
            <Typography variant="caption" color="primary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <MyLocation fontSize="inherit" /> Click on the model to pick a point — press Esc to cancel
            </Typography>
          </Paper>
        </Box>
      )}

      {/* Viewer controls */}
      <Paper sx={{ position: 'absolute', bottom: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 1, p: 1 }} elevation={3}>
        <IconButton onClick={handleZoomIn} size="small" title="Zoom In"><ZoomIn /></IconButton>
        <IconButton onClick={handleZoomOut} size="small" title="Zoom Out"><ZoomOut /></IconButton>
        <IconButton onClick={handleResetView} size="small" title="Reset View"><CenterFocusStrong /></IconButton>
        <Tooltip title={`Modo: ${VIEW_MODE_LABELS[viewMode]} → siguiente`} placement="left">
          <IconButton
            onClick={cycleViewMode}
            size="small"
            sx={{ color: viewMode !== 'realistic' ? 'warning.main' : 'inherit' }}
          >
            <Layers />
          </IconButton>
        </Tooltip>
      </Paper>

      {/* File info */}
      <Paper sx={{ position: 'absolute', top: 16, left: 16, p: 2, maxWidth: 300 }} elevation={2}>
        <Typography variant="subtitle2" gutterBottom>{filename}</Typography>
        {gltf && <Typography variant="caption" color="text.secondary">Model loaded</Typography>}
        {loading && <Typography variant="caption" color="primary">Loading model...</Typography>}
        {clippingPlane && <Chip label="Section Cut active" size="small" color="warning" sx={{ mt: 0.5, display: 'block' }} />}
        {viewMode !== 'realistic' && <Chip label={VIEW_MODE_LABELS[viewMode]} size="small" color="warning" sx={{ mt: 0.5, display: 'block' }} />}
      </Paper>
    </Box>
  );
}

function formatPMIValue(ann) {
  if (ann.text) return ann.text;
  if (!ann.value) return ann.label || '';
  const unit = ann.unit || 'mm';
  if (ann.subtype === 'DIAMETER') return `Ø${parseFloat(ann.value).toFixed(2)} ${unit}`;
  if (ann.subtype === 'RADIUS') return `R${parseFloat(ann.value).toFixed(2)} ${unit}`;
  if (ann.subtype === 'ANGULAR') return `${parseFloat(ann.value).toFixed(1)}°`;
  return `${parseFloat(ann.value).toFixed(2)} ${unit}`;
}
