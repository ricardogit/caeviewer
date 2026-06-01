/**
 * SolverPanel — FEM solver configuration and launcher.
 * FASE 2: structural linear elastic + cantilever validation.
 */
import React, { useState } from 'react';
import {
  Box, Typography, TextField, Select, MenuItem, FormControl,
  InputLabel, Button, Chip, Divider, CircularProgress, Alert,
  ToggleButtonGroup, ToggleButton, Tooltip, LinearProgress,
  Accordion, AccordionSummary, AccordionDetails, IconButton,
} from '@mui/material';
import {
  PlayArrow, Stop, ExpandMore, Science, CheckCircle,
  Warning, Close, Refresh,
} from '@mui/icons-material';

import useDesignStore from '../../stores/designStore';
import useSolverStore from '../../stores/solverStore';
import ConvergenceMonitor from './ConvergenceMonitor';
import AdaptiveMonitor from './AdaptiveMonitor';

const STATUS_COLOR = {
  idle: 'default', queued: 'info', running: 'warning',
  done: 'success', failed: 'error', cancelled: 'default',
};
const STATUS_LABEL = {
  idle: 'En espera', queued: 'En cola', running: 'Calculando...',
  done: 'Completado', failed: 'Error', cancelled: 'Cancelado',
};

export default function SolverPanel({ onClose }) {
  const { activeGraphId } = useDesignStore();
  const {
    runStatus, activePhysics, tier, tolerance,
    currentIter, currentResidual, percentComplete, currentStatus,
    convergenceLog, resultSummary, error, adaptiveLog,
    cantileverParams, cantileverResult, cantileverLoading,
    setActivePhysics, setTier, setCantileverParam, setAdaptiveLog,
    startRun, cancelRun, runCantileverTest, resetRun, clearError,
  } = useSolverStore();

  const [mode, setMode] = useState('graph');   // 'graph' | 'cantilever'

  const isRunning = runStatus === 'running' || runStatus === 'queued';

  const handleStart = async () => {
    if (!activeGraphId) return;
    await startRun(activeGraphId);
  };

  const handleCantilever = async () => {
    await runCantileverTest(activeGraphId || 'test');
  };

  return (
    <Box sx={{
      width: 320, height: '100%', bgcolor: '#1a1a1a',
      borderLeft: '2px solid #2196f3', display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', px: 1.5, py: 1,
                 borderBottom: '1px solid #333', bgcolor: '#0d1b2a' }}>
        <Science sx={{ color: '#2196f3', mr: 1 }} />
        <Typography variant="subtitle2" sx={{ color: '#90caf9', flex: 1, fontWeight: 700 }}>
          Solver FEM
        </Typography>
        <Chip
          label={STATUS_LABEL[runStatus] || runStatus}
          size="small"
          color={STATUS_COLOR[runStatus] || 'default'}
          sx={{ mr: 1, height: 20, fontSize: 10 }}
        />
        {onClose && (
          <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}>
            <Close fontSize="small" />
          </IconButton>
        )}
      </Box>

      <Box sx={{ flex: 1, overflow: 'auto', p: 1.5, display: 'flex', flexDirection: 'column', gap: 1.5 }}>

        {/* Error */}
        {error && (
          <Alert severity="error" onClose={clearError} sx={{ fontSize: 12 }}>
            {error}
          </Alert>
        )}

        {/* Mode selector */}
        <ToggleButtonGroup
          value={mode} exclusive onChange={(_, v) => v && setMode(v)}
          size="small" fullWidth
        >
          <ToggleButton value="graph" sx={{ fontSize: 11 }}>
            Desde grafo
          </ToggleButton>
          <ToggleButton value="cantilever" sx={{ fontSize: 11 }}>
            Viga voladizo
          </ToggleButton>
        </ToggleButtonGroup>

        {/* ── Graph mode ───────────────────────────────────────────────── */}
        {mode === 'graph' && (
          <>
            <Accordion disableGutters sx={{ bgcolor: '#141414', border: '1px solid #333' }}>
              <AccordionSummary expandIcon={<ExpandMore sx={{ color: '#888', fontSize: 16 }} />}>
                <Typography variant="caption" sx={{ color: '#aaa', fontWeight: 600 }}>
                  Física y parámetros
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ p: 1.5, display: 'flex', flexDirection: 'column', gap: 1 }}>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                  {['structural', 'thermal', 'fluid', 'electromagnetic'].map(ph => (
                    <Chip
                      key={ph} label={ph} size="small"
                      onClick={() => {
                        const next = activePhysics.includes(ph)
                          ? activePhysics.filter(p => p !== ph)
                          : [...activePhysics, ph];
                        if (next.length > 0) setActivePhysics(next);
                      }}
                      sx={{
                        height: 22, fontSize: 10, cursor: 'pointer',
                        bgcolor: activePhysics.includes(ph) ? '#1565c0' : '#222',
                        color: activePhysics.includes(ph) ? '#90caf9' : '#666',
                        '&:hover': { bgcolor: activePhysics.includes(ph) ? '#1976d2' : '#333' },
                      }}
                    />
                  ))}
                </Box>

                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: '#888', fontSize: 12 }}>Tier de modelo</InputLabel>
                  <Select value={tier} onChange={e => setTier(e.target.value)}
                          label="Tier de modelo" sx={{ color: '#fff', fontSize: 12 }}>
                    {[[0,'Tier 0 — Nano (≤30K DOF)'],[1,'Tier 1 — Interactivo (≤600K DOF)'],
                       [2,'Tier 2 — Estándar (≤6M DOF)'],[3,'Tier 3 — HPC (≤60M DOF)']].map(([v,l]) => (
                      <MenuItem key={v} value={v} sx={{ fontSize: 12 }}>{l}</MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <TextField
                  label="Tolerancia" value={tolerance} size="small" fullWidth
                  inputProps={{ style: { color: '#fff', fontSize: 12 } }}
                  InputLabelProps={{ style: { color: '#888', fontSize: 12 } }}
                />
              </AccordionDetails>
            </Accordion>

            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant="contained" fullWidth
                startIcon={isRunning ? <Stop /> : <PlayArrow />}
                onClick={isRunning ? cancelRun : handleStart}
                disabled={!activeGraphId || runStatus === 'queued'}
                color={isRunning ? 'error' : 'primary'}
                sx={{ fontWeight: 700, flex: 1 }}
              >
                {isRunning ? 'Cancelar' : 'Simular'}
              </Button>
              <Tooltip title="FASE 3: Refinamiento adaptativo automático">
                <Button
                  variant="outlined" fullWidth
                  startIcon={<Warning sx={{ fontSize: 16 }} />}
                  onClick={async () => {
                    if (!activeGraphId) return;
                    try {
                      const resp = await fetch(`/api/design/solver/${activeGraphId}/run-adaptive/`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          physics: ['structural'],
                          max_cycles: 5,
                          target_error: 0.05,
                          refinement_fraction: 0.2,
                        }),
                      });
                      const data = await resp.json();
                      if (resp.ok && data.adaptive_log) {
                        setAdaptiveLog(data.adaptive_log);
                        alert(`✓ Adaptativo completado: ${data.adaptive_log.length} ciclos`);
                      } else {
                        alert(`Error: ${data.error || 'Error desconocido'}`);
                      }
                    } catch (e) {
                      alert(`Error: ${e.message}`);
                    }
                  }}
                  disabled={!activeGraphId || isRunning}
                  sx={{ fontWeight: 700, flex: 1, color: '#ff9800', borderColor: '#ff9800', fontSize: 11 }}
                >
                  h-Refinar
                </Button>
              </Tooltip>
            </Box>
          </>
        )}

        {/* ── Cantilever mode ──────────────────────────────────────────── */}
        {mode === 'cantilever' && (
          <>
            <Typography variant="caption" sx={{ color: '#888' }}>
              Viga voladizo (validación FASE 2) — compara con solución analítica Euler-Bernoulli
            </Typography>

            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
              {[
                ['length', 'Longitud [mm]'], ['width', 'Ancho [mm]'],
                ['height', 'Altura [mm]'],   ['E', 'Módulo E [GPa]'],
                ['nu', 'Poisson ν'],          ['force_y', 'Fuerza -Y [N]'],
                ['n_div', 'Divisiones'],
              ].map(([k, lbl]) => (
                <TextField
                  key={k} label={lbl} size="small"
                  type="number"
                  value={cantileverParams[k]}
                  onChange={e => setCantileverParam(k, parseFloat(e.target.value) || 0)}
                  inputProps={{ style: { color: '#fff', fontSize: 12 } }}
                  InputLabelProps={{ style: { color: '#888', fontSize: 11 } }}
                />
              ))}
            </Box>

            <Button
              variant="contained" fullWidth color="secondary"
              startIcon={cantileverLoading ? <CircularProgress size={16} color="inherit" /> : <Science />}
              onClick={handleCantilever}
              disabled={cantileverLoading}
              sx={{ fontWeight: 700 }}
            >
              {cantileverLoading ? 'Calculando...' : 'Correr validación'}
            </Button>

            {cantileverResult && <CantileverResult result={cantileverResult} />}
          </>
        )}

        {/* ── Progress ─────────────────────────────────────────────────── */}
        {(isRunning || runStatus === 'done') && mode === 'graph' && (
          <>
            <Divider sx={{ borderColor: '#333' }} />

            {isRunning && (
              <>
                <LinearProgress
                  variant={percentComplete > 0 ? 'determinate' : 'indeterminate'}
                  value={percentComplete}
                  sx={{ borderRadius: 1 }}
                />
                <Typography variant="caption" sx={{ color: '#aaa', fontSize: 10 }}>
                  {currentStatus || `Iter ${currentIter} | Residuo: ${currentResidual?.toExponential(2) ?? '—'}`}
                </Typography>
              </>
            )}

            {convergenceLog.length > 0 && (
              <ConvergenceMonitor log={convergenceLog} />
            )}

            {runStatus === 'done' && resultSummary && (
              <ResultSummary summary={resultSummary} />
            )}
          </>
        )}

        {/* ── Adaptive results ─────────────────────────────────────────────── */}
        {adaptiveLog && adaptiveLog.length > 0 && (
          <>
            <AdaptiveMonitor adaptiveLog={adaptiveLog} />
          </>
        )}
      </Box>

      {/* Reset */}
      {(runStatus === 'done' || runStatus === 'failed' || runStatus === 'cancelled') && (
        <Box sx={{ p: 1.5, borderTop: '1px solid #333' }}>
          <Button
            size="small" fullWidth startIcon={<Refresh />}
            onClick={resetRun} sx={{ color: '#888' }}
          >
            Nueva simulación
          </Button>
        </Box>
      )}
    </Box>
  );
}

