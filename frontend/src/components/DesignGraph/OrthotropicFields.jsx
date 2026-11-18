/**
 * OrthotropicFields — orthotropic MATERIAL node (model_type = linear_elastic_orthotropic): moduli along the
 * material axes 1-2-3, the axes in the global/CAD frame and optional per-axis conductivity / expansion.
 * νij = −εj/εi under uniaxial stress along i. Units: Pa, W/m·K, 1/K (same as the isotropic fields).
 */
import React from 'react';
import { Box, TextField, Typography } from '@mui/material';

export const ORTHO_KEYS = ['E1', 'E2', 'E3', 'G12', 'G13', 'G23', 'nu12', 'nu13', 'nu23'];
const ROWS = [
  [['E1', 'E1 [Pa]', '140e9'], ['E2', 'E2 [Pa]', '10e9'], ['E3', 'E3 [Pa]', '10e9']],
  [['G12', 'G12 [Pa]', '5e9'], ['G13', 'G13 [Pa]', '5e9'], ['G23', 'G23 [Pa]', '3.5e9']],
  [['nu12', 'ν12', '0.3'], ['nu13', 'ν13', '0.3'], ['nu23', 'ν23', '0.45']],
];
const DEFAULT_AXES = { axis_1: [1, 0, 0], axis_2: [0, 1, 0] };

export default function OrthotropicFields({ props, setProp }) {
  const num = (k, lbl, ph = '') => (
    <TextField key={k} label={lbl} size="small" type="number" placeholder={ph} sx={{ flex: 1 }}
      value={props[k] ?? ''}
      onChange={(e) => setProp(k, e.target.value === '' ? null : parseFloat(e.target.value))}
      inputProps={{ style: { color: '#fff' }, 'aria-label': lbl }}
      InputLabelProps={{ style: { color: '#888' } }} />
  );
  const axis = (key, title) => {
    const v = props[key] || DEFAULT_AXES[key];
    return (
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        <Typography variant="caption" sx={{ color: '#bbb', width: 44, flexShrink: 0 }}>{title}</Typography>
        {['x', 'y', 'z'].map((c, i) => (
          <TextField key={c} label={c} size="small" type="number" sx={{ flex: 1 }} value={v[i]}
            onChange={(e) => {
              const next = [...v];
              next[i] = e.target.value === '' ? 0 : parseFloat(e.target.value);
              setProp(key, next);
            }}
            inputProps={{ style: { color: '#fff' }, 'aria-label': `${title} ${c}` }}
            InputLabelProps={{ style: { color: '#888' } }} />
        ))}
      </Box>
    );
  };
  const missing = ORTHO_KEYS.filter(k => props[k] == null || props[k] === '');
  return (
    <Box data-testid="orthotropic-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #1a3b4a', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#80deea' }}>
        Ortótropo · constantes en los ejes del material (νij = −εj/εi con tracción en i)
      </Typography>
      {missing.length > 0 && (
        <Typography variant="caption" sx={{ color: '#ef9a9a' }}>Faltan: {missing.join(', ')}</Typography>
      )}
      {ROWS.map((row, i) => (
        <Box key={i} sx={{ display: 'flex', gap: 0.5 }}>{row.map(([k, lbl, ph]) => num(k, lbl, ph))}</Box>
      ))}
      <Typography variant="caption" sx={{ color: '#888' }}>
        Ejes del material en el sistema global/CAD (el eje 2 se ortogonaliza; eje 3 = 1 × 2)
      </Typography>
      {axis('axis_1', 'Eje 1')}
      {axis('axis_2', 'Eje 2')}
      <Typography variant="caption" sx={{ color: '#888' }}>
        Térmico por eje (opcional; si se dejan vacíos se usan k y α isótropos)
      </Typography>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num('k1', 'k1 [W/m·K]')}{num('k2', 'k2')}{num('k3', 'k3')}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num('alpha1', 'α1 [1/K]')}{num('alpha2', 'α2')}{num('alpha3', 'α3')}
      </Box>
    </Box>
  );
}
