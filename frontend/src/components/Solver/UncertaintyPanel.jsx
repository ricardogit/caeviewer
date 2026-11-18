/**
 * UncertaintyPanel — FASE 6: Monte Carlo propagation of material and load uncertainty to the
 * results (through the study's ROM when one covers the random variables, else full solves),
 * probability of failure against the yield strength, sensitivities and 3D confidence bands.
 */
import React, { useEffect, useState } from 'react';
import {
  Box, Typography, Checkbox, TextField, Button, LinearProgress, Alert, Chip, Select, MenuItem, FormControl,
  InputLabel, Table, TableBody, TableRow, TableCell,
} from '@mui/material';
import { Casino, ViewInAr } from '@mui/icons-material';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid, LineChart, Line,
} from 'recharts';
import useUncertaintyStore from '../../stores/uncertaintyStore';
import UncertaintyBand from './UncertaintyBand';

const label = { color: '#bbb', fontSize: 12 };
const tf = { inputProps: { style: { color: '#fff', fontSize: 12 } }, InputLabelProps: { style: { color: '#888' } } };
const VAR_LABEL = { E: 'E', nu: 'ν', rho: 'ρ', yield: 'σy' };
const num = (v, d = 3) => (v == null ? '—' : Number(v).toPrecision(d));

function Histogram({ stats, yieldMPa, scale, unit }) {
  if (!stats?.histogram) return null;
  const { counts, edges } = stats.histogram;
  const data = counts.map((c, i) => ({ x: ((edges[i] + edges[i + 1]) / 2) * scale, c }));
  return (
    <ResponsiveContainer width="100%" height={140}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 14, left: 0 }} barCategoryGap={0}>
        <CartesianGrid stroke="#333" vertical={false} />
        <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']} tick={{ fill: '#999', fontSize: 10 }}
          tickFormatter={(v) => Number(v).toPrecision(3)}
          label={{ value: unit, position: 'insideBottom', offset: -6, fill: '#999', fontSize: 10 }} />
        <YAxis tick={{ fill: '#999', fontSize: 10 }} width={32} />
        <Tooltip contentStyle={{ background: '#222', border: '1px solid #444', fontSize: 11 }}
          labelFormatter={(v) => `${Number(v).toPrecision(4)} ${unit}`} formatter={(v) => [v, 'muestras']} />
        <Bar dataKey="c" fill="#4fc3f7" isAnimationActive={false} />
        <ReferenceLine x={stats.ci_high * scale} stroke="#ffb74d" strokeDasharray="4 3" />
        {yieldMPa && <ReferenceLine x={yieldMPa} stroke="#ef5350" label={{ value: 'σy', fill: '#ef5350', fontSize: 10 }} />}
      </BarChart>
    </ResponsiveContainer>
  );
}

