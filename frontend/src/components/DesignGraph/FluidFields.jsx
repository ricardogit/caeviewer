/**
 * FluidFields — Newtonian fluid MATERIAL node (model_type = newtonian_fluid): dynamic viscosity μ [Pa·s] and
 * flow model: Stokes (creeping, Re ≪ 1), steady laminar Navier–Stokes (convection, needs ρ > 0) or turbulent RANS
 * k-ε with wall functions (no-slip BCs become wall-function walls). T10 meshes only (Taylor-Hood P2-P1). ρ (above)
 * is used for gravity, inertia and the Reynolds-number check. Navier–Stokes and RANS can be transient (BDF2 / implicit
 * Euler, URANS with sub-iterations per step), with control points and a start-up ramp on the inlet velocity.
 */
import React from 'react';
import {
  Box, Button, FormControlLabel, MenuItem, Select, Switch, TextField, Typography, ToggleButton, ToggleButtonGroup,
} from '@mui/material';
import { ProbeList } from './TransportFields';

const num = (v) => (v === '' ? null : parseFloat(v));

function NumField({ label, k, props, setProp, helper }) {
  return (
    <TextField label={label} size="small" fullWidth type="number" value={props[k] ?? ''} helperText={helper}
      onChange={(e) => setProp(k, num(e.target.value))}
      inputProps={{ style: { color: '#fff' }, 'aria-label': label }}
      InputLabelProps={{ style: { color: '#888' } }} FormHelperTextProps={{ style: { color: '#777' } }} />
  );
}

export function TurbulenceFields({ props, setProp }) {
  return (
    <Box data-testid="turbulence-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Typography variant="caption" sx={{ color: '#888' }}>
        k-ε estándar con funciones de pared (Reichardt): las BC «Empotrado» (sin deslizamiento) son paredes cuyo
        contorno de malla está a la distancia δ de la pared real. Fiable con y⁺ entre ~30 y 300 (el resultado lo indica).
      </Typography>
      <NumField label="Distancia de pared δ [mm]" k="wall_distance_mm" props={props} setProp={setProp}
        helper="Vacío = automática (½ altura del elemento junto a la pared)" />
      <NumField label="Intensidad turbulenta de entrada [%]" k="inlet_intensity" props={props} setProp={setProp}
        helper="Vacío = 5 %" />
      <NumField label="Escala de longitud de entrada [mm]" k="inlet_length_mm" props={props} setProp={setProp}
        helper="Vacío = 0.07 × menor dimensión del dominio" />
    </Box>
  );
}

/** Velocity BC (inlet) of a RANS study: optional turbulence intensity and length scale (else the material's). */
export function InletTurbulenceFields({ props, setProp }) {
  return (
    <Box data-testid="inlet-turbulence-fields" sx={{ display: 'flex', gap: 0.5 }}>
      <NumField label="Intensidad turb. [%]" k="turbulence_intensity" props={props} setProp={setProp}
        helper="Solo RANS; vacío = la del material" />
      <NumField label="Escala turb. [mm]" k="turbulence_length_mm" props={props} setProp={setProp}
        helper="Vacío = la del material" />
    </Box>
  );
}

/** Velocity BC of a transient study: linear start-up ramp 0 → 1 over t_ramp (study time unit; laminar only). */
export function InletRampField({ props, setProp }) {
  return (
    <NumField label="Rampa de arranque" k="t_ramp" props={props} setProp={setProp}
      helper="Estudio transitorio laminar: la velocidad sube de 0 al valor en este tiempo (unidad del estudio)" />
  );
}

