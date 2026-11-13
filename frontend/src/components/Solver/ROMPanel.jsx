/**
 * ROMPanel — FASE 5: choose the study parameters and their ranges, build a POD ROM on the job
 * queue, and open finished ROMs in the real-time explorer.
 */
import React, { useEffect } from 'react';
import {
  Box, Typography, Checkbox, TextField, Button, LinearProgress, Alert, Chip, FormControlLabel,
} from '@mui/material';
import { Build, Bolt } from '@mui/icons-material';
import useROMStore from '../../stores/romStore';
import ROMExplorer from './ROMExplorer';

const label = { color: '#bbb', fontSize: 12 };
const inputSx = { inputProps: { style: { color: '#fff', fontSize: 12 } }, InputLabelProps: { style: { color: '#888' } } };

export default function ROMPanel({ graphId }) {
  const {
    candidates, space, buildSettings, building, buildError, roms, activeROM, loadingROM,
    loadCandidates, toggleParam, setRange, setBuildSetting, build, listROMs, openExplorer,
  } = useROMStore();

  useEffect(() => {
    if (!graphId) return;
    loadCandidates(graphId).catch((e) => useROMStore.setState({ buildError: e.response?.data?.error || e.message }));
    listROMs(graphId).catch(() => {});
  }, [graphId, loadCandidates, listROMs]);

  const nVar = Object.keys(space).length;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
      <Typography variant="caption" sx={{ color: '#888' }}>
        Modelo de orden reducido (POD): unas decenas de simulaciones completas en los extremos del rango
        y después respuesta instantánea para cualquier combinación de parámetros dentro de él.
      </Typography>
      {buildError && <Alert severity="error" sx={{ fontSize: 12 }}>{buildError}</Alert>}
      {candidates.map((p) => {
        const on = p.key in space;
        const sc = p.display_scale || 1;
        return (
          <Box key={p.key}>
            <FormControlLabel
              control={<Checkbox size="small" checked={on} onChange={(e) => toggleParam(p.key, e.target.checked)}
                disabled={!!building} />}
              label={<span style={label}>{p.label} <span style={{ color: '#777' }}>(nominal {Number((p.nominal * sc).toPrecision(4))} {p.display_unit})</span></span>}
            />
            {on && (
              <Box sx={{ display: 'flex', gap: 1, pl: 4 }}>
                {[0, 1].map((i) => (
                  <TextField key={i} size="small" type="number" label={`${i ? 'Máx' : 'Mín'} [${p.display_unit}]`}
                    value={Number((space[p.key][i] * sc).toPrecision(6))} disabled={!!building}
                    onChange={(e) => setRange(p.key, i, Number(e.target.value) / sc)} {...inputSx} />
                ))}
              </Box>
            )}
          </Box>
        );
      })}
      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField size="small" type="number" label="Snapshots" value={buildSettings.n_snapshots} disabled={!!building}
          onChange={(e) => setBuildSetting('n_snapshots', parseInt(e.target.value, 10) || 2)} {...inputSx} />
        <TextField size="small" type="number" label="Puntos de validación" value={buildSettings.n_test} disabled={!!building}
          onChange={(e) => setBuildSetting('n_test', parseInt(e.target.value, 10) || 0)} {...inputSx} />
      </Box>
      <Button variant="contained" startIcon={<Build />} disabled={!graphId || !!building || nVar === 0}
        onClick={() => build(graphId)} sx={{ bgcolor: '#e65100', '&:hover': { bgcolor: '#ef6c00' } }}>
        Construir ROM ({nVar} parámetro{nVar === 1 ? '' : 's'})
      </Button>
      {building && (
        <Box>
          <Typography sx={label}>{building.status}</Typography>
          <LinearProgress variant="determinate" value={building.percent || 0} sx={{ height: 6, borderRadius: 1 }} />
        </Box>
      )}
      {roms.length > 0 && <Typography sx={{ ...label, mt: 1, fontWeight: 700 }}>ROMs del estudio</Typography>}
      {roms.map((r) => (
        <Box key={r.rom_id} sx={{ border: '1px solid #333', borderRadius: 1, p: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
            <Typography sx={{ fontSize: 11, fontFamily: 'monospace', color: '#90caf9' }}>{r.hash.slice(0, 8)}</Typography>
            <Chip size="small" label={r.status} sx={{ height: 18, fontSize: 10 }}
              color={r.status === 'done' ? 'success' : r.status === 'failed' ? 'error' : 'default'} />
            {r.n_modes != null && <Chip size="small" label={`${r.n_modes} modos`} sx={{ height: 18, fontSize: 10 }} />}
            {r.validation_max_error_u != null && (
              <Chip size="small" label={`error ${r.validation_max_error_u.toExponential(0)}`} sx={{ height: 18, fontSize: 10 }} />
            )}
          </Box>
          <Typography variant="caption" sx={{ color: '#888' }}>
            {Object.keys(r.parameter_space || {}).join(', ')}
            {r.build_s != null && ` · ${r.build_s.toFixed(0)} s`}
          </Typography>
          {r.error && <Typography variant="caption" sx={{ color: '#ef9a9a' }}>{r.error}</Typography>}
          {r.status === 'done' && (
            <Button size="small" startIcon={<Bolt />} onClick={() => openExplorer(r.rom_id)} disabled={loadingROM}>
              Abrir explorador
            </Button>
          )}
        </Box>
      ))}
      {(activeROM || loadingROM) && <ROMExplorer />}
    </Box>
  );
}
