/**
 * MaterialImportDialog — import user materials from a CSV / Excel table: preview (column mapping, units, per-row
 * errors and the action each row gets) before anything is written.
 */
import React, { useRef, useState } from 'react';
import axios from 'axios';
import {
  Box, Dialog, DialogTitle, DialogContent, DialogActions, Button, Alert, Chip, Typography, Table, TableHead,
  TableRow, TableCell, TableBody, ToggleButton, ToggleButtonGroup, CircularProgress, Link,
} from '@mui/material';
import { UploadFile } from '@mui/icons-material';

const API = '/api/design/material/import';
const ACTION = {
  create: ['Nuevo', 'success'], update: ['Actualiza', 'info'], skip: ['Omitido', 'default'], error: ['Error', 'error'],
};
const MODES = [
  ['skip', 'Omitir existentes'], ['update', 'Actualizar existentes'], ['new', 'Crear siempre'],
];
// preview columns: key, label, scale SI → display
const COLS = [['E', 'E [GPa]', 1e-9], ['nu', 'ν', 1], ['rho', 'ρ [kg/m³]', 1], ['sigma_y', 'σy [MPa]', 1e-6],
  ['sigma_u', 'σu [MPa]', 1e-6], ['k', 'k [W/m·K]', 1], ['alpha', 'α [µm/m·K]', 1e6]];
const cell = { fontSize: 11, color: '#ccc', borderColor: '#333', py: 0.4, px: 0.8 };
const num = (v, sc) => (v == null ? '' : Number((v * sc).toPrecision(4)));

export default function MaterialImportDialog({ open, onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [mode, setMode] = useState('skip');
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const ref = useRef(null);

  const send = async (url, f, m) => {
    const fd = new FormData();
    fd.append('file', f);
    fd.append('on_duplicate', m);
    return (await axios.post(url, fd)).data;
  };
  const preview = async (f, m) => {
    setBusy(true); setError(null); setDone(null);
    try {
      setPlan(await send(`${API}/preview`, f, m));
    } catch (e) {
      setPlan(null);
      setError(e.response?.data?.error || e.message);
    } finally {
      setBusy(false);
    }
  };
  const onFile = (f) => { setFile(f); preview(f, mode); };
  const onMode = (_, m) => { if (!m) return; setMode(m); if (file) preview(file, m); };
  const onImport = async () => {
    setBusy(true); setError(null);
    try {
      const r = await send(API, file, mode);
      setDone(r.counts);
      setPlan(r);
      onImported?.(r.material_ids || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message);
    } finally {
      setBusy(false);
    }
  };
  const close = () => { setFile(null); setPlan(null); setError(null); setDone(null); onClose(); };
  const writable = plan ? plan.counts.create + plan.counts.update : 0;

  return (
    <Dialog open={open} onClose={close} maxWidth="lg" fullWidth
      PaperProps={{ sx: { bgcolor: '#1a1a1a', color: '#ddd' } }}>
      <DialogTitle sx={{ fontSize: 15, py: 1 }}>Importar materiales (CSV / Excel)</DialogTitle>
      <DialogContent dividers sx={{ borderColor: '#333', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        <Typography variant="caption" sx={{ color: '#999' }}>
          Una fila por material. Obligatorio: nombre, E y ν; opcional: categoría, densidad, σy, σu, alargamiento, k, α,
          cp, desviaciones («E std»), fuente y descripción. La unidad va en el encabezado, p. ej. «E [GPa]»; sin ella se
          deduce del orden de magnitud. Plantilla:{' '}
          <Link href={`${API}/template?format=xlsx`} sx={{ color: '#90caf9' }}>Excel</Link> ·{' '}
          <Link href={`${API}/template?format=csv`} sx={{ color: '#90caf9' }}>CSV</Link>.
          Los materiales del catálogo nunca se modifican.
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <input ref={ref} type="file" accept=".csv,.txt,.xlsx,.xlsm" hidden data-testid="import-file"
            onChange={(e) => { if (e.target.files.length) onFile(e.target.files[0]); e.target.value = ''; }} />
          <Button size="small" variant="outlined" startIcon={busy ? <CircularProgress size={14} /> : <UploadFile />}
            disabled={busy} onClick={() => ref.current?.click()}>
            {file ? file.name : 'Elegir archivo'}
          </Button>
          <ToggleButtonGroup size="small" exclusive value={mode} onChange={onMode}>
            {MODES.map(([k, l]) => (
              <ToggleButton key={k} value={k} sx={{ fontSize: 11, py: 0.3, color: '#aaa' }}>{l}</ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>
        {error && <Alert severity="error" sx={{ fontSize: 12 }}>{error}</Alert>}
        {done && (
          <Alert severity="success" sx={{ fontSize: 12 }}>
            Importados: {done.create} nuevos, {done.update} actualizados
            {done.skip ? `, ${done.skip} omitidos` : ''}{done.error ? `, ${done.error} con errores (no importados)` : ''}.
          </Alert>
        )}
        {plan && (
          <>
            {plan.notes.map((n) => <Typography key={n} variant="caption" sx={{ color: '#ffb74d' }}>{n}</Typography>)}
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
              {plan.columns.map((c) => (
                <Chip key={c.column} size="small" variant="outlined" sx={{ fontSize: 10, color: '#aaa', borderColor: '#444' }}
                  label={`${c.column} → ${c.property}${c.unit && c.unit !== '-' ? ` (${c.unit})` : ''}`} />
              ))}
            </Box>
            <Box sx={{ overflow: 'auto', maxHeight: '50vh' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    {['Fila', 'Estado', 'Nombre', 'Categoría', ...COLS.map((c) => c[1]), 'Avisos'].map((h) => (
                      <TableCell key={h} sx={{ ...cell, bgcolor: '#222', color: '#999' }}>{h}</TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {plan.rows.map((r) => {
                    const [lbl, col] = ACTION[r.action];
                    return (
                      <TableRow key={r.row}>
                        <TableCell sx={cell}>{r.row}</TableCell>
                        <TableCell sx={cell}><Chip size="small" color={col} label={lbl} sx={{ height: 18, fontSize: 10 }} /></TableCell>
                        <TableCell sx={cell}>{r.name}</TableCell>
                        <TableCell sx={cell}>{r.category}</TableCell>
                        {COLS.map(([k, , sc]) => <TableCell key={k} sx={cell}>{num(r.parameters[k]?.value, sc)}</TableCell>)}
                        <TableCell sx={{ ...cell, color: r.errors.length ? '#ef9a9a' : '#ffcc80', maxWidth: 280 }}>
                          {[...r.errors, ...r.warnings].join(' ')}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Box>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button size="small" onClick={close}>Cerrar</Button>
        <Button size="small" variant="contained" disabled={busy || !plan || !writable || !!done} onClick={onImport}>
          Importar {writable ? `${writable} material${writable > 1 ? 'es' : ''}` : ''}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
