/**
 * HyperelasticFields — Neo-Hookean MATERIAL node (model_type = hyperelastic_neohookean): large deformations,
 * total Lagrangian Newton with load steps. E and ν are the small-strain values (μ, λ derive from them).
 */
import React from 'react';
import { Box, TextField, Typography } from '@mui/material';

export default function HyperelasticFields({ props, setProp }) {
  const E = Number(props.E);
  const nu = Number(props.nu);
  const ok = E > 0 && nu > -1 && nu < 0.5;
  const mu = ok ? E / (2 * (1 + nu)) : null;
  const kappa = ok ? E / (3 * (1 - 2 * nu)) : null;
  return (
    <Box data-testid="hyperelastic-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #33402a', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#c5e1a5' }}>
        Neo-Hookean compresible · grandes deformaciones (Lagrangiano total, Newton)
      </Typography>
      {ok && (
        <Typography variant="caption" sx={{ color: '#bbb' }}>
          μ = {(mu / 1e6).toPrecision(4)} MPa · κ = {(kappa / 1e6).toPrecision(4)} MPa
          {nu > 0.49 ? ' · ν muy cercano a 0.5: posible bloqueo volumétrico, usa T10' : ''}
        </Typography>
      )}
      <TextField label="Pasos de carga" size="small" type="number" placeholder="10"
        value={props.load_steps ?? ''}
        onChange={(e) => setProp('load_steps', e.target.value === '' ? null : parseInt(e.target.value, 10))}
        inputProps={{ min: 1, max: 200, style: { color: '#fff' }, 'aria-label': 'Pasos de carga' }}
        InputLabelProps={{ style: { color: '#888' } }} />
      <Typography variant="caption" sx={{ color: '#888' }}>
        Cargas muertas: fuerza y presión conservan dirección y área de la configuración inicial.
      </Typography>
    </Box>
  );
}
