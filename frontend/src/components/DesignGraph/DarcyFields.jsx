/**
 * DarcyFields — MATERIAL «Medio poroso (Darcy)» (model_type = porous_medium, FASE 10.6): hydraulic conductivity K
 * (+ unit, vertical anisotropy Kz/Kh, heterogeneous zones by box), specific storage S_s, effective porosity
 * (pore velocity for transport), initial head, steady or transient (growing time steps for pumping tests) and
 * control points. HeadBCFields — BC «Carga hidráulica»; DarcyLoadFields — recharge, well (screen faces or a
 * point) and leakage (river bed / aquitard).
 */
import React from 'react';
import {
  Box, Button, FormControlLabel, IconButton, MenuItem, Select, Switch, TextField, Typography,
} from '@mui/material';
import { Add, Delete } from '@mui/icons-material';
import { ProbeList } from './TransportFields';

const txt = { style: { color: '#fff' } };
const lbl = { style: { color: '#888' } };
const toNum = (v) => (v === '' ? null : parseFloat(v));

const n = (props, setProp, k, label, def = '', sx = { flex: 1 }) => (
  <TextField key={k} label={label} size="small" type="number" sx={sx}
    value={props[k] ?? def}
    onChange={(e) => setProp(k, toNum(e.target.value))}
    inputProps={{ ...txt, 'aria-label': label }} InputLabelProps={lbl} />
);

const unitSelect = (props, setProp, k, units, def, aria) => (
  <Select size="small" value={props[k] || def} onChange={(e) => setProp(k, e.target.value)}
    sx={{ color: '#fff', minWidth: 72 }} inputProps={{ 'aria-label': aria }}>
    {units.map((u) => <MenuItem key={u} value={u}>{u}</MenuItem>)}
  </Select>
);

// typical orders of magnitude (Freeze & Cherry), not site data
export const AQUIFER_PRESETS = [
  ['Grava', { K: 1e-2, K_unit: 'm/s', porosity: 0.25, Ss: 1e-5 }],
  ['Arena', { K: 1e-4, K_unit: 'm/s', porosity: 0.3, Ss: 1e-4 }],
  ['Limo', { K: 1e-7, K_unit: 'm/s', porosity: 0.35, Ss: 1e-3 }],
  ['Arcilla', { K: 1e-9, K_unit: 'm/s', porosity: 0.4, Ss: 1e-2 }],
];

function ZoneRow({ z, i, onChange, onRemove, unit }) {
  const set = (k, v) => onChange({ ...z, [k]: v });
  return (
    <Box data-testid={`kzone-${i}`} sx={{ border: '1px solid #2a3550', borderRadius: 1, p: 0.75,
      display: 'flex', flexDirection: 'column', gap: 0.5 }}>
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        <TextField label="Zona" size="small" sx={{ flex: 2 }} value={z.label ?? ''}
          onChange={(e) => set('label', e.target.value)} inputProps={txt} InputLabelProps={lbl} />
        {n(z, set, 'K', `K [${unit}]`)}
        <IconButton size="small" onClick={onRemove} aria-label={`quitar zona ${i + 1}`} sx={{ color: '#e57373' }}>
          <Delete fontSize="small" />
        </IconButton>
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {['x0', 'y0', 'z0'].map((k) => n(z, set, k, `${k} mm`))}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {['x1', 'y1', 'z1'].map((k) => n(z, set, k, `${k} mm`))}
      </Box>
    </Box>
  );
}

export default function DarcyFields({ props, setProp }) {
  const zones = props.K_zones || [];
  const unit = props.K_unit || 'm/s';
  return (
    <Box data-testid="darcy-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #1f3a5a', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#90caf9' }}>
        Flujo subterráneo en acuífero confinado (Darcy): S_s ∂h/∂t = ∇·(K∇h) + Q · h = carga hidráulica [m]
      </Typography>
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        {AQUIFER_PRESETS.map(([name, vals]) => (
          <Button key={name} size="small" variant="outlined"
            onClick={() => Object.entries(vals).forEach(([k, v]) => setProp(k, v))}>{name}</Button>
        ))}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {n(props, setProp, 'K', 'Conductividad hidráulica K')}
        {unitSelect(props, setProp, 'K_unit', ['m/s', 'cm/s', 'm/d'], 'm/s', 'unidad de K')}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {n(props, setProp, 'Kz_ratio', 'Anisotropía Kz/Kh', 1)}
        {n(props, setProp, 'porosity', 'Porosidad eficaz n_e', 0.3)}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {n(props, setProp, 'Ss', 'Almacenamiento S_s [1/m]')}
        {n(props, setProp, 'initial_head', 'Carga inicial [m]', 0)}
      </Box>
      <Typography variant="caption" sx={{ color: '#777' }}>
        S_s solo interviene en el transitorio (coeficiente de almacenamiento S = S_s · espesor). La porosidad da la
        velocidad de poro v = q/n_e que usa un estudio de transporte.
      </Typography>

      <Typography variant="caption" sx={{ color: '#ccc' }}>Zonas de K (acuífero heterogéneo)</Typography>
      {zones.map((z, i) => (
        <ZoneRow key={i} z={z} i={i} unit={unit}
          onChange={(v) => setProp('K_zones', zones.map((x, j) => (j === i ? v : x)))}
          onRemove={() => setProp('K_zones', zones.filter((_, j) => j !== i))} />
      ))}
      <Button size="small" startIcon={<Add />} sx={{ alignSelf: 'flex-start' }}
        onClick={() => setProp('K_zones', [...zones, { label: `Zona ${zones.length + 1}`, K: props.K ?? null,
          x0: 0, y0: 0, z0: 0, x1: 0, y1: 0, z1: 0 }])}>
        Zona
      </Button>
      {zones.length > 0 && (
        <Typography variant="caption" sx={{ color: '#777' }}>
          Un elemento cuyo centro cae en la caja toma esa K (la última zona manda). Caja en mm, en el sistema de la
          geometría.
        </Typography>
      )}

      <FormControlLabel
        control={<Switch size="small" checked={!!props.transient} onChange={(e) => setProp('transient', e.target.checked)}
          inputProps={{ 'aria-label': 'Transitorio' }} />}
        label={<Typography variant="caption" sx={{ color: '#bbb' }}>Transitorio (ensayo de bombeo; si no: estacionario)</Typography>} />
      {props.transient && (
        <>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {n(props, setProp, 't_end', 'Tiempo final')}
            {unitSelect(props, setProp, 'time_unit', ['s', 'min', 'h', 'd'], 's', 'unidad de tiempo')}
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {n(props, setProp, 'time_steps', 'Pasos', 50)}
            {n(props, setProp, 'dt_growth', 'Crecimiento Δt', 1)}
            {n(props, setProp, 'n_output', 'Salidas', '')}
          </Box>
          <Select size="small" fullWidth value={props.scheme || 'bdf2'} onChange={(e) => setProp('scheme', e.target.value)}
            sx={{ color: '#fff' }} inputProps={{ 'aria-label': 'Esquema temporal' }}>
            <MenuItem value="bdf2">BDF2 de paso variable (recomendado)</MenuItem>
            <MenuItem value="cn">Crank–Nicolson</MenuItem>
            <MenuItem value="be">Euler implícito</MenuItem>
          </Select>
          <Typography variant="caption" sx={{ color: '#777' }}>
            El descenso cambia con log t: un crecimiento 1,05–1,1 da pasos cortos al arrancar el pozo y largos al final.
          </Typography>
        </>
      )}
      <ProbeList props={props} setProp={setProp} title="Piezómetros (carga en el tiempo)" />
    </Box>
  );
}

