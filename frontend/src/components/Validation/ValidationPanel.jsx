/**
 * ValidationPanel — FASE 8: continuous validation of the study.
 *   · confidence before simulating (similar correlated cases) + recommended tests / sensor positions
 *   · upload tests (ExperimentUpload), list them, correlate with the latest run, recalibrate
 *   · CorrelationView of the selected result
 */
import React, { useEffect, useState } from 'react';
import {
  Box, Typography, Button, Alert, Chip, IconButton, Tooltip, Divider, LinearProgress, Select, MenuItem,
} from '@mui/material';
import { Delete, CompareArrows, Tune, Visibility } from '@mui/icons-material';
import useValidationStore from '../../stores/validationStore';
import useDesignStore from '../../stores/designStore';
import ExperimentUpload from './ExperimentUpload';
import CorrelationView, { r2Color } from './CorrelationView';

const small = { fontSize: 10, minWidth: 0, px: 0.75, textTransform: 'none' };
const LEVEL_COLOR = { alta: '#66bb6a', media: '#ffb74d', baja: '#ef5350', 'sin historial': '#888' };

function ConfidenceCard({ confidence }) {
  if (!confidence) return null;
  if (confidence.error) return <Alert severity="info" sx={{ fontSize: 11, py: 0 }}>{confidence.error}</Alert>;
  const recs = confidence.recommendations || [];
  return (
    <Box sx={{ bgcolor: '#1a1a1a', p: 1, borderRadius: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
        <Typography sx={{ color: '#aaa', fontSize: 11 }}>Confianza del estudio</Typography>
        <Typography data-testid="confidence" sx={{ color: LEVEL_COLOR[confidence.level] || '#ccc', fontSize: 18, fontWeight: 700 }}>
          {Number(confidence.confidence_factor || 0).toFixed(2)}
        </Typography>
        <Chip size="small" label={confidence.level} sx={{ height: 16, fontSize: 10 }} />
      </Box>
      <Typography sx={{ color: '#777', fontSize: 10 }}>
        {confidence.similar_runs?.length
          ? `Basada en ${confidence.similar_runs.length} caso(s) similar(es) correlacionado(s) con ensayos.`
          : 'Ningún caso similar validado con ensayos todavía.'}
      </Typography>
      {confidence.similar_runs?.slice(0, 3).map((r) => (
        <Typography key={r.correlation_id} sx={{ color: '#999', fontSize: 10 }}>
          · similitud {Math.round(100 * r.similarity)} %{r.same_graph ? ' (este estudio)' : ''} — R²{' '}
          <span style={{ color: r2Color(r.r2) }}>{Number(r.r2).toFixed(3)}</span>
          {r.recalibrated ? ' · recalibrado' : ''}
        </Typography>
      ))}
      {recs.map((r) => (
        <Box key={`${r.test_type}-${r.priority}`} sx={{ mt: 0.5 }}>
          <Typography sx={{ color: '#4fc3f7', fontSize: 11 }}>{r.priority}. {r.title}</Typography>
          <Typography sx={{ color: '#888', fontSize: 10 }}>{r.reason}</Typography>
          {r.sensors?.map((s, i) => (
            <Typography key={i} sx={{ color: '#aaa', fontSize: 10, pl: 1 }}>
              {s.quantity} en ({s.x.toFixed(1)}, {s.y.toFixed(1)}, {s.z.toFixed(1)}) mm — {s.why}
              {s.expected != null ? `, esperado ≈ ${Number(s.expected).toPrecision(3)} ${s.unit}` : ''}
            </Typography>
          ))}
        </Box>
      ))}
    </Box>
  );
}

export default function ValidationPanel({ graphId }) {
  const {
    experiments, correlations, confidence, load, loadConfidence, correlate, recalibrate, remove, openCorrelation,
    view, busy, error, clearError,
  } = useValidationStore();
  const { graphData, loadGraph } = useDesignStore();
  const [mode, setMode] = useState('replace');
  const matNode = graphData.nodes.find((n) => n.data?.node_type === 'MATERIAL');
  const materialId = matNode?.data?.properties?.material_id || '';

  useEffect(() => {
    if (!graphId) return;
    load(graphId);
    loadConfidence(graphId);
  }, [graphId, load, loadConfidence]);

  if (!graphId) {
    return <Typography sx={{ color: '#888', fontSize: 12 }}>Abre un estudio para validarlo con ensayos.</Typography>;
  }

  const doRecal = async (exp, apply) => {
    const r = await recalibrate(graphId, exp, mode, apply);
    if (r && apply) loadGraph(graphId);                  // MATERIAL node changed
  };
  const lastCorr = (expId) => correlations.find((c) => c.experiment_id === expId);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
      <ConfidenceCard confidence={confidence} />
      {error && <Alert severity="error" onClose={clearError} sx={{ fontSize: 11 }}>{error}</Alert>}

      <Typography sx={{ color: '#ddd', fontSize: 12, fontWeight: 600 }}>Nuevo ensayo</Typography>
      <ExperimentUpload graphId={graphId} defaultMaterialId={materialId} />
      {busy && <LinearProgress />}

      <Divider sx={{ borderColor: '#333' }} />
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography sx={{ color: '#ddd', fontSize: 12, fontWeight: 600 }}>Ensayos ({experiments.length})</Typography>
        <Select size="small" value={mode} onChange={(e) => setMode(e.target.value)}
          sx={{ color: '#ccc', fontSize: 10, height: 22, '& .MuiSvgIcon-root': { color: '#888' } }}>
          <MenuItem value="replace" sx={{ fontSize: 11 }}>Recalibrar: reemplazar</MenuItem>
          <MenuItem value="bayes" sx={{ fontSize: 11 }}>Recalibrar: bayesiano</MenuItem>
        </Select>
      </Box>
      {experiments.length === 0 && (
        <Typography sx={{ color: '#777', fontSize: 11 }}>Sin ensayos en este estudio.</Typography>
      )}
      {experiments.map((e) => {
        const c = lastCorr(e.id);
        return (
          <Box key={e.id} data-testid="exp-row" sx={{ bgcolor: '#1e1e1e', p: 0.75, borderRadius: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Chip size="small" label={e.test_type === 'tensile' ? 'Tracción' : 'Pieza'}
                sx={{ height: 16, fontSize: 9, bgcolor: e.test_type === 'tensile' ? '#4a148c' : '#0d47a1', color: '#fff' }} />
              <Typography sx={{ color: '#ccc', fontSize: 11, flex: 1 }} noWrap>
                {e.description || e.file_ref?.split('/').pop() || e.id.slice(0, 8)}
              </Typography>
              {c && (
                <Tooltip title="Ver la última correlación">
                  <Typography onClick={() => openCorrelation(c.id)}
                    sx={{ color: r2Color(c.r2), fontSize: 11, cursor: 'pointer', fontWeight: 600 }}>
                    R² {Number(c.r2).toFixed(3)}
                  </Typography>
                </Tooltip>
              )}
              <Tooltip title="Eliminar ensayo">
                <IconButton size="small" onClick={() => remove(graphId, e.id)}><Delete sx={{ fontSize: 14, color: '#888' }} /></IconButton>
              </Tooltip>
            </Box>
            <Typography sx={{ color: '#777', fontSize: 10 }}>
              {e.test_type === 'tensile'
                ? `${e.scalar_summary?.label || ''} · E ${((e.scalar_summary?.E || 0) / 1e9).toFixed(1)} GPa · σ0.2 ${((e.scalar_summary?.sigma_y || 0) / 1e6).toFixed(0)} MPa`
                : `${e.scalar_summary?.n_sensors || 0} sensores`}
              {e.conditions?.temperature_c != null ? ` · ${e.conditions.temperature_c} °C` : ''}
              {e.created_at ? ` · ${e.created_at.slice(0, 10)}` : ''}
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5 }}>
              <Button size="small" sx={small} startIcon={<CompareArrows sx={{ fontSize: 14 }} />} disabled={busy}
                onClick={() => correlate(graphId, e.id)}>
                Correlacionar
              </Button>
              <Button size="small" sx={small} startIcon={<Visibility sx={{ fontSize: 14 }} />} disabled={busy}
                onClick={() => doRecal(e, false)}>
                Previsualizar
              </Button>
              <Button size="small" sx={small} variant="outlined" startIcon={<Tune sx={{ fontSize: 14 }} />} disabled={busy}
                onClick={() => doRecal(e, true)}>
                Recalibrar
              </Button>
            </Box>
          </Box>
        );
      })}

      {view && (
        <>
          <Divider sx={{ borderColor: '#333' }} />
          <CorrelationView view={view} />
        </>
      )}
    </Box>
  );
}
