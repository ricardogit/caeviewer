/**
 * UncertaintyBand — FASE 6: 3D view of a Monte Carlo study. The surface is drawn deformed by the
 * mean displacement and coloured by the mean, the standard deviation or the upper confidence
 * quantile of σvM / |u|; the optional envelope is a semi-transparent shell deformed to the upper
 * quantile of |u| (double field: mean + spread).
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import {
  Box, Dialog, DialogTitle, DialogContent, IconButton, Typography, ToggleButtonGroup, ToggleButton, Slider,
  FormControlLabel, Checkbox,
} from '@mui/material';
import { Close } from '@mui/icons-material';
import useUncertaintyStore from '../../stores/uncertaintyStore';
import { colormap, COLORBAR_CSS } from '../../utils/colormap';

const FIELDS = [
  ['vm_mean', 'σvM media', 1e-6, 'MPa'],
  ['vm_std', 'σvM desviación', 1e-6, 'MPa'],
  ['vm_high', 'σvM IC sup.', 1e-6, 'MPa'],
  ['u_mean', '|u| media', 1e3, 'mm'],
  ['u_std', '|u| desviación', 1e3, 'mm'],
];

function Fit({ box }) {
  const { camera, controls } = useThree();
  const done = useRef(false);
  useEffect(() => {
    if (!box || done.current) return;
    done.current = true;
    const c = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    camera.position.copy(c).add(new THREE.Vector3(0.6, 0.45, 1).normalize().multiplyScalar(size * 1.4));
    camera.near = size / 1000;
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    if (controls) { controls.target.copy(c); controls.update(); }
  }, [box, camera, controls]);
  return null;
}

export function surfaceStats(values) {
  let max = 0;
  for (let i = 0; i < values.length; i += 1) if (values[i] > max) max = values[i];
  return { max };
}

export default function UncertaintyBand({ onClose }) {
  const surface = useUncertaintyStore((s) => s.surface);
  const [field, setField] = useState('vm_mean');
  const [warp, setWarp] = useState(1);
  const [envelope, setEnvelope] = useState(true);

  const geo = useMemo(() => {
    if (!surface) return null;
    const make = () => {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(surface.xyz.data), 3));
      g.setIndex(new THREE.BufferAttribute(new Uint32Array(surface.tris.data), 1));
      return g;
    };
    const main = make();
    main.setAttribute('color', new THREE.BufferAttribute(new Float32Array(surface.nNodes * 3), 3));
    main.computeBoundingBox();
    return { main, ghost: make() };
  }, [surface]);

  const diag = useMemo(() => (geo ? geo.main.boundingBox.getSize(new THREE.Vector3()).length() : 1), [geo]);
  const maxU = useMemo(() => (surface ? surfaceStats(surface.u_high.data).max : 0), [surface]);
  const auto = maxU > 0 ? (0.05 * diag) / (maxU * 1000) : 0;       // max upper |u| drawn as 5 % of the size
  const [, , scale, unit] = FIELDS.find((f) => f[0] === field);
  const vmax = useMemo(() => (surface ? surfaceStats(surface[field].data).max : 1), [surface, field]);

  useEffect(() => {
    if (!geo) return;
    const xyz = surface.xyz.data;
    const d = surface.disp_mean.data;
    const um = surface.u_mean.data;
    const uh = surface.u_high.data;
    const vals = surface[field].data;
    const k = auto * warp * 1000;
    const p = geo.main.attributes.position.array;
    const q = geo.ghost.attributes.position.array;
    const col = geo.main.attributes.color.array;
    for (let i = 0; i < surface.nNodes; i += 1) {
      const f = um[i] > 0 ? uh[i] / um[i] : 1;
      for (let c = 0; c < 3; c += 1) {
        p[3 * i + c] = xyz[3 * i + c] + k * d[3 * i + c];
        q[3 * i + c] = xyz[3 * i + c] + k * f * d[3 * i + c];
      }
      col.set(colormap(vmax > 0 ? vals[i] / vmax : 0), 3 * i);
    }
    ['main', 'ghost'].forEach((g) => {
      geo[g].attributes.position.needsUpdate = true;
      geo[g].computeVertexNormals();
    });
    geo.main.attributes.color.needsUpdate = true;
  }, [geo, surface, field, warp, auto, vmax]);

  return (
    <Dialog open onClose={onClose} maxWidth="lg" fullWidth PaperProps={{ sx: { bgcolor: '#1a1a1a', color: '#ddd', height: '85vh' } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', fontSize: 15, py: 1 }}>
        <Box sx={{ flex: 1 }}>Bandas de confianza (IC {Math.round((surface?.confidence || 0.95) * 100)} %)</Box>
        <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}><Close fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ p: 0, position: 'relative', borderColor: '#333' }}>
        <Canvas camera={{ fov: 40, position: [300, 200, 400] }} onCreated={({ gl }) => gl.setClearColor('#20242a')}>
          <ambientLight intensity={0.5} />
          <hemisphereLight args={['#e8eef7', '#30343a', 0.6]} />
          <directionalLight position={[1, 2, 1.5]} intensity={0.9} />
          <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
          {geo && (
            <mesh geometry={geo.main}>
              <meshStandardMaterial vertexColors side={THREE.DoubleSide} roughness={0.6} />
            </mesh>
          )}
          {geo && envelope && (
            <mesh geometry={geo.ghost}>
              <meshStandardMaterial color="#ffb74d" transparent opacity={0.22} depthWrite={false} side={THREE.DoubleSide} />
            </mesh>
          )}
          <Fit box={geo?.main.boundingBox} />
        </Canvas>
        <Box sx={{ position: 'absolute', top: 8, left: 8, right: 8, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <ToggleButtonGroup size="small" exclusive value={field} onChange={(_, v) => v && setField(v)} sx={{ bgcolor: '#1a1a1a' }}>
            {FIELDS.map(([k, l]) => <ToggleButton key={k} value={k} sx={{ fontSize: 11, py: 0.25 }}>{l}</ToggleButton>)}
          </ToggleButtonGroup>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="caption" sx={{ color: '#aaa' }}>0</Typography>
            <Box sx={{ width: 120, height: 8, borderRadius: 1, background: COLORBAR_CSS }} />
            <Typography variant="caption" sx={{ color: '#aaa' }}>{(vmax * scale).toPrecision(3)} {unit}</Typography>
          </Box>
          <FormControlLabel control={<Checkbox size="small" checked={envelope} onChange={(e) => setEnvelope(e.target.checked)} />}
            label={<Typography variant="caption">Envolvente |u| IC sup.</Typography>} />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: 200 }}>
            <Typography variant="caption" sx={{ color: '#aaa', whiteSpace: 'nowrap' }}>Deformación ×{(auto * warp).toPrecision(2)}</Typography>
            <Slider size="small" min={0} max={3} step={0.1} value={warp} onChange={(_, v) => setWarp(v)} />
          </Box>
        </Box>
      </DialogContent>
    </Dialog>
  );
}
