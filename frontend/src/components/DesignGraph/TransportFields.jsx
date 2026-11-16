/**
 * TransportFields — MATERIAL «Transporte de contaminantes» (model_type = scalar_transport, FASE 10.1 + 10.2):
 * dissolved species (D, first-order decay or T90, unit, threshold, initial value or Gaussian pulse), reaction
 * model (none | Streeter–Phelps BOD → oxygen deficit), velocity (uniform or the field of a finished fluid run on
 * the same mesh), SUPG, steady or transient (BDF2 / Crank–Nicolson / implicit Euler) and control points.
 * Porous medium (FASE 10.6): porosity, dispersivities α_L / α_T and per-species retardation R; the velocity may be
 * the pore velocity of a finished Darcy run (its porosity is used when left empty).
 * ConcentrationBCFields — BC «Concentración impuesta»; SpeciesLoadFields — species loads (flux, exchange,
 * volumetric source, point discharge). Both pick the species from the study's transport MATERIAL.
 */
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  Box, Button, FormControlLabel, IconButton, MenuItem, Select, Switch, TextField, ToggleButton,
  ToggleButtonGroup, Typography,
} from '@mui/material';
import { Add, Delete } from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';

const txt = { style: { color: '#fff' } };
const lbl = { style: { color: '#888' } };
const toNum = (v) => (v === '' ? null : parseFloat(v));

export const DEFAULT_SPECIES = { name: 'Contaminante', D: 1e-6, unit: 'mg/L' };
export const SP_SPECIES = [
  { name: 'DBO', D: 1e-6, unit: 'mg/L' },
  { name: 'Déficit de OD', D: 1e-6, unit: 'mg/L' },
];
// typical values (not site data): diffusion coefficients and bacterial die-off in sea water
export const SPECIES_PRESETS = [
  ['Trazador conservativo', { name: 'Trazador', D: 1e-6, decay: null, unit: 'mg/L' }],
  ['E. coli (mar, T90 ≈ 2 h)', { name: 'E. coli', D: 1e-6, decay: 2, decay_unit: 'T90_h', unit: 'UFC/100mL' }],
  ['Sal disuelta (molecular)', { name: 'Sal', D: 1.5e-9, decay: null, unit: 'g/L' }],
];

const n = (props, setProp, k, label, def = '', sx = { flex: 1 }) => (
  <TextField key={k} label={label} size="small" type="number" sx={sx}
    value={props[k] ?? def}
    onChange={(e) => setProp(k, toNum(e.target.value))}
    inputProps={{ ...txt, 'aria-label': label }} InputLabelProps={lbl} />
);

/** Species of the study's transport MATERIAL (names for the BC / LOAD selectors). */
export function useTransportSpecies() {
  const nodes = useDesignStore((s) => s.graphData?.nodes);
  const mat = (nodes || []).find((nd) => nd.data?.node_type === 'MATERIAL'
    && nd.data?.properties?.model_type === 'scalar_transport');
  return (mat?.data?.properties?.species || [DEFAULT_SPECIES]).map((s, i) => s.name || `Especie ${i + 1}`);
}

