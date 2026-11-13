/**
 * GeometryViewer — CAD geometry with persistent face picking (Engineering Hub, Fase 1c).
 *
 * Loads /api/geometry/<id>/glb: one uncompressed mesh whose vertex attribute `_face_id`
 * (GLTFLoader lower-cases `_FACE_ID`) holds the 1-based CAD face index. Vertices are never
 * shared between faces, so each face is a contiguous vertex range and highlighting is a
 * write into the per-vertex color attribute — no re-tessellation, no per-face meshes.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, GizmoHelper, GizmoViewport } from '@react-three/drei';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader';
import { Box, CircularProgress, Typography, Alert, Paper, IconButton, Tooltip } from '@mui/material';
import { CenterFocusStrong, BorderOuter } from '@mui/icons-material';
import useGeometryStore from '../../stores/geometryStore';

const BASE = new THREE.Color(0.62, 0.66, 0.72);
const HOVER = new THREE.Color(0.35, 0.72, 1.0);
const SELECTED = new THREE.Color(1.0, 0.58, 0.12);
const CLICK_TOLERANCE_PX = 4;

/** Fetch the GLB (polling while the import job runs) and parse it. */
async function loadGlb(geometryId, signal) {
  for (let i = 0; i < 300; i++) {
    const resp = await fetch(`/api/geometry/${geometryId}/glb`, { signal });
    if (resp.status === 202) { await new Promise((r) => setTimeout(r, 2000)); continue; }
    if (!resp.ok) {
      let msg = `HTTP ${resp.status}`;
      try { msg = (await resp.json()).error || msg; } catch { /* binary or empty */ }
      throw new Error(msg);
    }
    const buf = await resp.arrayBuffer();
    return new Promise((resolve, reject) => new GLTFLoader().parse(buf, '', resolve, reject));
  }
  throw new Error('Tiempo de espera agotado esperando la importación');
}

/** face index -> [firstVertex, vertexCount], from the contiguous _face_id attribute. */
function faceRanges(attr) {
  const ranges = new Map();
  let start = 0;
  let cur = attr.getX(0);
  for (let i = 1; i <= attr.count; i++) {
    const v = i < attr.count ? attr.getX(i) : NaN;
    if (v !== cur) {
      ranges.set(Math.round(cur), [start, i - start]);
      start = i;
      cur = v;
    }
  }
  return ranges;
}

function paint(colors, range, color) {
  if (!range) return;
  const [s, n] = range;
  for (let i = s; i < s + n; i++) colors.setXYZ(i, color.r, color.g, color.b);
}

function FitCamera({ box, nonce }) {
  const { camera, controls } = useThree();
  useEffect(() => {
    if (!box) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    const dist = size / (2 * Math.tan((camera.fov * Math.PI) / 360)) * 1.1;
    camera.position.copy(center).add(new THREE.Vector3(1, 0.8, 1).normalize().multiplyScalar(dist));
    camera.near = size / 1000;
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    if (controls) { controls.target.copy(center); controls.update(); }
  }, [box, nonce, camera, controls]);
  return null;
}

function GeometryMesh({ mesh, ranges, showEdges }) {
  const selectedFaces = useGeometryStore((s) => s.selectedFaces);
  const hoverFace = useGeometryStore((s) => s.hoverFace);
  const pickFace = useGeometryStore((s) => s.pickFace);
  const setHoverFace = useGeometryStore((s) => s.setHoverFace);
  const painted = useRef(new Set());

  const edges = useMemo(() => {
    const g = new THREE.EdgesGeometry(mesh.geometry, 25);
    return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x1b1f24, transparent: true, opacity: 0.55 }));
  }, [mesh]);

  // Repaint only faces whose state changed.
  useEffect(() => {
    const colors = mesh.geometry.attributes.color;
    const want = new Map();
    selectedFaces.forEach((f) => want.set(f, SELECTED));
    if (hoverFace != null && !want.has(hoverFace)) want.set(hoverFace, HOVER);
    painted.current.forEach((f) => { if (!want.has(f)) paint(colors, ranges.get(f), BASE); });
    want.forEach((c, f) => paint(colors, ranges.get(f), c));
    painted.current = new Set(want.keys());
    colors.needsUpdate = true;
  }, [mesh, ranges, selectedFaces, hoverFace]);

  const faceOf = (e) => (e.face ? Math.round(mesh.geometry.attributes._face_id.getX(e.face.a)) : null);

  return (
    <>
      <primitive
        object={mesh}
        onPointerMove={(e) => { e.stopPropagation(); setHoverFace(faceOf(e)); }}
        onPointerOut={() => setHoverFace(null)}
        onClick={(e) => {
          if (e.delta > CLICK_TOLERANCE_PX) return;      // orbit drag, not a click
          e.stopPropagation();
          pickFace(faceOf(e), e.shiftKey || e.ctrlKey || e.metaKey);
        }}
        onPointerMissed={(e) => { if (e.type === 'click' && !e.shiftKey) pickFace(null); }}
      />
      {showEdges && <primitive object={edges} />}
    </>
  );
}