function FaceSet({ props, setProp, def, show }) {
  if (!show) return null;
  return (
    <TextField label="Conjunto de caras (viga de prueba)" size="small" fullWidth value={props.face_set || ''}
      onChange={(e) => setProp('face_set', e.target.value || null)}
      placeholder={`${def} (fixed, tip, y0, y1, z0, z1, @free)`} inputProps={txt} InputLabelProps={lbl} />
  );
}

function CutOff({ props, setProp }) {
  return n(props, setProp, 't_off', 'Activo hasta t (vacío = siempre)', '', {});
}

export function HeadBCFields({ props, setProp, showFaceSet }) {
  return (
    <>
      {n(props, setProp, 'head', 'Carga hidráulica h [m]', '', {})}
      <CutOff props={props} setProp={setProp} />
      <Typography variant="caption" sx={{ color: '#777' }}>
        Lago, río en contacto pleno, mar o contorno lejano. Las caras sin condición son impermeables.
      </Typography>
      <FaceSet props={props} setProp={setProp} def="fixed" show={showFaceSet} />
    </>
  );
}

export const DARCY_LOADS = ['recharge', 'well', 'leakage'];

export function DarcyLoadFields({ lt, props, setProp, showFaceSet }) {
  return (
    <>
      {lt === 'leakage' ? (
        <>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {n(props, setProp, 'conductance', 'Conductancia K′/b′')}
            {unitSelect(props, setProp, 'conductance_unit', ['1/d', '1/s'], '1/d', 'unidad de conductancia')}
          </Box>
          {n(props, setProp, 'head', 'Carga exterior (río / acuífero superior) [m]', '', {})}
        </>
      ) : (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {n(props, setProp, 'magnitude', lt === 'well' ? 'Caudal (+ extracción)' : 'Recarga (+ entra)', 0)}
          {lt === 'well'
            ? unitSelect(props, setProp, 'unit', ['m³/s', 'L/s', 'm³/h', 'm³/d'], 'm³/s', 'unidad de caudal')
            : unitSelect(props, setProp, 'unit', ['mm/d', 'mm/año', 'm/s'], 'mm/d', 'unidad de recarga')}
        </Box>
      )}
      {lt === 'well' && (
        <FormControlLabel
          control={<Switch size="small" checked={!!props.at_point} onChange={(e) => setProp('at_point', e.target.checked)}
            inputProps={{ 'aria-label': 'Pozo puntual' }} />}
          label={<Typography variant="caption" sx={{ color: '#bbb' }}>Pozo puntual (si no: caras del filtro)</Typography>} />
      )}
      {lt === 'well' && props.at_point && (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {n(props, setProp, 'x', 'x [mm]')}
          {n(props, setProp, 'y', 'y [mm]')}
          {n(props, setProp, 'z', 'z [mm]')}
        </Box>
      )}
      <Typography variant="caption" sx={{ color: '#777' }}>
        {lt === 'well' ? 'El caudal se reparte por área en las caras del filtro (con simetría, la fracción que toca).'
          : lt === 'recharge' ? 'Infiltración por la superficie (sin caras: cara superior z1 de la viga de prueba).'
            : 'Flujo C·(h_ext − h) a través del lecho del río o de un acuitardo.'}
      </Typography>
      <CutOff props={props} setProp={setProp} />
      <FaceSet props={props} setProp={setProp} def={lt === 'well' ? 'tip' : 'z1'}
        show={showFaceSet && !(lt === 'well' && props.at_point)} />
    </>
  );
}