function Results({ result, onBand }) {
  const s = result?.summary || {};
  if (!s.max_von_mises) return null;
  const vm = s.max_von_mises;
  const u = s.max_displacement;
  const rel = s.reliability;
  const c = Math.round((s.confidence || 0.95) * 100);
  const sens = s.sensitivity?.max_von_mises || {};
  const sensU = s.sensitivity?.max_displacement || {};
  const conv = s.convergence;
  const yieldMPa = rel ? (s.random_variables?.yield?.mean || null) / 1e6 : null;
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Table size="small" sx={{ '& td': { color: '#ccc', borderColor: '#333', fontSize: 11, py: 0.4, px: 0.5 } }}>
        <TableBody>
          <TableRow><TableCell>σvM máx.</TableCell>
            <TableCell><b>{num(vm.mean / 1e6, 4)} ± {num(vm.std / 1e6, 2)} MPa</b> (CV {(100 * vm.cv).toFixed(1)} %)</TableCell></TableRow>
          <TableRow><TableCell>IC {c} %</TableCell><TableCell>[{num(vm.ci_low / 1e6, 4)}, {num(vm.ci_high / 1e6, 4)}] MPa</TableCell></TableRow>
          <TableRow><TableCell>|u| máx.</TableCell>
            <TableCell><b>{num(u.mean * 1e3, 4)} ± {num(u.std * 1e3, 2)} mm</b> · IC [{num(u.ci_low * 1e3, 3)}, {num(u.ci_high * 1e3, 3)}]</TableCell></TableRow>
          {rel && (
            <>
              <TableRow><TableCell>P(fallo)</TableCell>
                <TableCell>
                  <b style={{ color: rel.p_failure > 1e-3 ? '#ef5350' : '#81c784' }}>{rel.p_failure.toExponential(2)}</b>
                  {' '}(IC {c} %: {rel.p_failure_ci[0].toExponential(1)} – {rel.p_failure_ci[1].toExponential(1)}) · {rel.n_failures}/{s.n_samples}
                </TableCell></TableRow>
              <TableRow><TableCell>Índice β</TableCell>
                <TableCell>{num(rel.beta_cornell, 3)} (Cornell){rel.beta_from_pf != null && ` · ${num(rel.beta_from_pf, 3)} (de Pf)`}</TableCell></TableRow>
              <TableRow><TableCell>Factor de seguridad</TableCell>
                <TableCell>medio {num(rel.safety_factor_mean, 3)} · percentil 5 % {num(rel.safety_factor_p05, 3)}</TableCell></TableRow>
            </>
          )}
        </TableBody>
      </Table>
      {rel?.note && <Typography variant="caption" sx={{ color: '#999' }}>{rel.note}</Typography>}
      {s.out_of_range > 0 && (
        <Alert severity="warning" sx={{ fontSize: 11, py: 0 }}>
          {s.out_of_range} muestras fuera del rango entrenado del ROM ({(100 * s.out_of_range / s.n_samples).toFixed(1)} %).
        </Alert>
      )}
      <Typography sx={label}>Distribución de σvM máx. (línea naranja: IC sup.; roja: σy medio)</Typography>
      <Histogram stats={vm} yieldMPa={yieldMPa} scale={1e-6} unit="MPa" />
      <Typography sx={label}>Sensibilidad (Spearman; barra = fracción de varianza explicada)</Typography>
      {Object.entries(sens).map(([k, v]) => (
        <Box key={k} sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: 11 }}>
          <Box sx={{ width: 50, color: '#bbb' }}>{VAR_LABEL[k] || k}</Box>
          <Box sx={{ flex: 1, bgcolor: '#222', height: 8, borderRadius: 1 }}>
            <Box sx={{ width: `${100 * v.share}%`, bgcolor: v.spearman >= 0 ? '#ef9a9a' : '#90caf9', height: 8, borderRadius: 1 }} />
          </Box>
          <Box sx={{ width: 120, color: '#999' }}>σ {v.spearman.toFixed(2)} · u {(sensU[k]?.spearman ?? 0).toFixed(2)}</Box>
        </Box>
      ))}
      {conv && (
        <>
          <Typography sx={label}>Convergencia de la media de σvM máx. [MPa]</Typography>
          <ResponsiveContainer width="100%" height={100}>
            <LineChart data={conv.n.map((n, i) => ({ n, m: conv.mean[i] / 1e6, hi: (conv.mean[i] + 2 * conv.sem[i]) / 1e6, lo: (conv.mean[i] - 2 * conv.sem[i]) / 1e6 }))}
              margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
              <XAxis dataKey="n" type="number" scale="log" domain={['dataMin', 'dataMax']} tick={{ fill: '#999', fontSize: 10 }} />
              <YAxis domain={['auto', 'auto']} tick={{ fill: '#999', fontSize: 10 }} width={40} tickFormatter={(v) => v.toPrecision(3)} />
              <Line dataKey="m" stroke="#4fc3f7" dot={false} isAnimationActive={false} />
              <Line dataKey="hi" stroke="#555" dot={false} strokeDasharray="3 3" isAnimationActive={false} />
              <Line dataKey="lo" stroke="#555" dot={false} strokeDasharray="3 3" isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </>
      )}
      <Typography variant="caption" sx={{ color: '#777' }}>
        {s.method === 'rom' ? 'Evaluado con el ROM' : 'Solves completos'} · {s.n_samples} muestras · {num(s.wall_time_s, 3)} s
      </Typography>
      <Button size="small" variant="outlined" startIcon={<ViewInAr />} onClick={onBand}>Ver bandas de confianza en 3D</Button>
    </Box>
  );
}