/** Transient settings of a Navier–Stokes / RANS fluid (``transient``, t_end + time_unit, steps, scheme, probes). */
export function FluidTransientFields({ props, setProp }) {
  const rans = props.flow_model === 'rans_k_epsilon';
  return (
    <Box data-testid="fluid-transient-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <FormControlLabel
        control={<Switch size="small" checked={!!props.transient} onChange={(e) => setProp('transient', e.target.checked)}
          inputProps={{ 'aria-label': 'Transitorio' }} />}
        label={<Typography variant="caption" sx={{ color: '#bbb' }}>
          {rans ? 'Transitorio (URANS)' : 'Transitorio'} (si no: estado estacionario)</Typography>} />
      {props.transient && (
        <>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <NumField label="Tiempo final" k="t_end" props={props} setProp={setProp} />
            <Select size="small" value={props.time_unit || 's'} onChange={(e) => setProp('time_unit', e.target.value)}
              sx={{ color: '#fff', minWidth: 64 }} inputProps={{ 'aria-label': 'unidad de tiempo' }}>
              {['s', 'min', 'h'].map((u) => <MenuItem key={u} value={u}>{u}</MenuItem>)}
            </Select>
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <NumField label="Pasos" k="time_steps" props={props} setProp={setProp} helper="Vacío = 50" />
            <NumField label="Salidas" k="n_output" props={props} setProp={setProp} helper="Instantes guardados" />
          </Box>
          <Select size="small" fullWidth value={props.scheme || 'bdf2'} onChange={(e) => setProp('scheme', e.target.value)}
            sx={{ color: '#fff' }} inputProps={{ 'aria-label': 'Esquema temporal' }}>
            <MenuItem value="bdf2">BDF2 (2.º orden, recomendado)</MenuItem>
            <MenuItem value="be">Euler implícito (1.er orden, amortigua)</MenuItem>
          </Select>
          {rans && (
            <Select size="small" fullWidth value={props.urans_initial || 'rest'}
              onChange={(e) => setProp('urans_initial', e.target.value)}
              sx={{ color: '#fff' }} inputProps={{ 'aria-label': 'Estado inicial URANS' }}>
              <MenuItem value="rest">Arranque desde el reposo</MenuItem>
              <MenuItem value="steady">Desde el cálculo estacionario (si no converge del todo)</MenuItem>
            </Select>
          )}
          {rans && (
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <NumField label="Sub-iteraciones" k="inner_iterations" props={props} setProp={setProp}
                helper="Por paso; vacío = 8" />
              <NumField label="Tol. estacionario" k="steady_tol" props={props} setProp={setProp}
                helper="Para al alcanzar el estado estacionario (p. ej. 1e-5)" />
            </Box>
          )}
          {rans && (
            <NumField label="Promediar desde" k="average_from" props={props} setProp={setProp}
              helper="Campos medios en el tiempo a partir de este instante (flujo que no se estabiliza)" />
          )}
          <Typography variant="caption" sx={{ color: '#777' }}>
            {rans ? 'Paso de tiempo global; con «Tol. estacionario» la marcha en el tiempo para al estabilizarse '
              + '(útil cuando el cálculo estacionario no converge, p. ej. tras un escalón).'
              : 'El resultado guarda la velocidad y la presión en las salidas, las fuerzas sobre las paredes en el '
              + 'tiempo y las curvas de los puntos de control. Courant |v|Δt/h ≲ 1 para seguir bien los vórtices.'}
          </Typography>
          <ProbeList props={props} setProp={setProp} title="Puntos de control (velocidad y presión en el tiempo)" />
        </>
      )}
    </Box>
  );
}

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
        Fluido newtoniano{props.transient && props.flow_model !== 'stokes' ? ' transitorio' : ' estacionario'} · requiere
        malla T10
      </Typography>
      <ToggleButtonGroup size="small" exclusive value={props.flow_model || 'stokes'} aria-label="Modelo de flujo"
        onChange={(_, v) => { if (v) setProp('flow_model', v); }}>
        <ToggleButton value="stokes" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>Stokes (Re ≪ 1)</ToggleButton>
        <ToggleButton value="navier_stokes" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>Navier-Stokes laminar</ToggleButton>
        <ToggleButton value="rans_k_epsilon" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>RANS k-ε</ToggleButton>
      </ToggleButtonGroup>
      <Typography variant="caption" sx={{ color: '#888' }}>
        {{
          navier_stokes: 'Incluye la inercia ρ(v·∇)v (Picard + Newton). Válido para flujo laminar estacionario (Re hasta ~10³).',
          rans_k_epsilon: 'Flujo turbulento medio (Reynolds alto): Navier-Stokes promediado + modelo k-ε.',
        }[props.flow_model] || 'Flujo lento: desprecia la inercia. Si el resultado avisa Re > 1, cambie a Navier-Stokes.'}
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
      {props.flow_model === 'rans_k_epsilon' && <TurbulenceFields props={props} setProp={setProp} />}
      {['navier_stokes', 'rans_k_epsilon'].includes(props.flow_model) && (
        <FluidTransientFields props={props} setProp={setProp} />
      )}
      {props.transient && props.flow_model === 'navier_stokes' && props.stabilization === 'supg' && (
        <Typography variant="caption" sx={{ color: '#ef9a9a' }}>
          SUPG no está disponible en transitorio laminar: desactívela.
        </Typography>
      )}
      {['navier_stokes', 'rans_k_epsilon'].includes(props.flow_model) && !(props.rho > 0) && (
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
