/**
 * DensityField — FASE 4: 3D view of a topology-optimization result.
 *
 * Shows the iso-surface ρ = threshold (marching tetrahedra, computed by the backend) coloured
 * by density (blue = threshold … red = solid) inside a translucent ghost of the design domain.
 * Re-fetches when a new snapshot arrives (live while optimizing) or the threshold changes.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import * as THREE from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, GizmoHelper, GizmoViewport } from '@react-three/drei';
import { Box, CircularProgress, Typography, Alert } from '@mui/material';

const API = '/api/design/topology';

// blue (0) → cyan → green → yellow → red (1)
function densityColor(t) {
  const stops = [[0, [0.13, 0.35, 0.85]], [0.25, [0.1, 0.75, 0.9]], [0.5, [0.3, 0.8, 0.3]],
    [0.75, [0.95, 0.85, 0.2]], [1, [0.9, 0.2, 0.15]]];
  const x = Math.min(1, Math.max(0, t));
  for (let i = 1; i < stops.length; i += 1) {
    if (x <= stops[i][0]) {
      const [a, ca] = stops[i - 1];
      const [b, cb] = stops[i];
      const f = (x - a) / (b - a);
      return ca.map((c, k) => c + f * (cb[k] - c));
    }
  }
  return stops[stops.length - 1][1];
}

function buildGeometry(positions, indices, density) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  g.setIndex(indices);
  if (density) {
    const col = new Float32Array(density.length * 3);
    density.forEach((d, i) => { col.set(densityColor(d), 3 * i); });
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  }
  g.computeVertexNormals();
  g.computeBoundingBox();
  return g;
}

function FitOnce({ box }) {
  const { camera, controls } = useThree();
  const done = useRef(false);
  useEffect(() => {
    if (!box || done.current) return;
    done.current = true;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    const dist = (size / (2 * Math.tan((camera.fov * Math.PI) / 360))) * 1.05;
    camera.position.copy(center).add(new THREE.Vector3(0.35, 0.3, 1).normalize().multiplyScalar(dist));
    camera.near = size / 1000;
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    if (controls) { controls.target.copy(center); controls.update(); }
  }, [box, camera, controls]);
  return null;
}

export default function DensityField({ runId, snapshotIter, threshold = 0.5, showDomain = true }) {
  const [domain, setDomain] = useState(null);
  const [iso, setIso] = useState(null);
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!runId) return undefined;
    let alive = true;
    setDomain(null);
    const tryLoad = (n) => axios.get(`${API}/${runId}/domain`)
      .then(r => { if (alive) setDomain(buildGeometry(r.data.positions, r.data.indices, null)); })
      .catch(() => { if (alive && n > 0) setTimeout(() => tryLoad(n - 1), 2000); });
    tryLoad(30);
    return () => { alive = false; };
  }, [runId]);

  useEffect(() => {
    if (!runId || !snapshotIter) return undefined;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      axios.get(`${API}/${runId}/isosurface`, { params: { threshold }, signal: ctrl.signal })
        .then(r => {
          const d = r.data;
          setIso(old => { if (old) old.dispose(); return buildGeometry(d.positions, d.indices, d.density); });
          setInfo({ iteration: d.iteration, source: d.source, volume: d.volume_mm3, triangles: d.indices.length / 3 });
          setError(null);
        })
        .catch(e => { if (!axios.isCancel(e)) setError(e.response?.data?.error || e.message); })
        .finally(() => setLoading(false));
    }, 250);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [runId, snapshotIter, threshold]);

  const box = useMemo(() => (domain ? domain.boundingBox : iso?.boundingBox) || null, [domain, iso]);

  return (
    <Box sx={{ position: 'relative', width: '100%', height: '100%', bgcolor: '#20242a' }}>
      <Canvas camera={{ fov: 40, position: [300, 200, 400] }} onCreated={({ gl }) => gl.setClearColor('#20242a')}>
        <ambientLight intensity={0.5} />
        <hemisphereLight args={['#e8eef7', '#30343a', 0.6]} />
        <directionalLight position={[1, 2, 1.5]} intensity={0.9} />
        <directionalLight position={[-1.5, -1, -1]} intensity={0.35} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
        {iso && (
          <mesh geometry={iso}>
            <meshStandardMaterial vertexColors side={THREE.DoubleSide} roughness={0.55} metalness={0.05} />
          </mesh>
        )}
        {domain && showDomain && (
          <mesh geometry={domain}>
            <meshBasicMaterial color="#9fb4cc" transparent opacity={0.07} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
        )}
        {domain && showDomain && (
          <lineSegments>
            <edgesGeometry args={[domain, 30]} />
            <lineBasicMaterial color="#6f8399" transparent opacity={0.6} />
          </lineSegments>
        )}
        <FitOnce box={box} />
        <GizmoHelper alignment="bottom-left" margin={[56, 56]}>
          <GizmoViewport axisColors={['#ff4060', '#80ff40', '#4080ff']} labelColor="white" />
        </GizmoHelper>
      </Canvas>
      <Box sx={{ position: 'absolute', top: 8, left: 8, color: '#ccc', fontSize: 12, pointerEvents: 'none' }}>
        {info && (
          <Typography variant="caption" sx={{ display: 'block', color: '#ccc' }}>
            {info.source === 'result' ? 'Resultado final' : 'En curso'} · iteración {info.iteration} ·
            {' '}{Math.round(info.volume).toLocaleString()} mm³ · {info.triangles.toLocaleString()} triángulos
          </Typography>
        )}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
          <Typography variant="caption" sx={{ color: '#aaa' }}>ρ {threshold.toFixed(2)}</Typography>
          <Box sx={{ width: 120, height: 8, borderRadius: 1,
            background: 'linear-gradient(90deg, #2159d9, #1abfe6, #4dcc4d, #f2d933, #e63326)' }} />
          <Typography variant="caption" sx={{ color: '#aaa' }}>1</Typography>
        </Box>
      </Box>
      {(loading || !snapshotIter) && (
        <Box sx={{ position: 'absolute', top: 8, right: 8, display: 'flex', alignItems: 'center', gap: 1 }}>
          <CircularProgress size={16} />
          {!snapshotIter && <Typography variant="caption" sx={{ color: '#aaa' }}>Esperando primera iteración…</Typography>}
        </Box>
      )}
      {error && (
        <Alert severity="warning" sx={{ position: 'absolute', bottom: 8, left: 8, right: 8 }}>{error}</Alert>
      )}
    </Box>
  );
}