export default function UncertaintyPanel({ graphId }) {
  const {
    setup, vars, failure, settings, running, runError, runs, result,
    loadSetup, setVar, setFailure, setSetting, run, listRuns, loadResult, loadSurface,
  } = useUncertaintyStore();
  const [band, setBand] = useState(false);

  useEffect(() => {
    if (!graphId) return;
    loadSetup(graphId).catch((e) => useUncertaintyStore.setState({ runError: e.response?.data?.error || e.message }));
    listRuns(graphId).then(() => {
      const last = useUncertaintyStore.getState().runs.find((r) => r.status === 'done');
      if (last) loadResult(last.run_id).catch(() => {});
      else useUncertaintyStore.setState({ result: null });
    }).catch(() => {});
  }, [graphId, loadSetup, listRuns, loadResult]);

  const params = setup?.parameters || [];
  const nOn = Object.values(vars).filter((v) => v.on && v.std > 0).length;
  const roms = setup?.roms || [];
  const tier = 1;
  const cap = settings.method === 'full' ? (setup?.tier_samples?.[tier] || 100) : (setup?.max_rom_samples || 2000);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
      <Typography variant="caption" sx={{ color: '#888' }}>
        Monte Carlo: las propiedades del material (y las cargas) como variables aleatorias normales; el resultado
        es la distribución de σvM y |u|, la probabilidad de fallo frente a σy y las bandas de confianza.
      </Typography>
      {setup?.material?.material_name && (
        <Typography variant="caption" sx={{ color: '#90caf9' }}>Material del estudio: {setup.material.material_name}</Typography>
      )}
      {runError && <Alert severity="error" sx={{ fontSize: 12 }}>{runError}</Alert>}
      {params.map((p) => {
        const v = vars[p.key] || {};
        const sc = p.display_scale || 1;
        return (
          <Box key={p.key} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Checkbox size="small" checked={!!v.on} onChange={(e) => setVar(p.key, { on: e.target.checked })} sx={{ p: 0.25 }} />
            <Typography sx={{ ...label, flex: 1, minWidth: 0 }} noWrap title={p.label}>{p.label}</Typography>
            <TextField size="small" type="number" label={`μ [${p.display_unit}]`} sx={{ width: 90 }} disabled={!v.on}
              value={Number((v.mean * sc).toPrecision(6))} onChange={(e) => setVar(p.key, { mean: Number(e.target.value) / sc })} {...tf} />
            <TextField size="small" type="number" label="σ" sx={{ width: 76 }} disabled={!v.on}
              value={Number((v.std * sc).toPrecision(4))} onChange={(e) => setVar(p.key, { std: Number(e.target.value) / sc })} {...tf} />
            <Typography variant="caption" sx={{ color: '#777', width: 38 }}>
              {v.mean ? `${(100 * v.std / Math.abs(v.mean)).toFixed(1)}%` : ''}
            </Typography>
          </Box>
        );
      })}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <Checkbox size="small" checked={failure.on} onChange={(e) => setFailure({ on: e.target.checked })} sx={{ p: 0.25 }} />
        <Typography sx={{ ...label, flex: 1 }}>Fallo: σvM máx. ≥ σy</Typography>
        <TextField size="small" type="number" label="σy μ [MPa]" sx={{ width: 90 }} disabled={!failure.on}
          value={failure.yield_mean ? Number((failure.yield_mean / 1e6).toPrecision(5)) : ''}
          onChange={(e) => setFailure({ yield_mean: Number(e.target.value) * 1e6 })} {...tf} />
        <TextField size="small" type="number" label="σ" sx={{ width: 76 }} disabled={!failure.on}
          value={Number(((failure.yield_std || 0) / 1e6).toPrecision(4))}
          onChange={(e) => setFailure({ yield_std: Number(e.target.value) * 1e6 })} {...tf} />
        <Box sx={{ width: 38 }} />
      </Box>
      <Box sx={{ display: 'flex', gap: 1 }}>
        <FormControl size="small" sx={{ flex: 1 }}>
          <InputLabel sx={{ color: '#888' }}>Evaluación</InputLabel>
          <Select label="Evaluación" value={settings.method === 'rom' && settings.rom_id ? `rom:${settings.rom_id}` : settings.method}
            sx={{ color: '#fff', fontSize: 12 }}
            onChange={(e) => {
              const v = e.target.value;
              if (v.startsWith('rom:')) { setSetting('method', 'rom'); setSetting('rom_id', v.slice(4)); } else {
                setSetting('method', v); setSetting('rom_id', '');
                if (v === 'full') setSetting('n_samples', Math.min(settings.n_samples, setup?.tier_samples?.[tier] || 100));
              }
            }}>
            <MenuItem value="auto">Automática (ROM si cubre las variables)</MenuItem>
            {roms.map((r) => (
              <MenuItem key={r.rom_id} value={`rom:${r.rom_id}`}>
                ROM {r.hash.slice(0, 8)} ({Object.keys(r.parameter_space).join(', ')})
              </MenuItem>
            ))}
            <MenuItem value="full">Solves completos (lento)</MenuItem>
          </Select>
        </FormControl>
      </Box>
      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField size="small" type="number" label={`Muestras (máx. ${cap})`} value={settings.n_samples}
          onChange={(e) => setSetting('n_samples', parseInt(e.target.value, 10) || 10)} {...tf} />
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel sx={{ color: '#888' }}>Confianza</InputLabel>
          <Select label="Confianza" value={settings.confidence} sx={{ color: '#fff', fontSize: 12 }}
            onChange={(e) => setSetting('confidence', e.target.value)}>
            {[0.9, 0.95, 0.99].map((c) => <MenuItem key={c} value={c}>{Math.round(c * 100)} %</MenuItem>)}
          </Select>
        </FormControl>
      </Box>
      {settings.method === 'full' && (
        <Typography variant="caption" sx={{ color: '#ffb74d' }}>
          Cada muestra es una simulación completa: para modelos CAD grandes construye antes un ROM (pestaña ROM).
        </Typography>
      )}
      <Button variant="contained" startIcon={<Casino />} disabled={!graphId || !!running || nOn === 0}
        onClick={() => run(graphId)} sx={{ bgcolor: '#6a1b9a', '&:hover': { bgcolor: '#7b1fa2' } }}>
        Propagar incertidumbre ({nOn} variable{nOn === 1 ? '' : 's'})
      </Button>
      {running && (
        <Box>
          <Typography sx={label}>{running.status}{running.method && ` · ${running.method === 'rom' ? 'ROM' : 'solves completos'}`}</Typography>
          <LinearProgress variant="determinate" value={running.percent || 0} sx={{ height: 6, borderRadius: 1 }} />
        </Box>
      )}
      <Results result={result} onBand={async () => { await loadSurface(result.run_id); setBand(true); }} />
      {runs.length > 0 && <Typography sx={{ ...label, mt: 1, fontWeight: 700 }}>Estudios de incertidumbre</Typography>}
      {runs.map((r) => (
        <Box key={r.run_id} onClick={() => r.status === 'done' && loadResult(r.run_id)}
          sx={{ border: `1px solid ${result?.run_id === r.run_id ? '#7b1fa2' : '#333'}`, borderRadius: 1, p: 0.75,
            cursor: r.status === 'done' ? 'pointer' : 'default', display: 'flex', gap: 0.5, alignItems: 'center', flexWrap: 'wrap' }}>
          <Typography sx={{ fontSize: 11, fontFamily: 'monospace', color: '#90caf9' }}>{r.hash.slice(0, 8)}</Typography>
          <Chip size="small" label={r.status} sx={{ height: 18, fontSize: 10 }}
            color={r.status === 'done' ? 'success' : r.status === 'failed' ? 'error' : 'default'} />
          <Typography variant="caption" sx={{ color: '#999' }}>
            {r.method} · {r.n_samples} · {r.variables.map((k) => VAR_LABEL[k] || k).join(', ')}
            {r.p_failure != null && ` · Pf ${r.p_failure.toExponential(1)}`}
          </Typography>
          {r.error && <Typography variant="caption" sx={{ color: '#ef9a9a', width: '100%' }}>{r.error}</Typography>}
        </Box>
      ))}
      {band && <UncertaintyBand onClose={() => { setBand(false); useUncertaintyStore.getState().closeSurface(); }} />}
    </Box>
  );
}
