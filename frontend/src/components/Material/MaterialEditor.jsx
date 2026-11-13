/**
 * MaterialEditor — FASE 6: material library, tensile-test fit (σ-ε CSV) with automatic model
 * selection, parameters with uncertainty (± std) and assignment to a MATERIAL node.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box, Dialog, DialogTitle, DialogContent, IconButton, Typography, TextField, Button, Alert, Chip,
  List, ListItemButton, ListItemText, Divider, MenuItem, Select, FormControl, InputLabel, Table, TableHead,
  TableRow, TableCell, TableBody, Tooltip, CircularProgress,
} from '@mui/material';
import { Close, Add, UploadFile, Link as LinkIcon, Save, Delete } from '@mui/icons-material';
import {
  ComposedChart, Line, Scatter, Area, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts';
import useMaterialStore from '../../stores/materialStore';

// display rows: key, label, unit, scale (SI → display)
export const PARAM_ROWS = [
  ['E', 'Módulo de Young E', 'GPa', 1e-9],
  ['nu', 'Coeficiente de Poisson ν', '', 1],
  ['rho', 'Densidad ρ', 'kg/m³', 1],
  ['sigma_y', 'Límite elástico σy (0.2 %)', 'MPa', 1e-6],
];
const SPEC_COLORS = ['#90caf9', '#ce93d8', '#a5d6a7', '#ffcc80', '#ef9a9a', '#80deea'];
const tf = { inputProps: { style: { color: '#fff', fontSize: 12 } }, InputLabelProps: { style: { color: '#888' } } };

export function fitQuality(r2) {
  if (r2 == null) return ['—', 'default'];
  if (r2 >= 0.995) return ['Excelente', 'success'];
  if (r2 >= 0.98) return ['Bueno', 'info'];
  if (r2 >= 0.9) return ['Regular', 'warning'];
  return ['Pobre', 'error'];
}

const fmt = (v, scale = 1, digits = 4) => (v == null || Number.isNaN(v) ? '' : Number((v * scale).toPrecision(digits)));

function ParamEditor({ params, onChange }) {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 110px 110px', gap: 1, alignItems: 'center' }}>
      {PARAM_ROWS.map(([k, label, unit, sc]) => {
        const p = params[k] || {};
        return (
          <React.Fragment key={k}>
            <Typography sx={{ fontSize: 12, color: '#bbb' }}>{label}{unit && ` [${unit}]`}</Typography>
            <TextField size="small" type="number" label="Valor" value={fmt(p.value, sc, 6)}
              onChange={(e) => onChange(k, 'value', e.target.value === '' ? null : Number(e.target.value) / sc)} {...tf} />
            <TextField size="small" type="number" label="± desv." value={fmt(p.std, sc, 4)}
              onChange={(e) => onChange(k, 'std', e.target.value === '' ? 0 : Number(e.target.value) / sc)} {...tf} />
          </React.Fragment>
        );
      })}
    </Box>
  );
}

function FitChart({ curves, model }) {
  const fit = curves?.fits?.[model];
  const data = useMemo(() => (fit ? curves.strain.map((e, i) => ({
    x: e * 100, fit: fit.stress[i], band: [fit.lower[i], fit.upper[i]],
  })) : []), [curves, fit]);
  if (!curves) return null;
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 4 }}>
        <CartesianGrid stroke="#333" />
        <XAxis dataKey="x" type="number" domain={[0, 'dataMax']} tick={{ fill: '#999', fontSize: 11 }}
          tickFormatter={(v) => v.toFixed(1)}
          label={{ value: 'Deformación [%]', position: 'insideBottom', offset: -8, fill: '#999', fontSize: 11 }} />
        <YAxis tick={{ fill: '#999', fontSize: 11 }} width={48}
          label={{ value: 'σ [MPa]', angle: -90, position: 'insideLeft', fill: '#999', fontSize: 11 }} />
        <RTooltip contentStyle={{ background: '#222', border: '1px solid #444', fontSize: 11 }}
          formatter={(v) => (Array.isArray(v) ? v.map((x) => x.toFixed(1)).join(' – ') : Number(v).toFixed(1))}
          labelFormatter={(v) => `ε = ${Number(v).toFixed(3)} %`} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {curves.specimens.map((s, i) => (
          <Scatter key={s.name} name={s.name} fill={SPEC_COLORS[i % SPEC_COLORS.length]} shape="circle"
            data={s.strain.map((e, j) => ({ x: e * 100, y: s.stress[j] }))} dataKey="y" isAnimationActive={false}
            line={false} r={1.5} />
        ))}
        {fit && <Area dataKey="band" name="Banda de predicción" stroke="none" fill="#ff9800" fillOpacity={0.2}
          isAnimationActive={false} />}
        {fit && <Line dataKey="fit" name="Ajuste" stroke="#ff9800" dot={false} strokeWidth={2} isAnimationActive={false} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export default function MaterialEditor({ open, onClose, graphId = null, nodeId = null, onAssigned = null }) {
  const {
    materials, current, fit, files, fitOptions, busy, error, list, open: openMat, create, save, remove,
    setFitOption, fitFiles, assign,
  } = useMaterialStore();
  const [newName, setNewName] = useState('');
  const [name, setName] = useState('');
  const [params, setParams] = useState({});
  const [dirty, setDirty] = useState(false);
  const [shown, setShown] = useState(null);
  const [assigned, setAssigned] = useState(null);
  const fileRef = useRef(null);

  useEffect(() => { if (open) list().catch(() => {}); }, [open, list]);
  useEffect(() => {
    setName(current?.name || '');
    setParams(current?.parameters || {});
    setDirty(false);
    setShown(current?.calibration?.best_model || null);
    setAssigned(null);
  }, [current]);

  const cal = current?.calibration || {};
  const results = fit?.all_results || cal.all_results || [];
  const curves = fit?.curves || cal.curves;
  const best = fit?.best_model || cal.best_model;
  const [qLabel, qColor] = fitQuality(fit?.r_squared ?? cal.r_squared);

  const setParam = (k, field, v) => {
    setParams((p) => ({ ...p, [k]: { ...(p[k] || { std: 0 }), [field]: v } }));
    setDirty(true);
  };
  const onSave = async () => {
    const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v && v.value != null));
    if (await save({ name, parameters: clean })) setDirty(false);
  };
  const onAssign = async () => {
    if (dirty) await onSave();
    const props = await assign(graphId, nodeId);
    if (props) {
      setAssigned(props);
      onAssigned?.(props);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth
      PaperProps={{ sx: { bgcolor: '#1a1a1a', color: '#ddd', height: '88vh' } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', fontSize: 15, py: 1 }}>
        <Box sx={{ flex: 1 }}>Materiales — modelos activos con incertidumbre</Box>
        <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}><Close fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ p: 0, display: 'flex', minHeight: 0, borderColor: '#333' }}>
        {/* library */}
        <Box sx={{ width: 230, borderRight: '1px solid #333', display: 'flex', flexDirection: 'column' }}>
          <Box sx={{ p: 1, display: 'flex', gap: 0.5 }}>
            <TextField size="small" placeholder="Nuevo material" value={newName}
              onChange={(e) => setNewName(e.target.value)} {...tf} />
            <IconButton size="small" disabled={!newName.trim()} sx={{ color: '#90caf9' }}
              onClick={async () => { if (await create(newName.trim())) setNewName(''); }}>
              <Add fontSize="small" />
            </IconButton>
          </Box>
          <List dense sx={{ overflow: 'auto', flex: 1 }}>
            {materials.map((m) => (
              <ListItemButton key={m.id} selected={current?.id === m.id} onClick={() => openMat(m.id)}>
                <ListItemText primary={m.name} primaryTypographyProps={{ fontSize: 12 }}
                  secondary={m.calibration?.label ? `${m.calibration.label} · R² ${m.calibration.r_squared?.toFixed(4)}` : m.model_type}
                  secondaryTypographyProps={{ fontSize: 10, color: '#888' }} />
              </ListItemButton>
            ))}
            {!materials.length && (
              <Typography variant="caption" sx={{ color: '#777', p: 1.5, display: 'block' }}>
                Biblioteca vacía: crea un material y ajústalo a tus ensayos.
              </Typography>
            )}
          </List>
        </Box>

        {/* editor */}
        <Box sx={{ flex: 1, overflow: 'auto', p: 2, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {error && <Alert severity="error" sx={{ fontSize: 12 }}>{error}</Alert>}
          {!current && <Typography sx={{ color: '#888' }}>Selecciona o crea un material.</Typography>}
          {current && (
            <>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                <TextField size="small" label="Nombre" value={name} sx={{ flex: 1 }}
                  onChange={(e) => { setName(e.target.value); setDirty(true); }} {...tf} />
                <Button size="small" variant="contained" startIcon={<Save />} disabled={!dirty} onClick={onSave}>Guardar</Button>
                {graphId && nodeId && (
                  <Button size="small" variant="outlined" startIcon={<LinkIcon />} onClick={onAssign}>
                    Asignar al nodo
                  </Button>
                )}
                <Tooltip title="Quitar de la biblioteca">
                  <IconButton size="small" sx={{ color: '#ef5350' }} onClick={() => remove(current.id)}><Delete fontSize="small" /></IconButton>
                </Tooltip>
              </Box>
              {assigned && (
                <Alert severity="success" sx={{ fontSize: 12 }}>
                  Asignado: E, ν, ρ y σy (con su desviación) en el nodo MATERIAL.
                </Alert>
              )}
              <Typography sx={{ fontSize: 12, color: '#888' }}>
                Modelo constitutivo: <b style={{ color: '#ddd' }}>{cal.label || 'Elástico lineal isótropo'}</b>
                {cal.label && ' — el solver FEM usa la parte elástica (E, ν); σy alimenta el criterio de fallo del estudio de incertidumbre.'}
              </Typography>
              <ParamEditor params={params} onChange={setParam} />
              {Object.entries(params).filter(([k]) => k.includes('.') || k === 'uts').length > 0 && (
                <Typography variant="caption" sx={{ color: '#888' }}>
                  {Object.entries(params).filter(([k]) => k.includes('.') || k === 'uts').map(([k, v]) => (
                    `${k.split('.').pop()} = ${fmt(v.value, v.unit === 'Pa' ? 1e-6 : 1)}${v.unit === 'Pa' ? ' MPa' : ''}` +
                    (v.std ? ` ± ${fmt(v.std, v.unit === 'Pa' ? 1e-6 : 1, 2)}` : '')
                  )).join(' · ')}
                </Typography>
              )}

              <Divider sx={{ borderColor: '#333' }} />
              <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Ensayo de tracción</Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                <input ref={fileRef} type="file" accept=".csv,.txt,.dat" multiple hidden data-testid="fit-files"
                  onChange={(e) => { if (e.target.files.length) fitFiles(e.target.files); e.target.value = ''; }} />
                <Button size="small" variant="outlined" startIcon={busy ? <CircularProgress size={14} /> : <UploadFile />}
                  disabled={busy} onClick={() => fileRef.current?.click()}>
                  Subir datos de ensayo (.csv)
                </Button>
                <FormControl size="small" sx={{ minWidth: 110 }}>
                  <InputLabel sx={{ color: '#888' }}>ε</InputLabel>
                  <Select label="ε" value={fitOptions.strain_unit} sx={{ color: '#fff', fontSize: 12 }}
                    onChange={(e) => setFitOption('strain_unit', e.target.value)}>
                    <MenuItem value="auto">auto</MenuItem><MenuItem value="%">%</MenuItem><MenuItem value="mm/mm">mm/mm</MenuItem>
                  </Select>
                </FormControl>
                <FormControl size="small" sx={{ minWidth: 110 }}>
                  <InputLabel sx={{ color: '#888' }}>σ</InputLabel>
                  <Select label="σ" value={fitOptions.stress_unit} sx={{ color: '#fff', fontSize: 12 }}
                    onChange={(e) => setFitOption('stress_unit', e.target.value)}>
                    {['auto', 'MPa', 'Pa', 'GPa', 'ksi', 'psi'].map((u) => <MenuItem key={u} value={u}>{u}</MenuItem>)}
                  </Select>
                </FormControl>
                <Tooltip title="Solo para columnas fuerza-desplazamiento">
                  <TextField size="small" type="number" label="Área [mm²]" value={fitOptions.area_mm2} sx={{ width: 100 }}
                    onChange={(e) => setFitOption('area_mm2', e.target.value)} {...tf} />
                </Tooltip>
                <TextField size="small" type="number" label="L0 [mm]" value={fitOptions.gauge_mm} sx={{ width: 90 }}
                  onChange={(e) => setFitOption('gauge_mm', e.target.value)} {...tf} />
              </Box>
              {(fit || cal.best_model) && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography sx={{ fontSize: 13 }}>
                    → Ajuste automático: <b>{cal.label}</b>, R² = {(fit?.r_squared ?? cal.r_squared)?.toFixed(4)}
                  </Typography>
                  <Chip size="small" label={qLabel} color={qColor} />
                  <Typography variant="caption" sx={{ color: '#888' }}>
                    {(fit?.std_source ?? cal.std_source) === 'specimens'
                      ? `± = dispersión entre ${cal.n_specimens} probetas`
                      : '± = error estándar del ajuste (una probeta: sube varias para la dispersión real)'}
                  </Typography>
                </Box>
              )}
              {(fit?.specimens || cal.specimens || []).map((s) => (
                [...(s.parse_notes || []), ...(s.notes || [])].length > 0 && (
                  <Typography key={s.name} variant="caption" sx={{ color: '#999' }}>
                    {s.name}: {[...(s.parse_notes || []), ...(s.notes || [])].join(' ')}
                  </Typography>
                )
              ))}
              <FitChart curves={curves} model={shown || best} />
              {results.length > 0 && (
                <Table size="small" sx={{ '& td, & th': { color: '#ccc', borderColor: '#333', fontSize: 11, py: 0.5 } }}>
                  <TableHead>
                    <TableRow><TableCell>Modelo</TableCell><TableCell>R² (mín.)</TableCell><TableCell>AICc</TableCell>
                      <TableCell>RMSE [MPa]</TableCell><TableCell>Parámetros</TableCell><TableCell /></TableRow>
                  </TableHead>
                  <TableBody>
                    {results.map((r) => (
                      <TableRow key={r.model} hover selected={(shown || best) === r.model} onClick={() => setShown(r.model)}
                        sx={{ cursor: 'pointer' }}>
                        <TableCell>{r.label}{r.model === best && <Chip size="small" label="elegido" color="warning" sx={{ ml: 0.5, height: 16, fontSize: 9 }} />}</TableCell>
                        <TableCell>{r.r2?.toFixed(5)}</TableCell>
                        <TableCell>{r.aicc?.toFixed(0)}</TableCell>
                        <TableCell>{r.rmse_mpa?.toFixed(2)}</TableCell>
                        <TableCell>
                          {Object.entries(r.parameters).map(([k, v]) => `${k}=${fmt(v.value, v.unit === 'Pa' ? 1e-6 : 1)}`).join(', ')}
                        </TableCell>
                        <TableCell>
                          {r.model !== best && files.length > 0 && (
                            <Button size="small" sx={{ fontSize: 10 }} onClick={(e) => { e.stopPropagation(); fitFiles(files, r.model); }}>
                              Usar
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </>
          )}
        </Box>
      </DialogContent>
    </Dialog>
  );
}