export default function GeometryViewer() {
  const selected = useGeometryStore((s) => s.selected);
  const glbNonce = useGeometryStore((s) => s.glbNonce);
  const [state, setState] = useState({ loading: false, error: null, mesh: null, ranges: null, box: null });
  const [fitNonce, setFitNonce] = useState(0);
  const [showEdges, setShowEdges] = useState(true);

  const geometryId = selected?.id;
  const ready = selected?.status === 'ready';

  useEffect(() => {
    if (!geometryId || !ready) { setState({ loading: false, error: null, mesh: null, ranges: null, box: null }); return undefined; }
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    loadGlb(geometryId, ctrl.signal)
      .then((gltf) => {
        let mesh = null;
        gltf.scene.traverse((o) => { if (o.isMesh && !mesh) mesh = o; });
        const attr = mesh?.geometry.attributes._face_id;
        if (!attr) throw new Error('El GLB no trae el atributo _FACE_ID');
        const n = mesh.geometry.attributes.position.count;
        const colors = new THREE.BufferAttribute(new Float32Array(n * 3), 3);
        for (let i = 0; i < n; i++) colors.setXYZ(i, BASE.r, BASE.g, BASE.b);
        mesh.geometry.setAttribute('color', colors);
        mesh.material = new THREE.MeshStandardMaterial({
          vertexColors: true, side: THREE.DoubleSide, metalness: 0.1, roughness: 0.6,
          polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
        });
        mesh.geometry.computeBoundingBox();
        mesh.geometry.computeBoundingSphere();
        setState({ loading: false, error: null, mesh, ranges: faceRanges(attr), box: mesh.geometry.boundingBox.clone() });
      })
      .catch((err) => { if (!ctrl.signal.aborted) setState({ loading: false, error: err.message, mesh: null, ranges: null, box: null }); });
    return () => ctrl.abort();
  }, [geometryId, ready, glbNonce]);

  if (!selected) {
    return (
      <Box sx={{ height: '100%', display: 'grid', placeItems: 'center' }}>
        <Typography color="text.secondary">Sube o selecciona una geometría STEP.</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ position: 'relative', width: '100%', height: '100%', bgcolor: '#2a2e33' }}>
      {(state.loading || !ready) && (
        <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', zIndex: 5 }}>
          {selected.status === 'failed'
            ? <Alert severity="error">La importación falló: {selected.error}</Alert>
            : <Box sx={{ textAlign: 'center' }}><CircularProgress /><Typography sx={{ mt: 1 }} color="text.secondary">
                {ready ? 'Cargando malla…' : 'Importando geometría…'}</Typography></Box>}
        </Box>
      )}
      {state.error && (
        <Box sx={{ position: 'absolute', top: 16, left: 16, right: 16, zIndex: 6 }}>
          <Alert severity="error">{state.error}</Alert>
        </Box>
      )}

      <Canvas camera={{ fov: 45, position: [300, 300, 300] }} onCreated={({ gl }) => gl.setClearColor('#2a2e33')}>
        <ambientLight intensity={0.55} />
        <hemisphereLight args={['#dfe9f5', '#3a3a3a', 0.6]} />
        <directionalLight position={[1, 2, 1.5]} intensity={0.9} />
        <directionalLight position={[-1.5, -1, -1]} intensity={0.35} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
        {state.mesh && <GeometryMesh mesh={state.mesh} ranges={state.ranges} showEdges={showEdges} />}
        <FitCamera box={state.box} nonce={fitNonce} />
        <GizmoHelper alignment="bottom-left" margin={[64, 64]}>
          <GizmoViewport axisColors={['#ff4060', '#80ff40', '#4080ff']} labelColor="white" />
        </GizmoHelper>
      </Canvas>

      <Paper sx={{ position: 'absolute', bottom: 16, right: 16, display: 'flex', flexDirection: 'column', p: 0.5 }} elevation={3}>
        <Tooltip title="Encuadrar" placement="left">
          <IconButton size="small" onClick={() => setFitNonce((n) => n + 1)}><CenterFocusStrong /></IconButton>
        </Tooltip>
        <Tooltip title={showEdges ? 'Ocultar aristas' : 'Mostrar aristas'} placement="left">
          <IconButton size="small" onClick={() => setShowEdges((v) => !v)} color={showEdges ? 'primary' : 'default'}>
            <BorderOuter />
          </IconButton>
        </Tooltip>
      </Paper>
      <Typography variant="caption" sx={{ position: 'absolute', top: 8, left: 12, color: '#9aa4ae' }}>
        Clic: seleccionar cara · Shift/Ctrl+clic: añadir/quitar · Clic en vacío: limpiar
      </Typography>
    </Box>
  );
}
