/**
 * FluidFields — Newtonian fluid MATERIAL node (model_type = newtonian_fluid): dynamic viscosity μ [Pa·s].
 * Steady Stokes flow (creeping, Re ≪ 1), T10 meshes only (Taylor-Hood P2-P1). ρ (above) is used for gravity
 * and the Reynolds-number check.
 */
import React from 'react';
import { Box, Button, TextField, Typography } from '@mui/material';

export const FLUID_PRESETS = [
  ['Agua 20 °C', { mu: 1.002e-3, rho: 998 }],
  ['Glicerina 20 °C', { mu: 1.41, rho: 1261 }],
  ['Aceite SAE 30', { mu: 0.29, rho: 875 }],
];

export default function FluidFields({ props, setProp }) {
  return (
    <Box data-testid="fluid-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #1a3b5a', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#90caf9' }}>
        Fluido newtoniano · Stokes estacionario (flujo lento, Re ≪ 1) · requiere malla T10
      </Typography>
      <TextField label="Viscosidad dinámica μ [Pa·s]" size="small" fullWidth type="number"
        value={props.mu ?? ''}
        onChange={(e) => setProp('mu', e.target.value === '' ? null : parseFloat(e.target.value))}
        inputProps={{ style: { color: '#fff' }, 'aria-label': 'Viscosidad dinámica μ [Pa·s]' }}
        InputLabelProps={{ style: { color: '#888' } }} />
      {(props.mu == null || props.mu === '') && (
        <Typography variant="caption" sx={{ color: '#ef9a9a' }}>Falta la viscosidad μ.</Typography>
      )}
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        {FLUID_PRESETS.map(([name, vals]) => (
          <Button key={name} size="small" variant="outlined"
            onClick={() => Object.entries(vals).forEach(([k, v]) => setProp(k, v))}>{name}</Button>
        ))}
      </Box>
    </Box>
  );
}
