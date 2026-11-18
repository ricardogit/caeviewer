/**
 * MagneticFields — magnetic MATERIAL node (model_type = linear_magnetic): relative permeability μr, remanent flux
 * density Br [T] (permanent magnet, global axes) and optional saturation (B-H curve: tanh model with μr initial and
 * saturation polarisation Js, or a table of H [A/m], B [T] points). Scalar potential, one material region.
 * CoilFields — BC «Bobina» (bc_type = coil): N turns × I amperes as the potential of the coil's pole faces,
 * swept in `current_steps` steps (magnetisation curve λ(I), secant and incremental inductance).
 */
import React, { useEffect, useState } from 'react';
import { Box, Button, MenuItem, Select, TextField, Typography } from '@mui/material';

export const MAGNETIC_PRESETS = [
  ['Acero eléctrico', { mu_r: 4000, Br_x: 0, Br_y: 0, Br_z: 0, saturation: 'none' }],
  ['Acero eléctrico saturable', { mu_r: 4000, Js: 2.0, Br_x: 0, Br_y: 0, Br_z: 0, saturation: 'tanh' }],
  ['Ferrita blanda saturable', { mu_r: 2000, Js: 0.45, Br_x: 0, Br_y: 0, Br_z: 0, saturation: 'tanh' }],
  ['NdFeB N42 (+Z)', { mu_r: 1.05, Br_x: 0, Br_y: 0, Br_z: 1.3, saturation: 'none' }],
  ['Ferrita (+Z)', { mu_r: 1.1, Br_x: 0, Br_y: 0, Br_z: 0.4, saturation: 'none' }],
  ['Aire', { mu_r: 1, Br_x: 0, Br_y: 0, Br_z: 0, saturation: 'none' }],
];

const num = (props, setProp, k, label) => (
  <TextField key={k} label={label} size="small" type="number" sx={{ flex: 1 }}
    value={props[k] ?? ''}
    onChange={(e) => setProp(k, e.target.value === '' ? null : parseFloat(e.target.value))}
    inputProps={{ style: { color: '#fff' }, 'aria-label': label }}
    InputLabelProps={{ style: { color: '#888' } }} />
);

/** "H B" per line (space, tab, ; or , between the two numbers) → [[H, B], …]; bad lines are skipped. */
export function parseBH(text) {
  return (text || '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
    .map((l) => l.split(/[\s;,]+/).map(Number))
    .filter((p) => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]))
    .map((p) => [p[0], p[1]]);
}

function BHTable({ points, setProp }) {
  const [text, setText] = useState(() => (points || []).map((p) => `${p[0]} ${p[1]}`).join('\n'));
  useEffect(() => {
    if (!points?.length) return;
    const cur = parseBH(text);
    if (JSON.stringify(cur) !== JSON.stringify(points)) setText(points.map((p) => `${p[0]} ${p[1]}`).join('\n'));
  }, [points]); // eslint-disable-line react-hooks/exhaustive-deps
  const n = parseBH(text).length;
  return (
    <>
      <TextField label="Curva B-H: H [A/m]  B [T] por línea" size="small" fullWidth multiline minRows={4}
        value={text}
        onChange={(e) => { setText(e.target.value); setProp('bh_points', parseBH(e.target.value)); }}
        inputProps={{ style: { color: '#fff', fontFamily: 'monospace', fontSize: 12 }, 'aria-label': 'Curva B-H' }}
        InputLabelProps={{ style: { color: '#888' } }} />
      <Typography variant="caption" sx={{ color: n >= 2 ? '#777' : '#ef9a9a' }}>
        {n} puntos (H y B crecientes; tras el último punto la pendiente es μ₀).
      </Typography>
    </>
  );
}

