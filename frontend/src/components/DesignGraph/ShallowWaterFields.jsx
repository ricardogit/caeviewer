/**
 * ShallowWaterFields — MATERIAL «Agua (aguas someras 2D)» (model_type = shallow_water, FASE 10.3): Manning n (+ the
 * zone attribute that overrides it), density, Coriolis, eddy viscosity, drying depth, initial level, scheme order,
 * duration and control points (lon/lat). SWBCFields — BC tide / river discharge / open sea / coast on the sides of
 * the study's 2-D domain (drawn in Mapa mode); WindLoadFields — LOAD «Viento». Tracers (FASE 10.4): species list
 * on the material (`species`), inflow concentrations on tide / river / open-sea BCs and the LOAD «Vertido» (outfall:
 * lon/lat, flow, concentrations) — all keyed by species name (`concentrations: {name: c}`).
 * 3-D stratified σ-layer model (FASE 10.4): `vertical_layers` ≥ 2 on the material (closure, T / S initial profile,
 * equation of state, bed roughness); inflow T / S on tide / river BCs, effluent T / S + release level on outfalls.
 */
import React, { useEffect, useMemo } from 'react';
import {
  Box, Button, Chip, FormControlLabel, IconButton, MenuItem, Select, Switch, TextField, Typography,
} from '@mui/material';
import { Add, Delete } from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';
import useGeoMapStore from '../../stores/geoMapStore';
import { SpeciesRow } from './TransportFields';

const txt = { style: { color: '#fff' } };
const lbl = { style: { color: '#888' } };
const toNum = (v) => (v === '' ? null : parseFloat(v));

export const SW_BCS = ['tide', 'river_inflow', 'open_boundary', 'coast'];
const CONSTITUENTS = ['M2', 'S2', 'N2', 'K2', 'K1', 'O1', 'P1', 'Q1', 'M4', 'MS4', 'M6'];
// which side kind a condition goes to when no side is chosen (graph_to_solver_spec SW_DEFAULT_SIDE)
const DEFAULT_SIDE = { tide: 'open', river_inflow: 'river', open_boundary: 'open', coast: 'coast' };
const KIND_LABEL = { open: 'mar abierto', river: 'río', coast: 'costa' };

const num = (props, setProp, k, label, def = '', sx = { flex: 1 }) => (
  <TextField key={k} label={label} size="small" type="number" sx={sx}
    value={props[k] ?? def}
    onChange={(e) => setProp(k, toNum(e.target.value))}
    inputProps={{ ...txt, 'aria-label': label }} InputLabelProps={lbl} />
);

