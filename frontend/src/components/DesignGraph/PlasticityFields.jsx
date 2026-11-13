/**
 * PlasticityFields — FASE 2.5: J2 (von Mises) plasticity settings of a MATERIAL node
 * (model_type = elastoplastic_vonmises). σy is the node's yield_strength field.
 */
import React from 'react';
import { Box, Checkbox, FormControl, FormControlLabel, InputLabel, MenuItem, Select, TextField, Typography } from '@mui/material';

export const HARDENING = [
  ['perfect', 'Perfectamente plástico'],
  ['linear', 'Lineal (H)'],
  ['voce', 'Voce (saturación)'],
  ['fit', 'Curva del ensayo ajustado'],
];

export function defaultHardening(props) {
  return props.hardening_type || (props.hardening_table ? 'fit' : props.H ? 'linear' : 'perfect');
}

export default function PlasticityFields({ props, setProp }) {
  const kind = defaultHardening(props);
  const num = (k, lbl, ph = '') => (
    <TextField key={k} label={lbl} size="small" type="number" placeholder={ph} sx={{ flex: 1 }}
      value={props[k] ?? ''}
      onChange={(e) => setProp(k, e.target.value === '' ? null : parseFloat(e.target.value))}
      inputProps={{ style: { color: '#fff' }, 'aria-label': lbl }}
      InputLabelProps={{ style: { color: '#888' } }} />
  );
  return (
    <Box data-testid="plasticity-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #4e342e', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#ffcc80' }}>
        Plasticidad J2 (von Mises) · Newton-Raphson con pasos de carga
      </Typography>
      {!props.yield_strength && (
        <Typography variant="caption" sx={{ color: '#ef9a9a' }}>Falta el límite elástico σy.</Typography>
      )}
      <FormControl size="small" fullWidth>
        <InputLabel sx={{ color: '#888' }}>Endurecimiento</InputLabel>
        <Select value={kind} label="Endurecimiento" sx={{ color: '#fff' }}
          onChange={(e) => setProp('hardening_type', e.target.value)}>
          {HARDENING.map(([k, lbl]) => (
            <MenuItem key={k} value={k} disabled={k === 'fit' && !props.hardening_table}>{lbl}</MenuItem>
          ))}
        </Select>
      </FormControl>
      {kind === 'linear' && num('H', 'Módulo plástico H [Pa]', 'ej: 2e9')}
      {kind === 'voce' && (
        <Box sx={{ display: 'flex', gap: 1 }}>
          {num('hardening_Q', 'Q [Pa]', '1.2e8')}
          {num('hardening_b', 'b', '40')}
          {num('H', 'H [Pa]', '0')}
        </Box>
      )}
      {kind === 'fit' && props.hardening_table && (
        <Typography variant="caption" sx={{ color: '#bbb' }}>
          {props.hardening_table.sy.length} puntos de la ley {props.hardening_table.model || ''}: σy de{' '}
          {(props.hardening_table.sy[0] / 1e6).toFixed(0)} a{' '}
          {(props.hardening_table.sy[props.hardening_table.sy.length - 1] / 1e6).toFixed(0)} MPa con εp hasta{' '}
          {(100 * props.hardening_table.ep[props.hardening_table.ep.length - 1]).toFixed(1)} %.
        </Typography>
      )}
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
        {num('load_steps', 'Pasos de carga', '10')}
        <FormControlLabel sx={{ flex: 1, color: '#bbb', '& .MuiTypography-root': { fontSize: 12 } }}
          control={<Checkbox size="small" checked={!!props.unload} onChange={(e) => setProp('unload', e.target.checked)} />}
          label="Descargar al final" />
      </Box>
    </Box>
  );
}
