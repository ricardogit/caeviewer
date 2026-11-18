/**
 * TopologyPanel — FASE 4: SIMP (optionally with the AM overhang filter) or level-set topology
 * optimization of the active study.
 *
 * Uses the graph's geometry, material, supports and loads; the settings are stored in the
 * graph's OPTIMIZATION node. Live compliance curve and 3D density field while it runs; the
 * optimum can be downloaded (STL/GLB) or added to the graph as a GEOMETRY node.
 */
import React, { useState } from 'react';
import {
  Box, Typography, Slider, TextField, Switch, FormControlLabel, Button, LinearProgress, Alert,
  Dialog, DialogTitle, DialogContent, DialogActions, IconButton, Chip, Radio, RadioGroup, Tooltip,
} from '@mui/material';
import { PlayArrow, Stop, ViewInAr, Close, Download, AddBox } from '@mui/icons-material';
import { LineChart, Line, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

import useTopologyStore from '../../stores/topologyStore';
import DensityField from './DensityField';

const API = '/api/design/topology';
const label = { color: '#bbb', fontSize: 12 };
const fmt = (v, d = 4) => (v == null ? '—' : Number(v).toPrecision(d));
const BUILD_DIRS = [
  { key: '+Z', v: [0, 0, 1] }, { key: '+Y', v: [0, 1, 0] }, { key: '+X', v: [1, 0, 0] },
  { key: '−Z', v: [0, 0, -1] }, { key: '−Y', v: [0, -1, 0] }, { key: '−X', v: [-1, 0, 0] },
];
const dirKey = (v) => (BUILD_DIRS.find(d => d.v.every((c, i) => c === Number(v?.[i]))) || BUILD_DIRS[0]).key;

function AMSummary({ am }) {
  if (!am) return null;
  return (
    <div>
      Imprimibilidad ({am.max_overhang_angle}°, {dirKey(am.build_direction)}): voladizo
      {' '}{(100 * am.overhang_area_fraction).toFixed(1)} % del área · sin soporte
      {' '}{(100 * am.unsupported_volume_fraction).toFixed(1)} % del volumen
      {am.constrained ? ' · con restricción AM' : ''}
    </div>
  );
}

function ViewerDialog({ open, onClose }) {
  const { runId, snapshotIter, status, extract, extracted } = useTopologyStore();
  const [threshold, setThreshold] = useState(0.5);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const done = status === 'done';

  const onExtract = async () => {
    setBusy(true); setMsg(null);
    try {
      const d = await extract(threshold);
      setMsg({ severity: 'success', text: `Nodo GEOMETRY "${Math.round(threshold * 100)} %" agregado al grafo `
        + `(${Math.round(d.properties.volume_mm3).toLocaleString()} mm³, ${d.properties.watertight ? 'cerrado' : 'abierto'}).` });
    } catch (e) {
      setMsg({ severity: 'error', text: e.response?.data?.error || e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth
      PaperProps={{ sx: { bgcolor: '#1a1a1a', color: '#ddd', height: '85vh' } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: 15, py: 1 }}>
        <ViewInAr sx={{ color: '#90caf9' }} />
        <Box sx={{ flex: 1 }}>Campo de densidad</Box>
        <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}><Close fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ p: 0, borderColor: '#333', display: 'flex', flexDirection: 'column' }}>
        <Box sx={{ flex: 1, minHeight: 0 }}>
          {runId && <DensityField runId={runId} snapshotIter={snapshotIter} threshold={threshold} />}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, px: 2, py: 1, borderTop: '1px solid #333' }}>
          <Typography sx={label}>Umbral ρ</Typography>
          <Slider value={threshold} min={0.1} max={0.9} step={0.05} size="small" sx={{ width: 240 }}
            valueLabelDisplay="auto" onChange={(_, v) => setThreshold(v)} />
          <Typography sx={{ ...label, flex: 1 }}>
            Superficie ρ = {threshold.toFixed(2)} sobre el campo nodal; los elementos con ρ menor se consideran vacío.
          </Typography>
        </Box>
        {msg && <Alert severity={msg.severity} sx={{ m: 1 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button size="small" startIcon={<Download />} disabled={!runId}
          href={`${API}/${runId}/isosurface?threshold=${threshold}&format=stl&download=1`}>STL</Button>
        <Button size="small" startIcon={<Download />} disabled={!runId}
          href={`${API}/${runId}/isosurface?threshold=${threshold}&format=glb&download=1`}>GLB</Button>
        <Tooltip title={done ? 'Guarda la superficie y crea un nodo GEOMETRY producido por la optimización'
          : 'Disponible al terminar'}>
          <span>
            <Button size="small" variant="contained" startIcon={<AddBox />} disabled={!done || busy}
              onClick={onExtract}>
              {extracted ? 'Extraer otra vez' : 'Extraer geometría óptima'}
            </Button>
          </span>
        </Tooltip>
      </DialogActions>
    </Dialog>
  );
}

export default function TopologyPanel({ graphId }) {
  const {
    settings, setSetting, status, stage, history, maxIter, summary, meta, error,
    start, cancel, clearError, runId,
  } = useTopologyStore();
  const [viewerOpen, setViewerOpen] = useState(false);
  const running = status === 'queued' || status === 'running';
  const last = history[history.length - 1];
  const first = history[0];
  const c0 = summary?.compliance_initial ?? first?.compliance;
  const c = summary?.compliance_bw ?? last?.compliance;
  const pct = last && maxIter ? Math.min(100, (100 * last.iter) / maxIter) : 0;
  const ls = settings.method === 'levelset';

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
      {error && <Alert severity="error" onClose={clearError} sx={{ fontSize: 12 }}>{error}</Alert>}
      <Typography variant="caption" sx={{ color: '#888' }}>
        Minimiza la flexibilidad del estudio (geometría, material, apoyos y cargas del grafo) con una
        fracción de volumen dada. Los elementos que tocan apoyos y cargas se mantienen sólidos.
      </Typography>

      <RadioGroup row value={settings.method} onChange={e => setSetting('method', e.target.value)}>
        <FormControlLabel value="simp" disabled={running} control={<Radio size="small" />}
          label={<span style={label}>SIMP</span>} />
        <FormControlLabel value="levelset" disabled={running} control={<Radio size="small" />}
          label={<span style={label}>Level Set</span>} />
      </RadioGroup>
      {ls && (
        <Typography variant="caption" sx={{ color: '#888' }}>
          Level set de reacción-difusión: contorno nítido (sin densidades intermedias salvo una banda de un
          elemento); los huecos pueden nacer en cualquier punto. τ controla la complejidad de la forma.
        </Typography>
      )}

      <Box>
        <Typography sx={label}>Fracción de volumen: {Math.round(settings.volume_fraction * 100)} %</Typography>
        <Slider size="small" value={settings.volume_fraction} min={0.05} max={0.9} step={0.05} disabled={running}
          onChange={(_, v) => setSetting('volume_fraction', v)} />
      </Box>
      {ls ? (
        <>
          <Box>
            <Typography sx={label}>Regularización τ: {Number(settings.tau).toExponential(1)}</Typography>
            <Slider size="small" value={Math.log10(settings.tau)} min={-5} max={-2} step={0.1} disabled={running}
              onChange={(_, v) => setSetting('tau', Number((10 ** v).toPrecision(2)))} />
          </Box>
          <Box>
            <Typography sx={label}>Rampa de volumen: {settings.ramp_iter} iteraciones</Typography>
            <Slider size="small" value={settings.ramp_iter} min={10} max={100} step={5} disabled={running}
              onChange={(_, v) => setSetting('ramp_iter', v)} />
          </Box>
        </>
      ) : (
      <>
      <Box>
        <Typography sx={label}>Penalización p: {settings.p_penalization}</Typography>
        <Slider size="small" value={settings.p_penalization} min={1} max={5} step={0.5} disabled={running}
          onChange={(_, v) => setSetting('p_penalization', v)} />
      </Box>
      <Box>
        <Typography sx={label}>Radio de filtro: {settings.filter_factor} × arista media</Typography>
        <Slider size="small" value={settings.filter_factor} min={1.2} max={4} step={0.2} disabled={running}
          onChange={(_, v) => setSetting('filter_factor', v)} />
      </Box>
      </>
      )}
      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField label="Iteraciones máx." size="small" type="number" value={settings.max_iter} disabled={running}
          onChange={e => setSetting('max_iter', parseInt(e.target.value, 10) || 1)}
          inputProps={{ style: { color: '#fff' } }} InputLabelProps={{ style: { color: '#888' } }} />
        <TextField label="Tamaño elemento [mm]" size="small" type="number" value={settings.mesh_size_mm}
          placeholder="auto" disabled={running} onChange={e => setSetting('mesh_size_mm', e.target.value)}
          inputProps={{ style: { color: '#fff' } }} InputLabelProps={{ style: { color: '#888' }, shrink: true }} />
      </Box>
      {!ls && (
        <FormControlLabel disabled={running}
          control={<Switch size="small" checked={settings.projection} onChange={e => setSetting('projection', e.target.checked)} />}
          label={<span style={label}>Proyección Heaviside (diseño 0/1 nítido)</span>} />
      )}
      <FormControlLabel disabled={running}
        control={<Switch size="small" checked={settings.keep_bc_load_solid}
          onChange={e => setSetting('keep_bc_load_solid', e.target.checked)} />}
        label={<span style={label}>Mantener sólidos apoyos y cargas</span>} />
      <Tooltip title={ls ? 'La restricción de voladizo está disponible con SIMP' : ''}>
        <FormControlLabel disabled={running || ls}
          control={<Switch size="small" checked={!ls && settings.am_constraint}
            onChange={e => setSetting('am_constraint', e.target.checked)} />}
          label={<span style={{ ...label, color: ls ? '#666' : label.color }}>
            Manufactura aditiva: sin voladizos (autosoportado)</span>} />
      </Tooltip>
      {!ls && settings.am_constraint && (
        <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center', pl: 1 }}>
          <TextField select label="Dirección de impresión" size="small" value={dirKey(settings.build_direction)}
            disabled={running} SelectProps={{ native: true }} sx={{ width: 150 }}
            onChange={e => setSetting('build_direction', BUILD_DIRS.find(d => d.key === e.target.value).v)}
            inputProps={{ style: { color: '#fff' } }} InputLabelProps={{ style: { color: '#888' } }}>
            {BUILD_DIRS.map(d => <option key={d.key} value={d.key}>{d.key}</option>)}
          </TextField>
          <Box sx={{ flex: 1 }}>
            <Typography sx={label}>Ángulo máx. de voladizo: {settings.max_overhang_angle}°</Typography>
            <Slider size="small" value={settings.max_overhang_angle} min={30} max={70} step={5} disabled={running}
              onChange={(_, v) => setSetting('max_overhang_angle', v)} />
          </Box>
        </Box>
      )}

      {!running ? (
        <Button variant="contained" startIcon={<PlayArrow />} disabled={!graphId} onClick={() => start(graphId)}
          sx={{ bgcolor: '#6a1b9a', '&:hover': { bgcolor: '#7b1fa2' } }}>
          Optimizar topología
        </Button>
      ) : (
        <Button variant="outlined" color="error" startIcon={<Stop />} onClick={cancel}>Detener</Button>
      )}

      {(running || history.length > 0) && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography sx={label}>{stage}{last ? ` · iter ${last.iter}${maxIter ? ` / ${maxIter}` : ''}` : ''}</Typography>
            {last?.beta != null && <Chip size="small" label={`β ${last.beta}`} sx={{ height: 18, fontSize: 10 }} />}
          </Box>
          <LinearProgress variant={last ? 'determinate' : 'indeterminate'} value={status === 'done' ? 100 : pct}
            sx={{ mt: 0.5, height: 6, borderRadius: 1 }} />
        </Box>
      )}
      {meta && (
        <Typography variant="caption" sx={{ color: '#888' }}>
          {meta.n_elements?.toLocaleString()} T4 · {meta.n_design?.toLocaleString()} de diseño
          {meta.filter_radius != null ? ` · filtro r = ${fmt(meta.filter_radius * 1000, 3)} mm` : ''}
        </Typography>
      )}
      {history.length > 0 && (
        <>
          <Box sx={{ bgcolor: '#141414', border: '1px solid #333', borderRadius: 1, p: 1, fontSize: 12, color: '#ccc' }}>
            <div>Flexibilidad: {fmt(c0)} → {fmt(c)}{c0 && c ? ` (−${Math.round(100 * (1 - c / c0))} %)` : ''}</div>
            <div>Volumen: {last ? `${(100 * last.volume_fraction).toFixed(1)} %` : '—'} · grises:
              {' '}{last ? `${(100 * (summary?.grayness ?? last.grayness)).toFixed(1)} %` : '—'}</div>
            {summary && (
              <div>{summary.method ? `${summary.method} · ` : ''}{summary.converged ? 'Convergió' : 'Sin converger'} en
                {' '}{summary.n_iterations} iteraciones · {fmt(summary.wall_time_s, 3)} s</div>
            )}
            <AMSummary am={summary?.am} />
          </Box>
          <Box sx={{ height: 120 }}>
            <ResponsiveContainer>
              <LineChart data={history} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid stroke="#333" strokeDasharray="3 3" />
                <XAxis dataKey="iter" tick={{ fontSize: 9, fill: '#888' }} />
                <YAxis tick={{ fontSize: 9, fill: '#888' }} tickFormatter={v => Number(v).toPrecision(2)} domain={['auto', 'auto']} />
                <RTooltip contentStyle={{ background: '#222', border: '1px solid #444', fontSize: 11 }}
                  formatter={(v) => Number(v).toPrecision(4)} labelFormatter={l => `iter ${l}`} />
                <Line type="monotone" dataKey="compliance" name="C" stroke="#ce93d8" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </Box>
        </>
      )}
      {runId && (
        <Button size="small" variant="outlined" startIcon={<ViewInAr />} onClick={() => setViewerOpen(true)}>
          Ver densidades 3D
        </Button>
      )}
      <ViewerDialog open={viewerOpen} onClose={() => setViewerOpen(false)} />
    </Box>
  );
}