const sel = (props, setProp, k, opts, def, aria, sx = { color: '#fff', minWidth: 80 }) => (
  <Select size="small" value={props[k] ?? def} onChange={(e) => setProp(k, e.target.value)} sx={sx}
    inputProps={{ 'aria-label': aria }}>
    {opts.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
  </Select>
);

/** Sides of the study's 2-D domain: [{id, kind, label}] (edge<i> per drawn side + coast). */
export function useDomainSides() {
  const nodes = useDesignStore((s) => s.graphData.nodes);
  return useMemo(() => {
    const g = nodes.find((n) => n.data?.node_type === 'GEOMETRY' && n.data?.properties?.shape === 'domain_2d');
    if (!g) return null;
    const p = g.data.properties;
    const sides = (p.segments || []).map((k, i) => ({
      id: `edge${i}`, kind: k, label: (p.segment_labels || [])[i] || `Lado ${i + 1} (${KIND_LABEL[k] || k})`,
    }));
    return [...sides, { id: 'coast', kind: 'coast', label: 'Costa (tierra)' }];
  }, [nodes]);
}

/** Species of the study's shallow-water MATERIAL: [{name, unit, …}]. */
export function useSWSpecies() {
  const nodes = useDesignStore((s) => s.graphData.nodes);
  return useMemo(() => {
    const m = nodes.find((n) => n.data?.node_type === 'MATERIAL' && n.data?.properties?.model_type === 'shallow_water');
    return (m?.data?.properties?.species || []).map((s, i) => ({ ...s, name: (s.name || '').trim() || `Especie ${i + 1}` }));
  }, [nodes]);
}

/** The study's shallow-water MATERIAL runs the 3-D stratified model: {layers, T, S} or null. */
export function useSW3D() {
  const nodes = useDesignStore((s) => s.graphData.nodes);
  return useMemo(() => {
    const m = nodes.find((n) => n.data?.node_type === 'MATERIAL' && n.data?.properties?.model_type === 'shallow_water');
    const p = m?.data?.properties || {};
    if (!(p.vertical_layers > 1)) return null;
    return { layers: p.vertical_layers, T: p.T_surface != null, S: p.S_surface != null };
  }, [nodes]);
}

/** Temperature / salinity of the water entering (BC) or discharged (outfall) — 3-D stratified model only. */
function TSInputs({ props, setProp, title }) {
  const m3 = useSW3D();
  if (!m3 || !(m3.T || m3.S)) return null;
  return (
    <>
      <Typography variant="caption" sx={{ color: '#888' }}>{title}</Typography>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {m3.T && num(props, setProp, 'temperature', 'Temperatura [°C]', '')}
        {m3.S && num(props, setProp, 'salinity', 'Salinidad [psu]', '')}
      </Box>
    </>
  );
}

/** MATERIAL: 3-D hydrostatic model in σ layers (stratification by temperature / salinity). */
function Stratified3DFields({ props, setProp }) {
  const on = props.vertical_layers > 1;
  return (
    <>
      <FormControlLabel sx={{ color: '#ccc' }}
        control={<Switch size="small" checked={on} inputProps={{ 'aria-label': 'modelo 3D estratificado' }}
          onChange={(e) => setProp('vertical_layers', e.target.checked ? 10 : null)} />}
        label="3D estratificado (capas σ)" />
      {on && (
        <>
          <Typography variant="caption" sx={{ color: '#80deea' }}>
            Hidrostático en capas σ: perfiles verticales de corriente, densidad ρ(T, S), mezcla vertical. Cada capa
            multiplica el coste; el paso de tiempo lo sigue fijando la onda de gravedad.
          </Typography>
          <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
            {num(props, setProp, 'vertical_layers', 'Capas', 10)}
            {sel(props, setProp, 'closure', [['k_epsilon', 'Mezcla k-ε'], ['constant', 'ν, κ constantes']], 'k_epsilon',
              'cierre vertical', { color: '#fff', flex: 1.5 })}
          </Box>
          {props.closure === 'constant' ? (
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              {num(props, setProp, 'nu_v', 'ν vertical [m²/s]', '')}
              {num(props, setProp, 'kappa_v', 'κ vertical [m²/s]', '')}
            </Box>
          ) : (
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              {num(props, setProp, 'nu_v', 'ν de fondo [m²/s]', 1e-6)}
              {num(props, setProp, 'kappa_v', 'κ de fondo [m²/s]', 1e-7)}
            </Box>
          )}
          <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
            {num(props, setProp, 'bottom_z0_mm', 'Rugosidad z₀ [mm] (vacío = Manning)', '')}
            {sel(props, setProp, 'eos', [['unesco', 'ρ UNESCO'], ['linear', 'ρ lineal']], 'unesco', 'ecuación de estado')}
          </Box>
          <Typography variant="caption" sx={{ color: '#888' }}>
            Estado inicial (vacío = no se modela; solo fondo vacío = uniforme)
          </Typography>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {num(props, setProp, 'T_surface', 'T superficie [°C]', '')}
            {num(props, setProp, 'T_bottom', 'T fondo [°C]', '')}
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {num(props, setProp, 'S_surface', 'S superficie [psu]', '')}
            {num(props, setProp, 'S_bottom', 'S fondo [psu]', '')}
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {num(props, setProp, 'profile_depth', 'Prof. del valor de fondo [m]', 20)}
            {num(props, setProp, 'D_h', 'Difusión horizontal T, S [m²/s]', 0)}
          </Box>
        </>
      )}
    </>
  );
}

/** Concentration per species of the study (`concentrations: {name: c}`). */
function ConcentrationInputs({ props, setProp, title }) {
  const species = useSWSpecies();
  if (!species.length) return null;
  const conc = props.concentrations || {};
  return (
    <>
      <Typography variant="caption" sx={{ color: '#888' }}>{title}</Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
        {species.map((s) => (
          <TextField key={s.name} size="small" type="number" label={`${s.name} [${s.unit || 'mg/L'}]`}
            sx={{ flex: '1 1 45%' }} value={conc[s.name] ?? ''}
            onChange={(e) => setProp('concentrations', { ...conc, [s.name]: toNum(e.target.value) })}
            inputProps={{ ...txt, 'aria-label': `concentración ${s.name}` }} InputLabelProps={lbl} />
        ))}
      </Box>
    </>
  );
}

function useForcings() {
  const datasets = useGeoMapStore((s) => s.datasets);
  const fetchDatasets = useGeoMapStore((s) => s.fetchDatasets);
  useEffect(() => { if (!datasets.length) fetchDatasets(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return datasets.filter((d) => d.kind === 'forcing');
}

function ForcingPick({ props, setProp, columnKeys = [['column', 'Columna']], allowHarmonics = true }) {
  const forcings = useForcings();
  const ds = forcings.find((d) => d.id === props.forcing_dataset);
  const cols = Object.keys(ds?.summary?.columns || {});
  return (
    <>
      <Select size="small" fullWidth displayEmpty value={props.forcing_dataset || ''}
        onChange={(e) => setProp('forcing_dataset', e.target.value || null)} sx={{ color: '#fff' }}
        inputProps={{ 'aria-label': 'forzamiento' }}>
        <MenuItem value="">Valores en el nodo</MenuItem>
        {forcings.filter((d) => allowHarmonics || d.summary?.columns).map((d) => (
          <MenuItem key={d.id} value={d.id}>{d.name}{d.summary?.constituents ? ' (armónicos)' : ''}</MenuItem>
        ))}
      </Select>
      {ds && cols.length > 0 && columnKeys.map(([k, l]) => (
        <Select key={k} size="small" fullWidth value={props[k] || cols[0]} onChange={(e) => setProp(k, e.target.value)}
          sx={{ color: '#fff' }} inputProps={{ 'aria-label': l }}>
          {cols.map((c) => <MenuItem key={c} value={c}>{l}: {c}</MenuItem>)}
        </Select>
      ))}
      {!forcings.length && (
        <Typography variant="caption" sx={{ color: '#777' }}>
          Sin forzamientos: súbalos en el modo Mapa (CSV de serie temporal o constantes armónicas).
        </Typography>
      )}
    </>
  );
}

export default function ShallowWaterFields({ props, setProp }) {
  const probes = props.probes || [];
  const species = props.species || [];
  const setProbe = (i, patch) => setProp('probes', probes.map((p, k) => (k === i ? { ...p, ...patch } : p)));
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Typography variant="caption" sx={{ color: '#80deea' }}>
        Aguas someras 2D sobre el dominio del modo Mapa (necesita batimetría).
      </Typography>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num(props, setProp, 'manning_n', 'Manning n [s/m^⅓]', 0.025)}
        <TextField label="Atributo de zona" size="small" sx={{ flex: 1 }} placeholder="manning"
          value={props.manning_zone_key || ''} onChange={(e) => setProp('manning_zone_key', e.target.value || null)}
          inputProps={{ ...txt, 'aria-label': 'atributo de zona Manning' }} InputLabelProps={lbl} />
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num(props, setProp, 'rho', 'ρ [kg/m³]', 1025)}
        {num(props, setProp, 'h_dry', 'Calado de secado [m]', 0.01)}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num(props, setProp, 'nu_t', 'ν turbulenta [m²/s]', 0)}
        {num(props, setProp, 'eta0', 'Nivel inicial [m]', '')}
      </Box>
      <FormControlLabel sx={{ color: '#ccc' }}
        control={<Switch size="small" checked={props.coriolis !== false} onChange={(e) => setProp('coriolis', e.target.checked)} />}
        label="Coriolis (latitud del dominio)" />
      <Stratified3DFields props={props} setProp={setProp} />
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        {num(props, setProp, 't_end', 'Duración', 24)}
        {sel(props, setProp, 'time_unit', [['h', 'h'], ['d', 'd'], ['min', 'min'], ['s', 's']], 'h', 'unidad de tiempo')}
        {num(props, setProp, 'n_output', 'Salidas', 48)}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        {sel(props, setProp, 'order', [[2, 'Orden 2 (MUSCL)'], [1, 'Orden 1']], 2, 'orden', { color: '#fff', flex: 1 })}
        {num(props, setProp, 'cfl', 'CFL', '')}
      </Box>
      <Typography variant="caption" sx={{ color: '#888' }}>Puntos de control (lon, lat)</Typography>
      {probes.map((p, i) => (
        <Box key={i} sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          <TextField size="small" label="Nombre" sx={{ flex: 1.2 }} value={p.label || ''}
            onChange={(e) => setProbe(i, { label: e.target.value })} inputProps={txt} InputLabelProps={lbl} />
          {['lon', 'lat'].map((k) => (
            <TextField key={k} size="small" type="number" label={k} sx={{ flex: 1 }} value={p[k] ?? ''}
              onChange={(e) => setProbe(i, { [k]: toNum(e.target.value) })}
              inputProps={{ ...txt, 'aria-label': `punto ${i + 1} ${k}`, step: 0.001 }} InputLabelProps={lbl} />
          ))}
          <IconButton size="small" onClick={() => setProp('probes', probes.filter((_, k) => k !== i))}
            aria-label={`quitar punto ${i + 1}`}><Delete fontSize="small" sx={{ color: '#888' }} /></IconButton>
        </Box>
      ))}
      <Button size="small" startIcon={<Add />} sx={{ alignSelf: 'flex-start' }}
        onClick={() => setProp('probes', [...probes, { label: `P${probes.length + 1}`, lon: null, lat: null }])}>
        Punto de control
      </Button>
      <Typography variant="caption" sx={{ color: '#888' }}>
        Sustancias transportadas (promediadas en la vertical): contaminantes, bacterias, salinidad…
      </Typography>
      {species.map((sp, i) => (
        <SpeciesRow key={i} sp={sp} i={i} noPulse canRemove
          onChange={(v) => setProp('species', species.map((x, k) => (k === i ? v : x)))}
          onRemove={() => setProp('species', species.filter((_, k) => k !== i))} />
      ))}
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        <Button size="small" startIcon={<Add />}
          onClick={() => setProp('species', [...species, { name: `Especie ${species.length + 1}`, unit: 'mg/L', D: 1 }])}>
          Especie
        </Button>
        <Button size="small" startIcon={<Add />}
          onClick={() => setProp('species', [...species, { name: 'E. coli', unit: 'UFC/100 mL', D: 1, decay: 24, decay_unit: 'T90_h', threshold: 500 }])}>
          Bacterias (T90)
        </Button>
      </Box>
    </Box>
  );
}

