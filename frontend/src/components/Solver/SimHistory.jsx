/**
 * SimHistory — FASE 7: simulation history with hash, lineage, reports and exact reproduction.
 *
 * Runs with the same parameters share the input hash (same colour). [Ver] opens the
 * Markdown report (downloadable as .md / JSON-LD); [Reproducir] re-runs the stored spec after
 * checking that the numerical environment matches the recorded one.
 */
import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import {
  Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography, Alert,
} from '@mui/material';
import {
  Close, Refresh, Replay, Description, ContentCopy, CheckCircle, Cancel, Download,
} from '@mui/icons-material';

const API = '/api/design/solver';
const PURPOSE = { run: 'Simulación', reproduce: 'Reproducción', adaptive: 'Adaptativa', topology: 'Topología' };
const STATUS = {
  queued: ['En cola', 'info'], running: ['Calculando', 'warning'], done: ['OK', 'success'],
  failed: ['Error', 'error'], cancelled: ['Cancelada', 'default'],
};
const HASH_COLORS = ['#4fc3f7', '#ffb74d', '#81c784', '#f06292', '#ba68c8', '#ffd54f', '#4db6ac', '#e57373'];

const cell = { color: '#ddd', borderColor: '#333', fontSize: 12, py: 0.5, px: 1 };
const head = { ...cell, color: '#90caf9', fontWeight: 700, bgcolor: '#0d1b2a' };

const fmt = (v, d = 4) => (v === null || v === undefined ? '—' : Number(v).toPrecision(d));

function hashColor(hash, palette) {
  if (!palette.has(hash)) palette.set(hash, HASH_COLORS[palette.size % HASH_COLORS.length]);
  return palette.get(hash);
}

function copy(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text);
}

function ReproducibilityCell({ run }) {
  const [res, setRes] = useState(null);
  useEffect(() => {
    if (run.purpose !== 'reproduce' || run.status !== 'done') return;
    axios.get(`${API}/${run.run_id}/reproducibility`).then(r => setRes(r.data)).catch(() => setRes(null));
  }, [run.run_id, run.purpose, run.status]);
  if (run.purpose !== 'reproduce') return null;
  if (run.status !== 'done') return <Typography variant="caption" sx={{ color: '#888' }}>—</Typography>;
  if (!res) return <CircularProgress size={12} />;
  const ok = res.reproduced;
  const text = res.bitwise_identical
    ? 'Idéntico bit a bit'
    : res.max_rel_diff_displacement !== null ? `Δu rel. ${fmt(res.max_rel_diff_displacement, 2)}` : 'Distinto';
  return (
    <Tooltip title={
      <Box sx={{ fontSize: 11 }}>
        <div>Hash de entradas: {res.same_hash ? 'igual' : 'distinto'}</div>
        <div>Malla: {res.same_mesh ? 'igual' : 'distinta'}</div>
        <div>Desplazamientos: {res.bitwise_identical ? 'idénticos bit a bit' : 'distintos'}</div>
        {res.max_rel_diff_von_mises !== null && <div>Δ von Mises rel.: {fmt(res.max_rel_diff_von_mises, 2)}</div>}
        {Object.keys(res.environment_diff || {}).length > 0 && (
          <div>Entorno: {Object.entries(res.environment_diff).map(([k, [a, b]]) => `${k} ${a}→${b}`).join(', ')}</div>
        )}
      </Box>
    }>
      <Chip size="small" icon={ok ? <CheckCircle /> : <Cancel />} label={text}
        color={ok ? 'success' : 'error'} variant="outlined" sx={{ height: 20, fontSize: 10 }} />
    </Tooltip>
  );
}

function ReportDialog({ run, onClose }) {
  const [md, setMd] = useState('');
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!run) return;
    setMd(''); setErr(null);
    axios.get(`${API}/${run.run_id}/report`, { params: { format: 'markdown' }, responseType: 'text' })
      .then(r => setMd(r.data)).catch(e => setErr(e.message));
  }, [run]);
  if (!run) return null;
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth PaperProps={{ sx: { bgcolor: '#1a1a1a', color: '#ddd' } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: 15 }}>
        <Description sx={{ color: '#90caf9' }} />
        <Box sx={{ flex: 1 }}>Reporte <code>{run.hash.slice(0, 12)}</code></Box>
        <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}><Close fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ borderColor: '#333' }}>
        {err && <Alert severity="error">{err}</Alert>}
        {!md && !err && <CircularProgress size={20} />}
        <Box component="pre" sx={{
          m: 0, whiteSpace: 'pre-wrap', fontFamily: 'Consolas, monospace', fontSize: 12, color: '#ddd',
        }}>{md}</Box>
      </DialogContent>
      <DialogActions>
        <Button size="small" startIcon={<Download />} href={`${API}/${run.run_id}/report?format=markdown&download=1`}>
          Markdown
        </Button>
        <Button size="small" startIcon={<Download />} href={`${API}/${run.run_id}/report?format=jsonld&download=1`}>
          JSON-LD
        </Button>
        <Button size="small" onClick={onClose}>Cerrar</Button>
      </DialogActions>
    </Dialog>
  );
}