function ResultSummary({ summary }) {
  const rows = [
    ['Despl. máx', `${summary.max_displacement_mm?.toFixed(4)} mm`],
    ['σ_vm máx', `${summary.max_von_mises_mpa?.toFixed(2)} MPa`],
    ['Nodos', summary.n_nodes?.toLocaleString()],
    ['Elementos', summary.n_elements?.toLocaleString()],
    ['Iter', summary.n_iterations],
    ['Tiempo', `${summary.wall_time_s?.toFixed(2)} s`],
  ];
  return (
    <Box sx={{ bgcolor: '#0d1b0d', border: '1px solid #2e7d32', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#81c784', fontWeight: 700, display: 'block', mb: 0.5 }}>
        ✓ Simulación completada
      </Typography>
      {rows.map(([lbl, val]) => (
        <Box key={lbl} sx={{ display: 'flex', justifyContent: 'space-between' }}>
          <Typography variant="caption" sx={{ color: '#888', fontSize: 10 }}>{lbl}</Typography>
          <Typography variant="caption" sx={{ color: '#a5d6a7', fontFamily: 'monospace', fontSize: 10 }}>{val}</Typography>
        </Box>
      ))}
    </Box>
  );
}

function CantileverResult({ result }) {
  const { fem, analytical, validation } = result;
  const pass = validation.pass_5pct;
  const color = pass ? '#2e7d32' : '#c62828';
  const bgColor = pass ? '#0d1b0d' : '#1b0d0d';
  const chipColor = pass ? '#81c784' : '#ef9a9a';

  return (
    <Box sx={{ bgcolor: bgColor, border: `1px solid ${color}`, borderRadius: 1, p: 1 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="caption" sx={{ color: chipColor, fontWeight: 700 }}>
          {pass ? '✓ Validación OK' : '⚠ Error > 5%'}
        </Typography>
        <Chip
          label={`Error: ${validation.relative_error_pct?.toFixed(2)}%`}
          size="small"
          sx={{ height: 18, fontSize: 9, bgcolor: pass ? '#1b5e20' : '#b71c1c', color: chipColor }}
        />
      </Box>

      {[
        ['FEM tip deflexión', `${fem.tip_deflection_mm?.toFixed(4)} mm`],
        ['Analítico (EB)', `${analytical.tip_deflection_mm?.toFixed(4)} mm`],
        ['FEM σ_vm máx', `${fem.max_von_mises_mpa?.toFixed(2)} MPa`],
        ['Nodos / Elem.', `${fem.n_nodes?.toLocaleString()} / ${fem.n_elements?.toLocaleString()}`],
        ['Solver', fem.solver],
        ['Tiempo', `${fem.wall_time_s?.toFixed(2)} s`],
      ].map(([l, v]) => (
        <Box key={l} sx={{ display: 'flex', justifyContent: 'space-between' }}>
          <Typography variant="caption" sx={{ color: '#888', fontSize: 10 }}>{l}</Typography>
          <Typography variant="caption" sx={{ color: chipColor, fontFamily: 'monospace', fontSize: 10 }}>{v}</Typography>
        </Box>
      ))}
    </Box>
  );
}