export function SWBCFields({ props, setProp }) {
  const sides = useDomainSides();
  const t = props.bc_type;
  const chosen = props.boundaries || [];
  const toggle = (id) => setProp('boundaries', chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]);
  const cons = props.constituents || [];
  const setCons = (i, patch) => setProp('constituents', cons.map((c, k) => (k === i ? { ...c, ...patch } : c)));
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Typography variant="caption" sx={{ color: '#888' }}>
        Contornos del dominio 2D {chosen.length ? '' : `(ninguno elegido: todos los lados de ${KIND_LABEL[DEFAULT_SIDE[t]]} libres)`}
      </Typography>
      {sides ? (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
          {sides.map((s) => (
            <Chip key={s.id} size="small" label={s.label} onClick={() => toggle(s.id)}
              variant={chosen.includes(s.id) ? 'filled' : 'outlined'}
              color={chosen.includes(s.id) ? 'primary' : 'default'}
              sx={{ color: chosen.includes(s.id) ? undefined : '#bbb' }} />
          ))}
        </Box>
      ) : (
        <Typography variant="caption" sx={{ color: '#ffab91' }}>
          El estudio no tiene un dominio 2D: dibújelo en el modo Mapa y guárdelo en su GEOMETRY.
        </Typography>
      )}
      {t === 'tide' && (
        <>
          <ForcingPick props={props} setProp={setProp} />
          {!props.forcing_dataset && (
            <>
              {cons.map((c, i) => (
                <Box key={i} sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
                  <Select size="small" value={c.name || 'M2'} onChange={(e) => setCons(i, { name: e.target.value })}
                    sx={{ color: '#fff', minWidth: 72 }} inputProps={{ 'aria-label': `constituyente ${i + 1}` }}>
                    {CONSTITUENTS.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
                  </Select>
                  {[['amplitude', 'A [m]'], ['phase', 'g [°]']].map(([k, l]) => (
                    <TextField key={k} size="small" type="number" label={l} sx={{ flex: 1 }} value={c[k] ?? ''}
                      onChange={(e) => setCons(i, { [k]: toNum(e.target.value) })}
                      inputProps={{ ...txt, 'aria-label': `${l} ${i + 1}` }} InputLabelProps={lbl} />
                  ))}
                  <IconButton size="small" onClick={() => setProp('constituents', cons.filter((_, k) => k !== i))}
                    aria-label={`quitar constituyente ${i + 1}`}><Delete fontSize="small" sx={{ color: '#888' }} /></IconButton>
                </Box>
              ))}
              <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
                <Button size="small" startIcon={<Add />}
                  onClick={() => setProp('constituents', [...cons, { name: cons.length ? 'S2' : 'M2', amplitude: 1, phase: 0 }])}>
                  Constituyente
                </Button>
                {num(props, setProp, 'z0', 'Nivel medio Z0 [m]', 0)}
              </Box>
            </>
          )}
          {num(props, setProp, 'ramp_h', 'Rampa inicial [h]', '', {})}
        </>
      )}
      {t === 'river_inflow' && (
        <>
          <ForcingPick props={props} setProp={setProp} allowHarmonics={false} />
          {!props.forcing_dataset && (
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              {num(props, setProp, 'discharge', 'Caudal Q', '')}
              {sel(props, setProp, 'unit', [['m3/s', 'm³/s'], ['L/s', 'L/s'], ['m3/h', 'm³/h']], 'm3/s', 'unidad de caudal')}
            </Box>
          )}
          {num(props, setProp, 'ramp_h', 'Rampa inicial [h]', '', {})}
        </>
      )}
      {t === 'open_boundary' && (
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          {sel(props, setProp, 'mode', [['free', 'Salida libre (transmisiva)'], ['level', 'Nivel fijo']], 'free',
            'tipo de mar abierto', { color: '#fff', flex: 2 })}
          {props.mode === 'level' && num(props, setProp, 'level', 'Nivel [m]', 0)}
        </Box>
      )}
      {t === 'coast' && (
        <Typography variant="caption" sx={{ color: '#777' }}>
          Pared impermeable con deslizamiento (la costa ya lo es por defecto; sirve para cerrar un lado dibujado).
        </Typography>
      )}
      {t !== 'coast' && <TSInputs props={props} setProp={setProp} title="Temperatura / salinidad del agua que entra" />}
      {t !== 'coast' && (
        <ConcentrationInputs props={props} setProp={setProp}
          title={t === 'open_boundary' && props.mode !== 'level'
            ? 'Concentración del agua que entra (vacío = la del interior)'
            : 'Concentración del agua que entra (vacío = 0)'} />
      )}
    </Box>
  );
}

