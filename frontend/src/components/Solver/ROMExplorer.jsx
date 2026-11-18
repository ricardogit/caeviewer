/**
 * ROMExplorer — FASE 5: real-time response of a POD ROM.
 *
 * Sliders → socket.io `rom_evaluate` (reduced solve on the server, whole-volume maxima) →
 * the surface field is rebuilt in the browser from the reduced coefficients (romPack) and
 * drawn deformed and coloured. The round-trip time is shown next to the server time.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, GizmoHelper, GizmoViewport } from '@react-three/drei';
import {
  Box, Typography, Slider, Dialog, DialogTitle, DialogContent, IconButton, Alert, Chip, Button,
  ToggleButtonGroup, ToggleButton, TextField, CircularProgress, Divider, Tooltip,
} from '@mui/material';
import { Close, Bolt, PlayArrow } from '@mui/icons-material';

import useROMStore from '../../stores/romStore';
import { reconstruct } from '../../utils/romPack';
import { colormap, COLORBAR_CSS } from '../../utils/colormap';

const label = { color: '#bbb', fontSize: 12 };

const fmtParam = (p, v) => {
  const x = v * (p.display_scale || 1);
  return Math.abs(x) >= 100 ? x.toFixed(0) : Number(x.toPrecision(3)).toString();
};

function FitOnce({ box }) {
  const { camera, controls } = useThree();
  const done = useRef(false);
  useEffect(() => {
    if (!box || done.current) return;
    done.current = true;
    const c = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    const dist = (size / (2 * Math.tan((camera.fov * Math.PI) / 360))) * 1.1;
    camera.position.copy(c).add(new THREE.Vector3(0.6, 0.45, 1).normalize().multiplyScalar(dist));
    camera.near = size / 1000;
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    if (controls) { controls.target.copy(c); controls.update(); }
  }, [box, camera, controls]);
  return null;
}

function FieldMesh({ geometry }) {
  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial vertexColors side={THREE.DoubleSide} roughness={0.6} metalness={0.05} />
    </mesh>
  );
}

export default function ROMExplorer() {
  const {
    activeROM, pack, params, result, responseTime, loadingROM, error, setParam, closeExplorer, fullRun, compare,
  } = useROMStore();
  const [field, setField] = useState('vm');
  const [warp, setWarp] = useState(1);
  const [yieldMPa, setYieldMPa] = useState('');
  const [verify, setVerify] = useState(null);

  const geometry = useMemo(() => {
    if (!pack) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pack.xyz.data), 3));
    g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(pack.nNodes * 3), 3));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(pack.tris.data), 1));
    g.computeBoundingBox();
    return g;
  }, [pack]);
  const box = geometry?.boundingBox || null;
  const diag = useMemo(() => (box ? box.getSize(new THREE.Vector3()).length() : 1), [box]);

  const fieldData = useMemo(() => {
    if (!pack || !result) return null;
    const t0 = performance.now();
    const out = reconstruct(pack, result.coefficients, result.lambda, result.mu);
    out.ms = performance.now() - t0;
    return out;
  }, [pack, result]);

  // auto warp: the largest displacement drawn as 5 % of the model size, times the slider
  const autoWarp = fieldData && fieldData.maxDisp > 0 ? (0.05 * diag) / (fieldData.maxDisp * 1000) : 0;

  useEffect(() => {
    if (!geometry || !fieldData) return;
    const pos = geometry.attributes.position.array;
    const col = geometry.attributes.color.array;
    const xyz = pack.xyz.data;
    const k = autoWarp * warp * 1000;                  // m → mm, scaled
    const vals = field === 'vm' ? fieldData.vm : fieldData.dispMag;
    const vmax = field === 'vm' ? fieldData.maxVm : fieldData.maxDisp;
    for (let i = 0; i < pack.nNodes; i += 1) {
      for (let c = 0; c < 3; c += 1) pos[3 * i + c] = xyz[3 * i + c] + k * fieldData.disp[3 * i + c];
      col.set(colormap(vmax > 0 ? vals[i] / vmax : 0), 3 * i);
    }
    geometry.attributes.position.needsUpdate = true;
    geometry.attributes.color.needsUpdate = true;
    geometry.computeVertexNormals();
  }, [geometry, fieldData, field, warp, autoWarp, pack]);

  if (!activeROM && !loadingROM) return null;
  const variable = (activeROM?.parameters || []).filter((p) => p.variable);
  const fixed = (activeROM?.parameters || []).filter((p) => !p.variable);
  const s = activeROM?.summary || {};
  const fs = yieldMPa && result ? Number(yieldMPa) / result.max_von_mises_mpa : null;

  const onFullRun = async () => {
    setVerify({ status: 'queued' });
    try {
      const d = await fullRun();
      setVerify({ status: 'running', runId: d.run_id });
      const poll = async () => {
        const r = await compare(d.run_id);
        if (r.status === 202) { setTimeout(poll, 2000); return; }
        setVerify({ status: 'done', ...r.data });
      };
      setTimeout(poll, 2000);
    } catch (e) {
      setVerify({ status: 'error', message: e.response?.data?.error || e.message });
    }
  };

  return (
    <Dialog open onClose={closeExplorer} maxWidth="xl" fullWidth
      PaperProps={{ sx: { bgcolor: '#1a1a1a', color: '#ddd', height: '90vh' } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: 15, py: 1 }}>
        <Bolt sx={{ color: '#ffb74d' }} />
        <Box sx={{ flex: 1 }}>ROM Explorer — respuesta en tiempo real</Box>
        <IconButton size="small" onClick={closeExplorer} sx={{ color: '#888' }}><Close fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ p: 0, borderColor: '#333', display: 'flex', minHeight: 0 }}>
        <Box sx={{ width: 340, p: 2, overflow: 'auto', borderRight: '1px solid #333', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {loadingROM && <CircularProgress size={20} />}
          {error && <Alert severity="error" sx={{ fontSize: 12 }}>{error}</Alert>}
          {variable.map((p) => (
            <Box key={p.key}>
              <Typography sx={label}>
                {p.label}: <b style={{ color: '#fff' }}>{fmtParam(p, params[p.key])} {p.display_unit}</b>
              </Typography>
              <Slider size="small" min={p.range[0]} max={p.range[1]} step={(p.range[1] - p.range[0]) / 200}
                value={params[p.key]} onChange={(_, v) => setParam(p.key, v)}
                valueLabelDisplay="auto" valueLabelFormat={(v) => fmtParam(p, v)} />
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: -1 }}>
                <Typography variant="caption" sx={{ color: '#666' }}>{fmtParam(p, p.range[0])}</Typography>
                <Typography variant="caption" sx={{ color: '#666' }}>{fmtParam(p, p.range[1])}</Typography>
              </Box>
            </Box>
          ))}
          {fixed.length > 0 && (
            <Typography variant="caption" sx={{ color: '#777' }}>
              Fijos: {fixed.map((p) => `${p.label.split(' (')[0]} ${fmtParam(p, p.nominal)} ${p.display_unit}`).join(' · ')}
            </Typography>
          )}
          <Divider sx={{ borderColor: '#333' }} />
          {result && (
            <Box sx={{ fontSize: 13, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
              <div>Von Mises máx.: <b>{result.max_von_mises_mpa.toFixed(2)} MPa</b></div>
              <div>Desplazamiento máx.: <b>{result.max_displacement_mm.toPrecision(4)} mm</b></div>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <TextField size="small" label="Límite elástico [MPa]" type="number" value={yieldMPa}
                  onChange={(e) => setYieldMPa(e.target.value)} sx={{ width: 150 }}
                  inputProps={{ style: { color: '#fff' } }} InputLabelProps={{ style: { color: '#888' } }} />
                {fs && (
                  <Chip size="small" label={`FS ${fs.toFixed(2)}`}
                    color={fs < 1 ? 'error' : fs < 1.5 ? 'warning' : 'success'} />
                )}
              </Box>
              {!result.within_range && (
                <Alert severity="warning" sx={{ fontSize: 11, py: 0 }}>Fuera del rango entrenado: el error puede crecer.</Alert>
              )}
            </Box>
          )}
          <Box sx={{ bgcolor: '#141414', border: '1px solid #333', borderRadius: 1, p: 1, fontSize: 11, color: '#aaa' }}>
            <div>
              Respuesta: <b style={{ color: responseTime != null && responseTime < 100 ? '#81c784' : '#ffb74d' }}>
                {responseTime != null ? `${responseTime.toFixed(1)} ms` : '—'}</b>
              {result && ` (servidor ${result.response_ms.toFixed(2)} ms, campo ${fieldData ? fieldData.ms.toFixed(1) : '—'} ms)`}
            </div>
            <div>Modos ROM: {s.n_modes} / {s.n_snapshots} snapshots · energía {s.energy_captured != null ? (100 * s.energy_captured).toFixed(8) : '—'} %</div>
            <div>Error de validación: u {s.validation_max_error_u != null ? s.validation_max_error_u.toExponential(1) : '—'} ·
              {' '}σvM {s.validation_max_error_vm != null ? s.validation_max_error_vm.toExponential(1) : '—'}</div>
            <div>Malla: {s.n_nodes?.toLocaleString()} nodos {s.element_type} · superficie {pack?.nNodes?.toLocaleString()} nodos</div>
          </Box>
          <Button variant="outlined" size="small" startIcon={<PlayArrow />} onClick={onFullRun}
            disabled={verify?.status === 'queued' || verify?.status === 'running'}>
            Correr simulación completa con estos parámetros
          </Button>
          {verify?.status === 'running' && (
            <Typography variant="caption" sx={{ color: '#aaa' }}><CircularProgress size={10} /> Simulación completa en curso…</Typography>
          )}
          {verify?.status === 'done' && (
            <Alert severity={verify.error_u < 1e-3 ? 'success' : 'warning'} sx={{ fontSize: 11 }}>
              Completa vs ROM: error en u {verify.error_u.toExponential(2)} · σvM {verify.full.max_von_mises_mpa?.toFixed(2)} vs
              {' '}{verify.rom.max_von_mises_mpa.toFixed(2)} MPa · {verify.full.wall_time_s?.toFixed(1)} s vs {verify.rom.response_ms.toFixed(2)} ms
            </Alert>
          )}
          {verify?.status === 'error' && <Alert severity="error" sx={{ fontSize: 11 }}>{verify.message}</Alert>}
        </Box>
        <Box sx={{ flex: 1, position: 'relative', minWidth: 0 }}>
          <Canvas camera={{ fov: 40, position: [300, 200, 400] }} onCreated={({ gl }) => gl.setClearColor('#20242a')}>
            <ambientLight intensity={0.5} />
            <hemisphereLight args={['#e8eef7', '#30343a', 0.6]} />
            <directionalLight position={[1, 2, 1.5]} intensity={0.9} />
            <directionalLight position={[-1.5, -1, -1]} intensity={0.35} />
            <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
            {geometry && <FieldMesh geometry={geometry} />}
            <FitOnce box={box} />
            <GizmoHelper alignment="bottom-left" margin={[56, 56]}>
              <GizmoViewport axisColors={['#ff4060', '#80ff40', '#4080ff']} labelColor="white" />
            </GizmoHelper>
          </Canvas>
          <Box sx={{ position: 'absolute', top: 8, left: 8, right: 8, display: 'flex', alignItems: 'center', gap: 2 }}>
            <ToggleButtonGroup size="small" exclusive value={field} onChange={(_, v) => v && setField(v)}
              sx={{ bgcolor: '#1a1a1a' }}>
              <ToggleButton value="vm" sx={{ fontSize: 11, py: 0.25 }}>Von Mises</ToggleButton>
              <ToggleButton value="u" sx={{ fontSize: 11, py: 0.25 }}>|u|</ToggleButton>
            </ToggleButtonGroup>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="caption" sx={{ color: '#aaa' }}>0</Typography>
              <Box sx={{ width: 140, height: 8, borderRadius: 1,
                background: COLORBAR_CSS }} />
              <Typography variant="caption" sx={{ color: '#aaa' }}>
                {fieldData ? (field === 'vm' ? `${(fieldData.maxVm / 1e6).toFixed(1)} MPa (superficie)`
                  : `${(fieldData.maxDisp * 1000).toPrecision(3)} mm`) : ''}
              </Typography>
            </Box>
            <Tooltip title="Factor de deformación (1 = desplazamiento máximo dibujado como 5 % del modelo)">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: 220 }}>
                <Typography variant="caption" sx={{ color: '#aaa', whiteSpace: 'nowrap' }}>
                  Deformación ×{(autoWarp * warp).toPrecision(2)}
                </Typography>
                <Slider size="small" min={0} max={3} step={0.1} value={warp} onChange={(_, v) => setWarp(v)} />
              </Box>
            </Tooltip>
          </Box>
        </Box>
      </DialogContent>
    </Dialog>
  );
}