function ReproduceDialog({ run, onClose, onLaunched }) {
  const [env, setEnv] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!run) return;
    setEnv(null); setErr(null);
    axios.get(`${API}/environment`).then(r => setEnv(r.data)).catch(e => setErr(e.message));
  }, [run]);
  if (!run) return null;
  const recorded = run.environment || {};
  const keys = Array.from(new Set([...Object.keys(recorded), ...Object.keys(env || {})])).sort();
  const mismatch = env ? keys.filter(k => String(recorded[k]) !== String(env[k])) : [];

  const launch = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await axios.post(`${API}/${run.run_id}/reproduce`, { force: mismatch.length > 0 });
      onLaunched(r.data);
    } catch (e) {
      setErr(e.response?.data?.message || e.response?.data?.error || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth PaperProps={{ sx: { bgcolor: '#1a1a1a', color: '#ddd' } }}>
      <DialogTitle sx={{ fontSize: 15 }}>Reproducir simulación <code>{run.hash.slice(0, 12)}</code></DialogTitle>
      <DialogContent dividers sx={{ borderColor: '#333', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        <Typography variant="body2" sx={{ color: '#bbb' }}>
          Se vuelve a ejecutar exactamente la especificación guardada de esta corrida. Al terminar se
          compara el hash de la malla y del campo de desplazamientos con el original.
        </Typography>
        {err && <Alert severity="error">{err}</Alert>}
        {!env && !err && <CircularProgress size={20} />}
        {env && (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={head}>Entorno numérico</TableCell>
                <TableCell sx={head}>Registrado</TableCell>
                <TableCell sx={head}>Actual</TableCell>
                <TableCell sx={head} />
              </TableRow>
            </TableHead>
            <TableBody>
              {keys.map(k => {
                const same = String(recorded[k]) === String(env[k]);
                return (
                  <TableRow key={k}>
                    <TableCell sx={cell}>{k}</TableCell>
                    <TableCell sx={{ ...cell, fontFamily: 'monospace' }}>{String(recorded[k] ?? '—')}</TableCell>
                    <TableCell sx={{ ...cell, fontFamily: 'monospace' }}>{String(env[k] ?? '—')}</TableCell>
                    <TableCell sx={cell}>
                      {same ? <CheckCircle sx={{ fontSize: 14, color: '#66bb6a' }} />
                        : <Cancel sx={{ fontSize: 14, color: '#ef5350' }} />}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        {env && mismatch.length > 0 && (
          <Alert severity="warning" sx={{ fontSize: 12 }}>
            El entorno difiere en {mismatch.join(', ')}: la nueva corrida tendrá otro hash y el resultado
            puede no ser idéntico bit a bit.
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button size="small" onClick={onClose}>Cancelar</Button>
        <Button size="small" variant="contained" startIcon={busy ? <CircularProgress size={14} /> : <Replay />}
          disabled={!env || busy} onClick={launch} color={mismatch.length ? 'warning' : 'primary'}>
          {mismatch.length ? 'Reproducir de todos modos' : 'Reproducir'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function SimHistory({ open, graphId, onClose }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [reportRun, setReportRun] = useState(null);
  const [reproRun, setReproRun] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    if (!graphId) return;
    setLoading(true);
    try {
      const r = await axios.get(`${API}/runs`, { params: { graph_id: graphId, limit: 100 } });
      setRuns(r.data.runs || []);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [graphId]);

  useEffect(() => { if (open) load(); }, [open, load]);

  // poll while something is pending
  const pending = runs.some(r => r.status === 'queued' || r.status === 'running');
  useEffect(() => {
    if (!open || !pending) return undefined;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [open, pending, load]);

  const palette = new Map();
  [...runs].reverse().forEach(r => hashColor(r.hash, palette));
  const index = Object.fromEntries(runs.map((r, i) => [r.run_id, runs.length - i]));

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xl" fullWidth
      PaperProps={{ sx: { bgcolor: '#1a1a1a', color: '#ddd', minHeight: '60vh' } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: 16 }}>
        <Box sx={{ flex: 1 }}>Historial de simulaciones</Box>
        <Tooltip title="Actualizar">
          <IconButton size="small" onClick={load} sx={{ color: '#888' }}>
            {loading ? <CircularProgress size={16} /> : <Refresh fontSize="small" />}
          </IconButton>
        </Tooltip>
        <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}><Close fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ borderColor: '#333', p: 0 }}>
        {error && <Alert severity="error" sx={{ m: 1 }}>{error}</Alert>}
        {notice && <Alert severity="info" sx={{ m: 1 }} onClose={() => setNotice(null)}>{notice}</Alert>}
        {!runs.length && !loading && (
          <Typography sx={{ p: 2, color: '#888' }}>Este grafo todavía no tiene simulaciones.</Typography>
        )}
        {runs.length > 0 && (
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                {['#', 'Hash', 'Fecha', 'Tipo', 'Tier', 'Física', 'Malla', 'u máx [mm]', 'σvM máx [MPa]',
                  'Estado', 'Cambios / reproducción', 'Acción'].map(h => <TableCell key={h} sx={head}>{h}</TableCell>)}
              </TableRow>
            </TableHead>
            <TableBody>
              {runs.map(r => {
                const [stLabel, stColor] = STATUS[r.status] || [r.status, 'default'];
                const color = hashColor(r.hash, palette);
                const delta = Object.entries(r.parameter_delta || {});
                return (
                  <TableRow key={r.run_id} hover>
                    <TableCell sx={cell}>{index[r.run_id]}</TableCell>
                    <TableCell sx={cell}>
                      <Tooltip title={
                        <Box sx={{ fontSize: 11, fontFamily: 'monospace' }}>
                          <div>entradas: {r.hash}</div>
                          <div>malla: {r.mesh_hash || '—'}</div>
                          <div>resultado: {r.result_hash || '—'}</div>
                          {r.same_hash_runs > 1 && <div>{r.same_hash_runs} corridas con este hash</div>}
                        </Box>
                      }>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: color }} />
                          <Box component="span" sx={{ fontFamily: 'monospace', color }}>{r.hash.slice(0, 8)}</Box>
                          {r.same_hash_runs > 1 && (
                            <Box component="span" sx={{ color: '#888', fontSize: 10 }}>×{r.same_hash_runs}</Box>
                          )}
                          <IconButton size="small" onClick={() => copy(r.hash)} sx={{ color: '#666', p: 0.25 }}>
                            <ContentCopy sx={{ fontSize: 12 }} />
                          </IconButton>
                        </Box>
                      </Tooltip>
                    </TableCell>
                    <TableCell sx={cell}>{r.created_at ? new Date(r.created_at).toLocaleString() : '—'}</TableCell>
                    <TableCell sx={cell}>{PURPOSE[r.purpose] || r.purpose}</TableCell>
                    <TableCell sx={cell}>{r.tier}</TableCell>
                    <TableCell sx={cell}>{(r.physics || []).join(' + ') || '—'}</TableCell>
                    <TableCell sx={cell}>
                      {r.n_nodes ? `${r.element_type || ''} · ${Number(r.n_nodes).toLocaleString()} nodos` : '—'}
                    </TableCell>
                    <TableCell sx={cell}>{fmt(r.max_displacement_mm)}</TableCell>
                    <TableCell sx={cell}>{fmt(r.max_von_mises_mpa)}</TableCell>
                    <TableCell sx={cell}>
                      <Tooltip title={r.error || (r.converged === false ? 'No convergió' : '')}>
                        <Chip size="small" label={r.status === 'done' && r.converged === false ? 'No conv.' : stLabel}
                          color={r.status === 'done' && r.converged === false ? 'warning' : stColor}
                          sx={{ height: 20, fontSize: 10 }} />
                      </Tooltip>
                    </TableCell>
                    <TableCell sx={cell}>
                      {r.purpose === 'reproduce' ? (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Typography variant="caption" sx={{ color: '#888' }}>
                            de #{index[r.parent_run_id] ?? '?'}
                          </Typography>
                          <ReproducibilityCell run={r} />
                        </Box>
                      ) : delta.length > 0 ? (
                        <Tooltip title={
                          <Box sx={{ fontSize: 11 }}>
                            {delta.map(([k, [a, b]]) => (
                              <div key={k}><code>{k}</code>: {JSON.stringify(a)} → {JSON.stringify(b)}</div>
                            ))}
                          </Box>
                        }>
                          <Chip size="small" variant="outlined" sx={{ height: 20, fontSize: 10, color: '#ffb74d', borderColor: '#ffb74d' }}
                            label={delta.length === 1 ? delta[0][0] : `${delta.length} cambios`} />
                        </Tooltip>
                      ) : r.parent_run_id ? (
                        <Typography variant="caption" sx={{ color: '#888' }}>sin cambios</Typography>
                      ) : null}
                    </TableCell>
                    <TableCell sx={{ ...cell, whiteSpace: 'nowrap' }}>
                      <Button size="small" startIcon={<Description sx={{ fontSize: 14 }} />}
                        sx={{ fontSize: 11, minWidth: 0 }} onClick={() => setReportRun(r)}>Ver</Button>
                      {r.status === 'done' && r.purpose !== 'adaptive' && (
                        <Button size="small" startIcon={<Replay sx={{ fontSize: 14 }} />}
                          sx={{ fontSize: 11, minWidth: 0 }} onClick={() => setReproRun(r)}>Reproducir</Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </DialogContent>
      <ReportDialog run={reportRun} onClose={() => setReportRun(null)} />
      <ReproduceDialog
        run={reproRun}
        onClose={() => setReproRun(null)}
        onLaunched={(d) => {
          setReproRun(null);
          setNotice(`Reproducción en cola (hash ${d.same_hash ? 'igual al original' : 'distinto: el entorno cambió'}).`);
          load();
        }}
      />
    </Dialog>
  );
}