export function OutfallLoadFields({ props, setProp }) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num(props, setProp, 'lon', 'lon', '')}
        {num(props, setProp, 'lat', 'lat', '')}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        {num(props, setProp, 'discharge', 'Caudal Q', 0)}
        {sel(props, setProp, 'unit', [['m3/s', 'm³/s'], ['L/s', 'L/s'], ['m3/h', 'm³/h']], 'm3/s', 'unidad de caudal')}
      </Box>
      {num(props, setProp, 't_off', 'Duración del vertido [h] (vacío = continuo)', '', {})}
      <ConcentrationInputs props={props} setProp={setProp} title="Concentración del efluente" />
      <OutfallRelease props={props} setProp={setProp} />
      <Typography variant="caption" sx={{ color: '#777' }}>
        Emisario, colector o derrame puntual: aporta Q de agua y Q·c de cada sustancia a la celda que contiene el punto.
      </Typography>
    </Box>
  );
}

function OutfallRelease({ props, setProp }) {
  const m3 = useSW3D();
  if (!m3) return null;
  return (
    <>
      <TSInputs props={props} setProp={setProp} title="Temperatura / salinidad del efluente (vacío: T ambiente, S = 0)" />
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
        <Typography variant="caption" sx={{ color: '#888', flex: 1 }}>Descarga en</Typography>
        {sel(props, setProp, 'release', [['bottom', 'el fondo (emisario)'], ['surface', 'superficie'],
          ['column', 'toda la columna']], 'bottom', 'nivel de descarga', { color: '#fff', flex: 2 })}
      </Box>
    </>
  );
}

export function WindLoadFields({ props, setProp }) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <ForcingPick props={props} setProp={setProp} allowHarmonics={false}
        columnKeys={[['u_column', 'u (este)'], ['v_column', 'v (norte)']]} />
      {!props.forcing_dataset && (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {num(props, setProp, 'speed', 'Velocidad a 10 m [m/s]', '')}
          {num(props, setProp, 'direction', 'Procedencia [° desde N]', 0)}
        </Box>
      )}
      <Typography variant="caption" sx={{ color: '#777' }}>
        Tensión τ = ρ_aire C_d |W| W (Wu 1982) sobre todo el dominio; la serie da u, v en m/s.
      </Typography>
    </Box>
  );
}