export default function MagneticFields({ props, setProp }) {
  const sat = props.saturation || 'none';
  return (
    <Box data-testid="magnetic-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #3b2a5a', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#ce93d8' }}>
        Magnetostática · potencial escalar · bobinas como fuerza magnetomotriz entre caras · una sola región de material
      </Typography>
      {num(props, setProp, 'mu_r', sat === 'tanh' ? 'μr inicial' : 'Permeabilidad relativa μr')}
      {sat !== 'table' && (props.mu_r == null || props.mu_r === '') && (
        <Typography variant="caption" sx={{ color: '#ef9a9a' }}>Falta la permeabilidad μr.</Typography>
      )}
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        <Typography variant="caption" sx={{ color: '#bbb', flex: 1 }}>Saturación</Typography>
        <Select size="small" value={sat} onChange={(e) => setProp('saturation', e.target.value)}
          sx={{ color: '#fff', flex: 2 }} inputProps={{ 'aria-label': 'Saturación' }}>
          <MenuItem value="none">Lineal (sin saturación)</MenuItem>
          <MenuItem value="tanh">Modelo μr inicial + Js</MenuItem>
          <MenuItem value="table">Tabla B-H</MenuItem>
        </Select>
      </Box>
      {sat === 'tanh' && (
        <>
          {num(props, setProp, 'Js', 'Polarización de saturación Js [T]')}
          <Typography variant="caption" sx={{ color: '#777' }}>
            B = μ₀H + Js·tanh(μ₀(μr − 1)H / Js). Valores de los presets orientativos: use la curva del fabricante
            (tabla) para diseño.
          </Typography>
        </>
      )}
      {sat === 'table' && <BHTable points={props.bh_points} setProp={setProp} />}
      {sat === 'none' && (
        <>
          <Typography variant="caption" sx={{ color: '#888' }}>Remanencia Br del imán [T] (0 = material blando)</Typography>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {num(props, setProp, 'Br_x', 'Br x [T]')}
            {num(props, setProp, 'Br_y', 'Br y [T]')}
            {num(props, setProp, 'Br_z', 'Br z [T]')}
          </Box>
        </>
      )}
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        {MAGNETIC_PRESETS.map(([name, vals]) => (
          <Button key={name} size="small" variant="outlined"
            onClick={() => Object.entries(vals).forEach(([k, v]) => setProp(k, v))}>{name}</Button>
        ))}
      </Box>
      <Typography variant="caption" sx={{ color: '#777' }}>
        BC «Potencial magnético» = cara de polo contra hierro ideal (B normal); BC «Bobina» = N·I amperios-vuelta
        entre su cara y la de referencia (corte del núcleo). Caras sin condición: el flujo no las atraviesa (Bn = 0).
        Sin entrehierros de aire (requieren varias regiones de material).
      </Typography>
    </Box>
  );
}

export function CoilFields({ props, setProp, showFaceSet }) {
  const mmf = Number(props.turns) * Number(props.current);
  return (
    <Box data-testid="coil-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num(props, setProp, 'turns', 'Vueltas N')}
        {num(props, setProp, 'current', 'Corriente I [A]')}
        {num(props, setProp, 'current_steps', 'Pasos de corriente')}
      </Box>
      {Number.isFinite(mmf) && (
        <Typography variant="caption" sx={{ color: '#ce93d8' }}>Fuerza magnetomotriz N·I = {mmf.toPrecision(4)} A·vuelta</Typography>
      )}
      <Typography variant="caption" sx={{ color: '#777' }}>
        Aplica ψ = N·I en las caras de la bobina; necesita otra BC «Potencial magnético» (ψ = 0) en la otra cara del
        corte. Con saturación se barre la corriente (10 pasos por defecto) → λ(I), inductancia secante e incremental.
      </Typography>
      {showFaceSet && (
        <TextField label="Conjunto de caras (viga de prueba)" size="small" fullWidth
          value={props.face_set || ''}
          onChange={(e) => setProp('face_set', e.target.value || null)}
          placeholder="tip (fixed, tip, y0, y1, z0, z1)"
          inputProps={{ style: { color: '#fff' } }}
          InputLabelProps={{ style: { color: '#888' } }} />
      )}
    </Box>
  );
}
