/**
 * MagneticFields — linear magnetic MATERIAL node (model_type = linear_magnetic): relative permeability μr and
 * remanent flux density Br [T] (permanent magnet, global axes). Current-free magnetostatics with a scalar
 * potential, one material region.
 */
import React from 'react';
import { Box, Button, TextField, Typography } from '@mui/material';

export const MAGNETIC_PRESETS = [
  ['Acero eléctrico', { mu_r: 4000, Br_x: 0, Br_y: 0, Br_z: 0 }],
  ['NdFeB N42 (+Z)', { mu_r: 1.05, Br_x: 0, Br_y: 0, Br_z: 1.3 }],
  ['Ferrita (+Z)', { mu_r: 1.1, Br_x: 0, Br_y: 0, Br_z: 0.4 }],
  ['Aire', { mu_r: 1, Br_x: 0, Br_y: 0, Br_z: 0 }],
];

const num = (props, setProp, k, label) => (
  <TextField key={k} label={label} size="small" type="number" sx={{ flex: 1 }}
    value={props[k] ?? ''}
    onChange={(e) => setProp(k, e.target.value === '' ? null : parseFloat(e.target.value))}
    inputProps={{ style: { color: '#fff' }, 'aria-label': label }}
    InputLabelProps={{ style: { color: '#888' } }} />
);

export default function MagneticFields({ props, setProp }) {
  return (
    <Box data-testid="magnetic-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #3b2a5a', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#ce93d8' }}>
        Magnetostática lineal · potencial escalar (sin bobinas ni corrientes) · una sola región de material
      </Typography>
      {num(props, setProp, 'mu_r', 'Permeabilidad relativa μr')}
      {(props.mu_r == null || props.mu_r === '') && (
        <Typography variant="caption" sx={{ color: '#ef9a9a' }}>Falta la permeabilidad μr.</Typography>
      )}
      <Typography variant="caption" sx={{ color: '#888' }}>Remanencia Br del imán [T] (0 = material blando)</Typography>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num(props, setProp, 'Br_x', 'Br x [T]')}
        {num(props, setProp, 'Br_y', 'Br y [T]')}
        {num(props, setProp, 'Br_z', 'Br z [T]')}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        {MAGNETIC_PRESETS.map(([name, vals]) => (
          <Button key={name} size="small" variant="outlined"
            onClick={() => Object.entries(vals).forEach(([k, v]) => setProp(k, v))}>{name}</Button>
        ))}
      </Box>
      <Typography variant="caption" sx={{ color: '#777' }}>
        BC «Potencial magnético» = cara de polo contra hierro ideal (B normal); la diferencia de potencial entre dos
        caras es la fuerza magnetomotriz (A·vuelta). Caras sin condición: el flujo no las atraviesa (Bn = 0).
      </Typography>
    </Box>
  );
}
