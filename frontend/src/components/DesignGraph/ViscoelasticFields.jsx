/**
 * ViscoelasticFields — generalized Maxwell MATERIAL node (model_type = viscoelastic_maxwell): Prony series
 * of the relaxation modulus E(t) = E₀[g∞ + Σ gᵢ e^(−t/τᵢ)] (E is E₀, ν constant) and the time settings
 * of the quasi-static analysis (load history, final time, steps).
 */
import React from 'react';
import { Box, Button, FormControl, IconButton, InputLabel, MenuItem, Select, TextField, Typography } from '@mui/material';
import { Close } from '@mui/icons-material';

export const LOAD_HISTORIES = [
  ['creep', 'Escalón mantenido (fluencia / relajación)'],
  ['ramp', 'Rampa y mantenimiento'],
  ['recovery', 'Fluencia y recuperación (descarga)'],
];

export default function ViscoelasticFields({ props, setProp }) {
  const terms = props.prony_terms || [];
  const gSum = terms.reduce((a, t) => a + (Number(t.g) || 0), 0);
  const tauMax = Math.max(0, ...terms.map(t => Number(t.tau) || 0));
  const kind = props.load_history || 'creep';
  const setTerm = (i, k, v) => setProp('prony_terms', terms.map((t, j) => (j === i ? { ...t, [k]: v } : t)));
  const num = (k, lbl, ph = '') => (
    <TextField key={k} label={lbl} size="small" type="number" placeholder={ph} sx={{ flex: 1 }}
      value={props[k] ?? ''}
      onChange={(e) => setProp(k, e.target.value === '' ? null : parseFloat(e.target.value))}
      inputProps={{ style: { color: '#fff' }, 'aria-label': lbl }}
      InputLabelProps={{ style: { color: '#888' } }} />
  );
  return (
    <Box data-testid="viscoelastic-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #3e2f4a', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#ce93d8' }}>
        Maxwell generalizado · E es el módulo instantáneo E₀; E(t) = E₀[g∞ + Σ gᵢ e^(−t/τᵢ)]
      </Typography>
      {terms.map((t, i) => (
        <Box key={i} sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          <TextField label={`g${i + 1}`} size="small" type="number" sx={{ flex: 1 }} value={t.g ?? ''}
            onChange={(e) => setTerm(i, 'g', e.target.value === '' ? null : parseFloat(e.target.value))}
            inputProps={{ step: 0.05, style: { color: '#fff' }, 'aria-label': `g${i + 1}` }}
            InputLabelProps={{ style: { color: '#888' } }} />
          <TextField label={`τ${i + 1} [s]`} size="small" type="number" sx={{ flex: 1 }} value={t.tau ?? ''}
            onChange={(e) => setTerm(i, 'tau', e.target.value === '' ? null : parseFloat(e.target.value))}
            inputProps={{ style: { color: '#fff' }, 'aria-label': `tau${i + 1}` }}
            InputLabelProps={{ style: { color: '#888' } }} />
          <IconButton size="small" aria-label={`quitar término ${i + 1}`}
            onClick={() => setProp('prony_terms', terms.filter((_, j) => j !== i))}>
            <Close sx={{ fontSize: 14, color: '#888' }} />
          </IconButton>
        </Box>
      ))}
      <Button size="small" onClick={() => setProp('prony_terms', [...terms, { g: 0.3, tau: 10 }])}>
        + término de Prony
      </Button>
      <Typography variant="caption" sx={{ color: gSum >= 1 || !terms.length ? '#ef9a9a' : '#bbb' }}>
        {terms.length ? `Σg = ${gSum.toFixed(3)} → E∞ = ${(1 - gSum).toFixed(3)}·E₀` : 'Falta al menos un término.'}
        {gSum >= 1 ? ' (Σg debe ser < 1)' : ''}
      </Typography>
      <FormControl size="small" fullWidth>
        <InputLabel sx={{ color: '#888' }}>Historia de carga</InputLabel>
        <Select value={kind} label="Historia de carga" sx={{ color: '#fff' }}
          onChange={(e) => setProp('load_history', e.target.value)}>
          {LOAD_HISTORIES.map(([k, lbl]) => <MenuItem key={k} value={k}>{lbl}</MenuItem>)}
        </Select>
      </FormControl>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num('t_end', 'Tiempo final [s]', tauMax ? String(10 * tauMax) : '')}
        {num('time_steps', 'Pasos', '40')}
        {kind === 'ramp' && num('t_ramp', 't rampa [s]')}
        {kind === 'recovery' && num('t_unload', 't descarga [s]')}
      </Box>
    </Box>
  );
}