/** One species: name, unit, D, threshold, decay; initial value c0 or (3-D only) a Gaussian pulse. */
export function SpeciesRow({ sp, i, onChange, onRemove, canRemove, porous, noPulse = false }) {
  const set = (k, v) => onChange({ ...sp, [k]: v });
  const [pulse, setPulse] = useState(sp.pulse_sigma_mm != null);
  return (
    <Box data-testid={`species-${i}`} sx={{ border: '1px solid #2a3a2a', borderRadius: 1, p: 0.75,
      display: 'flex', flexDirection: 'column', gap: 0.75 }}>
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        <TextField label="Especie" size="small" sx={{ flex: 2 }} value={sp.name ?? ''}
          onChange={(e) => set('name', e.target.value)} inputProps={{ ...txt, 'aria-label': `nombre especie ${i + 1}` }}
          InputLabelProps={lbl} />
        <TextField label="Unidad" size="small" sx={{ flex: 1 }} value={sp.unit ?? 'mg/L'}
          onChange={(e) => set('unit', e.target.value)} inputProps={txt} InputLabelProps={lbl} />
        {canRemove && (
          <IconButton size="small" onClick={onRemove} aria-label={`quitar especie ${i + 1}`} sx={{ color: '#e57373' }}>
            <Delete fontSize="small" />
          </IconButton>
        )}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {n(sp, set, 'D', 'Difusividad D [m²/s]')}
        {n(sp, set, 'threshold', 'Umbral')}
        {porous && n(sp, set, 'retardation', 'Retardo R', 1)}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {n(sp, set, 'decay', sp.decay_unit === 'T90_h' ? 'T90 [h]' : 'Decaimiento λ')}
        <Select size="small" value={sp.decay_unit || '1/s'} onChange={(e) => set('decay_unit', e.target.value)}
          sx={{ color: '#fff', minWidth: 84 }} inputProps={{ 'aria-label': `unidad decaimiento ${i + 1}` }}>
          {[['1/s', '1/s'], ['1/h', '1/h'], ['1/d', '1/d'], ['T90_h', 'T90 h']].map(([v, l]) => (
            <MenuItem key={v} value={v}>{l}</MenuItem>))}
        </Select>
      </Box>
      {!noPulse && <FormControlLabel
        control={<Switch size="small" checked={pulse} onChange={(e) => {
          setPulse(e.target.checked);
          onChange(e.target.checked ? { ...sp, pulse_sigma_mm: sp.pulse_sigma_mm ?? 10 }
            : { ...sp, pulse_sigma_mm: null, pulse_center_mm: null, pulse_peak: null });
        }} />}
        label={<Typography variant="caption" sx={{ color: '#bbb' }}>Condición inicial: pulso gaussiano</Typography>} />}
      {pulse && !noPulse ? (
        <>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {[0, 1, 2].map((k) => (
              <TextField key={k} label={`${'xyz'[k]}₀ [mm]`} size="small" type="number" sx={{ flex: 1 }}
                value={(sp.pulse_center_mm || [0, 0, 0])[k] ?? 0}
                onChange={(e) => {
                  const c = [...(sp.pulse_center_mm || [0, 0, 0])];
                  c[k] = toNum(e.target.value) ?? 0;
                  set('pulse_center_mm', c);
                }} inputProps={txt} InputLabelProps={lbl} />
            ))}
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {n(sp, set, 'pulse_sigma_mm', 'σ [mm]')}
            {n(sp, set, 'pulse_peak', 'Pico', 1)}
          </Box>
        </>
      ) : n(sp, set, 'c0', 'Concentración inicial', 0, {})}
    </Box>
  );
}

const FLOW_PHYSICS = ['fluid', 'darcy'];

