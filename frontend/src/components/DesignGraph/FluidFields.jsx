/**
 * FluidFields — Newtonian fluid MATERIAL node (model_type = newtonian_fluid): dynamic viscosity μ [Pa·s] and
 * flow model: Stokes (creeping, Re ≪ 1) or steady laminar Navier–Stokes (convection, needs ρ > 0). T10 meshes
 * only (Taylor-Hood P2-P1). ρ (above) is used for gravity, inertia and the Reynolds-number check.
 */
import React from 'react';
import {
  Box, Button, FormControlLabel, Switch, TextField, Typography, ToggleButton, ToggleButtonGroup,
} from '@mui/material';

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
        Fluido newtoniano estacionario · requiere malla T10
      </Typography>
      <ToggleButtonGroup size="small" exclusive value={props.flow_model || 'stokes'} aria-label="Modelo de flujo"
        onChange={(_, v) => { if (v) setProp('flow_model', v); }}>
        <ToggleButton value="stokes" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>Stokes (Re ≪ 1)</ToggleButton>
        <ToggleButton value="navier_stokes" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>Navier-Stokes laminar</ToggleButton>
      </ToggleButtonGroup>
      <Typography variant="caption" sx={{ color: '#888' }}>
        {(props.flow_model || 'stokes') === 'navier_stokes'
          ? 'Incluye la inercia ρ(v·∇)v (Picard + Newton). Válido para flujo laminar estacionario (Re hasta ~10³).'
          : 'Flujo lento: desprecia la inercia. Si el resultado avisa Re > 1, cambie a Navier-Stokes.'}
      </Typography>
      {props.flow_model === 'navier_stokes' && (
        <>
          <FormControlLabel
            control={<Switch size="small" checked={props.stabilization === 'supg'}
              onChange={(e) => setProp('stabilization', e.target.checked ? 'supg' : null)}
              inputProps={{ 'aria-label': 'Estabilización SUPG' }} />}
            label={<Typography variant="caption" sx={{ color: '#bbb' }}>Estabilización SUPG</Typography>} />
          <Typography variant="caption" sx={{ color: '#777' }}>
            Actívela si el resultado avisa Reynolds de elemento &gt; 100 (convección dominante, malla gruesa): evita
            oscilaciones y ayuda a converger. En flujos bien resueltos resta algo de precisión; ahí es mejor sin ella.
          </Typography>
        </>
      )}
      {(props.flow_model === 'navier_stokes') && !(props.rho > 0) && (
        <Typography variant="caption" sx={{ color: '#ef9a9a' }}>Navier-Stokes necesita la densidad ρ &gt; 0.</Typography>
      )}
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