function FluidRunPicker({ value, onChange }) {
  const [runs, setRuns] = useState([]);
  useEffect(() => {
    let alive = true;
    axios.get('/api/design/solver/runs', { params: { limit: 200 } })
      .then((r) => {
        if (alive) {
          setRuns((r.data.runs || []).filter((x) => x.status === 'done'
            && (x.physics || []).some((ph) => FLOW_PHYSICS.includes(ph))));
        }
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  return (
    <>
      <Select size="small" fullWidth displayEmpty value={runs.some((r) => r.run_id === value) ? value : ''}
        onChange={(e) => onChange(e.target.value)} sx={{ color: '#fff' }}
        inputProps={{ 'aria-label': 'Run de fluido' }}>
        <MenuItem value=""><em>{runs.length ? 'Elija un run de fluido o de Darcy…' : 'No hay runs de fluido ni de Darcy terminados'}</em></MenuItem>
        {runs.map((r) => (
          <MenuItem key={r.run_id} value={r.run_id}>
            {`${(r.physics || []).includes('darcy') ? 'Darcy' : 'Fluido'} · ${(r.created_at || '').slice(0, 16).replace('T', ' ')} · ${r.n_nodes ?? '?'} nodos · ${r.run_id.slice(0, 8)}`}
          </MenuItem>
        ))}
      </Select>
      <TextField label="o ID del run" size="small" fullWidth value={value || ''}
        onChange={(e) => onChange(e.target.value || null)} inputProps={txt} InputLabelProps={lbl} />
      <Typography variant="caption" sx={{ color: '#777' }}>
        La malla debe ser la misma (misma geometría, tamaño y orden de malla que el estudio de flujo). De un run de
        Darcy se toma la velocidad de poro q/n_e.
      </Typography>
    </>
  );
}

export default function TransportFields({ props, setProp }) {
  const species = props.species || [DEFAULT_SPECIES];
  const sp = props.reaction_model === 'streeter_phelps';
  const setSpecies = (list) => setProp('species', list);
  const src = props.velocity_source || 'uniform';
  return (
    <Box data-testid="transport-fields" sx={{ display: 'flex', flexDirection: 'column', gap: 1,
      border: '1px solid #1f4a2a', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#a5d6a7' }}>
        Advección–difusión–reacción de especies disueltas · c en la unidad de cada especie, D en m²/s
      </Typography>

      <Typography variant="caption" sx={{ color: '#ccc' }}>Reacción</Typography>
      <ToggleButtonGroup size="small" exclusive value={props.reaction_model || 'none'} aria-label="Modelo de reacción"
        onChange={(_, v) => {
          if (!v) return;
          setProp('reaction_model', v);
          if (v === 'streeter_phelps' && species.length !== 2) setSpecies(SP_SPECIES);
        }}>
        <ToggleButton value="none" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>Decaimiento λ</ToggleButton>
        <ToggleButton value="streeter_phelps" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>Streeter–Phelps</ToggleButton>
      </ToggleButtonGroup>
      {sp && (
        <>
          <Typography variant="caption" sx={{ color: '#888' }}>
            Especie 1 = DBO (se degrada con kd), especie 2 = déficit de oxígeno (lo genera la DBO, lo reduce la
            reaireación ka). El resultado incluye el oxígeno disuelto OD = OD_sat − déficit.
          </Typography>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {n(props, setProp, 'kd', 'kd')}
            {n(props, setProp, 'ka', 'ka')}
            <Select size="small" value={props.rate_unit || '1/d'} onChange={(e) => setProp('rate_unit', e.target.value)}
              sx={{ color: '#fff', minWidth: 64 }} inputProps={{ 'aria-label': 'unidad de tasa' }}>
              {['1/s', '1/h', '1/d'].map((u) => <MenuItem key={u} value={u}>{u}</MenuItem>)}
            </Select>
          </Box>
          {n(props, setProp, 'do_sat', 'OD de saturación [mg/L]', '', {})}
          {props.kd > 0 && props.ka > 0 && props.ka <= props.kd && (
            <Typography variant="caption" sx={{ color: '#ffcc80' }}>
              ka ≤ kd: el déficit crece sin el mínimo de OD típico (río muy cargado o poco reaireado).
            </Typography>
          )}
        </>
      )}

      <Typography variant="caption" sx={{ color: '#ccc' }}>Especies</Typography>
      {species.map((s, i) => (
        <SpeciesRow key={i} sp={s} i={i} canRemove={!sp && species.length > 1} porous={!!props.porous}
          onChange={(v) => setSpecies(species.map((x, j) => (j === i ? v : x)))}
          onRemove={() => setSpecies(species.filter((_, j) => j !== i))} />
      ))}
      {!sp && (
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          <Button size="small" startIcon={<Add />} onClick={() => setSpecies([...species, { ...DEFAULT_SPECIES, name: `Especie ${species.length + 1}` }])}>
            Especie
          </Button>
          {SPECIES_PRESETS.map(([name, vals]) => (
            <Button key={name} size="small" variant="outlined" onClick={() => setSpecies([...species.slice(0, -1), { ...species[species.length - 1], ...vals }])}>
              {name}
            </Button>
          ))}
        </Box>
      )}

      <Typography variant="caption" sx={{ color: '#ccc' }}>Velocidad del agua</Typography>
      <ToggleButtonGroup size="small" exclusive value={src} aria-label="Origen de la velocidad"
        onChange={(_, v) => { if (v) setProp('velocity_source', v); }}>
        <ToggleButton value="uniform" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>Uniforme</ToggleButton>
        <ToggleButton value="run" sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>De un run (fluido / Darcy)</ToggleButton>
      </ToggleButtonGroup>
      {src === 'uniform' ? (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {n(props, setProp, 'vx', 'vx [m/s]', 0)}
          {n(props, setProp, 'vy', 'vy [m/s]', 0)}
          {n(props, setProp, 'vz', 'vz [m/s]', 0)}
        </Box>
      ) : (
        <FluidRunPicker value={props.velocity_run_id} onChange={(v) => setProp('velocity_run_id', v)} />
      )}
      <FormControlLabel
        control={<Switch size="small" checked={!!props.porous} onChange={(e) => setProp('porous', e.target.checked)}
          inputProps={{ 'aria-label': 'Medio poroso' }} />}
        label={<Typography variant="caption" sx={{ color: '#bbb' }}>Medio poroso (acuífero)</Typography>} />
      {props.porous && (
        <>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {n(props, setProp, 'porosity', 'Porosidad n_e')}
            {n(props, setProp, 'alpha_L', 'α_L [m]')}
            {n(props, setProp, 'alpha_T', 'α_T [m]')}
          </Box>
          <Typography variant="caption" sx={{ color: '#777' }}>
            Dispersión 𝔻 = (D + α_T|v|) I + (α_L − α_T) v vᵀ/|v| con v = velocidad de poro; α_T ≈ α_L/10. Porosidad vacía
            = la del run de Darcy. Masas totales (disuelta + adsorbida, R = 1 + ρ_b K_d / n_e).
          </Typography>
        </>
      )}
      <FormControlLabel
        control={<Switch size="small" checked={props.stabilization !== 'none'}
          onChange={(e) => setProp('stabilization', e.target.checked ? null : 'none')}
          inputProps={{ 'aria-label': 'Estabilización SUPG' }} />}
        label={<Typography variant="caption" sx={{ color: '#bbb' }}>Estabilización SUPG</Typography>} />
      <Typography variant="caption" sx={{ color: '#777' }}>
        Necesaria cuando la advección domina (Péclet de elemento |v|h/2D &gt; 1): sin ella la concentración oscila.
      </Typography>

      <FormControlLabel
        control={<Switch size="small" checked={!!props.transient} onChange={(e) => setProp('transient', e.target.checked)}
          inputProps={{ 'aria-label': 'Transitorio' }} />}
        label={<Typography variant="caption" sx={{ color: '#bbb' }}>Transitorio (si no: estado estacionario)</Typography>} />
      {props.transient && (
        <>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {n(props, setProp, 't_end', 'Tiempo final')}
            <Select size="small" value={props.time_unit || 's'} onChange={(e) => setProp('time_unit', e.target.value)}
              sx={{ color: '#fff', minWidth: 64 }} inputProps={{ 'aria-label': 'unidad de tiempo' }}>
              {['s', 'min', 'h', 'd'].map((u) => <MenuItem key={u} value={u}>{u}</MenuItem>)}
            </Select>
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {n(props, setProp, 'time_steps', 'Pasos', 50)}
            {n(props, setProp, 'n_output', 'Salidas', '')}
          </Box>
          <Select size="small" fullWidth value={props.scheme || 'bdf2'} onChange={(e) => setProp('scheme', e.target.value)}
            sx={{ color: '#fff' }} inputProps={{ 'aria-label': 'Esquema temporal' }}>
            <MenuItem value="bdf2">BDF2 (2.º orden, recomendado)</MenuItem>
            <MenuItem value="cn">Crank–Nicolson (2.º orden; oscila con saltos bruscos)</MenuItem>
            <MenuItem value="be">Euler implícito (1.er orden, muy robusto)</MenuItem>
          </Select>
          <Typography variant="caption" sx={{ color: '#777' }}>
            Las series de las condiciones (corte de un vertido) usan esta misma unidad de tiempo.
          </Typography>
        </>
      )}

      <ProbeList props={props} setProp={setProp} title="Puntos de control (curvas de llegada)" />
    </Box>
  );
}

/** Control points [{label, x, y, z mm}] in ``props.probes`` (time curves in the results summary). */
export function ProbeList({ props, setProp, title }) {
  const probes = props.probes || [];
  return (
    <>
      <Typography variant="caption" sx={{ color: '#ccc' }}>{title}</Typography>
      {probes.map((p, i) => (
        <Box key={i} sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          <TextField size="small" sx={{ flex: 1.3 }} label="Nombre" value={p.label ?? ''}
            onChange={(e) => setProp('probes', probes.map((q, j) => (j === i ? { ...q, label: e.target.value } : q)))}
            inputProps={txt} InputLabelProps={lbl} />
          {['x', 'y', 'z'].map((k) => (
            <TextField key={k} size="small" type="number" sx={{ flex: 1 }} label={`${k} mm`} value={p[k] ?? ''}
              onChange={(e) => setProp('probes', probes.map((q, j) => (j === i ? { ...q, [k]: toNum(e.target.value) } : q)))}
              inputProps={txt} InputLabelProps={lbl} />
          ))}
          <IconButton size="small" onClick={() => setProp('probes', probes.filter((_, j) => j !== i))}
            aria-label={`quitar punto ${i + 1}`} sx={{ color: '#e57373' }}>
            <Delete fontSize="small" />
          </IconButton>
        </Box>
      ))}
      <Button size="small" startIcon={<Add />} sx={{ alignSelf: 'flex-start' }}
        onClick={() => setProp('probes', [...probes, { label: `P${probes.length + 1}`, x: 0, y: 0, z: 0 }])}>
        Punto
      </Button>
    </>
  );
}

function SpeciesSelect({ props, setProp }) {
  const names = useTransportSpecies();
  if (names.length < 2) return null;
  return (
    <Select size="small" fullWidth value={props.species ?? 0} onChange={(e) => setProp('species', e.target.value)}
      sx={{ color: '#fff' }} inputProps={{ 'aria-label': 'Especie' }}>
      {names.map((nm, i) => <MenuItem key={i} value={i}>{nm}</MenuItem>)}
    </Select>
  );
}

function CutOff({ props, setProp }) {
  return (
    <>
      {n(props, setProp, 't_off', 'Activo hasta t (vacío = siempre)', '', {})}
      <Typography variant="caption" sx={{ color: '#777' }}>En la unidad de tiempo del material (transitorio).</Typography>
    </>
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

export function ConcentrationBCFields({ props, setProp, showFaceSet }) {
  return (
    <>
      <SpeciesSelect props={props} setProp={setProp} />
      {n(props, setProp, 'concentration', 'Concentración impuesta', '', {})}
      <CutOff props={props} setProp={setProp} />
      <Typography variant="caption" sx={{ color: '#777' }}>
        Entrada de agua con concentración conocida. Las caras sin condición son salidas (∂c/∂n = 0).
      </Typography>
      <FaceSet props={props} setProp={setProp} def="fixed" show={showFaceSet} />
    </>
  );
}

export const SPECIES_LOADS = ['species_flux', 'exchange', 'species_source', 'point_source'];

export function SpeciesLoadFields({ lt, props, setProp, showFaceSet }) {
  return (
    <>
      <SpeciesSelect props={props} setProp={setProp} />
      {lt === 'exchange' ? (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {n(props, setProp, 'k', 'k [m/s]')}
          {n(props, setProp, 'c_ext', 'c exterior', 0)}
        </Box>
      ) : n(props, setProp, 'magnitude',
        lt === 'species_flux' ? 'Flujo [c·m/s] (+ entra)' : lt === 'species_source' ? 'Fuente [c/s]' : 'Caudal másico [c·m³/s]',
        0, {})}
      {lt === 'point_source' && (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {n(props, setProp, 'x', 'x [mm]')}
          {n(props, setProp, 'y', 'y [mm]')}
          {n(props, setProp, 'z', 'z [mm]')}
        </Box>
      )}
      <Typography variant="caption" sx={{ color: '#777' }}>
        {lt === 'point_source' ? 'Vertido continuo en un punto (con c en mg/L el caudal es g/s).'
          : lt === 'species_source' ? 'Uniforme en todo el volumen.'
            : lt === 'exchange' ? 'Flujo k·(c_ext − c) con la atmósfera o el fondo. Sin caras: resto de la superficie.'
              : 'Sin caras seleccionadas (viga de prueba): cara del extremo.'}
      </Typography>
      <CutOff props={props} setProp={setProp} />
      <FaceSet props={props} setProp={setProp} def={lt === 'exchange' ? '@free' : 'tip'}
        show={showFaceSet && ['species_flux', 'exchange'].includes(lt)} />
    </>
  );
}
