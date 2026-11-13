/**
 * ResultsRunList — FASE 9 left panel of the Results mode: the study (graph) and its runs with fields.
 */
import React, { useEffect } from 'react';
import {
  Box, Typography, List, ListItemButton, Chip, IconButton, Tooltip, FormControl, Select, MenuItem,
  CircularProgress,
} from '@mui/material';
import { Refresh, Assessment } from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';
import useResultsStore from '../../stores/resultsStore';

const STATUS = {
  done: ['Terminado', '#66bb6a'], failed: ['Error', '#ef5350'], running: ['Calculando', '#42a5f5'],
  queued: ['En cola', '#90a4ae'], cancelled: ['Cancelado', '#888'],
};
const PURPOSE = { run: 'Simulación', reproduce: 'Reproducción', adaptive: 'Adaptativa' };

export default function ResultsRunList() {
  const { graphs, activeGraphId, fetchGraphs, loadGraph } = useDesignStore();
  const { runs, runsLoading, listRuns, runId, open } = useResultsStore();

  useEffect(() => { if (!graphs?.length) fetchGraphs(); }, [graphs, fetchGraphs]);
  useEffect(() => { listRuns(activeGraphId); }, [activeGraphId, listRuns]);
  // open the newest finished run when nothing is selected for this study
  useEffect(() => {
    if (runId && runs.some((r) => r.run_id === runId)) return;
    const first = runs.find((r) => r.status === 'done');
    if (first) open(first.run_id);
  }, [runs, runId, open]);

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1.5, borderBottom: '1px solid #333' }}>
        <Assessment sx={{ color: '#4db6ac', mr: 1, fontSize: 18 }} />
        <Typography variant="subtitle2" sx={{ color: '#80cbc4', flex: 1 }}>Resultados</Typography>
        <Tooltip title="Actualizar">
          <IconButton size="small" onClick={() => listRuns(activeGraphId)} sx={{ color: '#888' }}>
            <Refresh fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
      <Box sx={{ p: 1.5 }}>
        <FormControl size="small" fullWidth>
          <Select value={activeGraphId || ''} displayEmpty onChange={(e) => loadGraph(e.target.value)}
            sx={{ color: '#fff', fontSize: 12 }} inputProps={{ 'data-testid': 'results-graph' }}>
            <MenuItem value="" disabled sx={{ fontSize: 12 }}>Elige un estudio</MenuItem>
            {(graphs || []).map((g) => (
              <MenuItem key={g.id} value={g.id} sx={{ fontSize: 12 }}>{g.name} (v{g.version})</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>
      {runsLoading && <CircularProgress size={18} sx={{ mx: 'auto' }} />}
      {!runsLoading && activeGraphId && runs.length === 0 && (
        <Typography sx={{ color: '#777', fontSize: 12, px: 2 }}>
          Este estudio no tiene simulaciones todavía. Lánzala desde Design → Simular.
        </Typography>
      )}
      <List dense sx={{ flex: 1, overflow: 'auto', py: 0 }}>
        {runs.map((r) => {
          const [lbl, color] = STATUS[r.status] || [r.status, '#888'];
          return (
            <ListItemButton key={r.run_id} selected={r.run_id === runId} disabled={r.status !== 'done'}
              onClick={() => open(r.run_id)} data-testid="run-item"
              sx={{ flexDirection: 'column', alignItems: 'stretch', borderBottom: '1px solid #262626' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                <Typography sx={{ color: '#ddd', fontSize: 12, fontFamily: 'monospace' }}>{r.run_id.slice(0, 8)}</Typography>
                <Typography sx={{ color: '#888', fontSize: 11, flex: 1 }}>{PURPOSE[r.purpose] || r.purpose}</Typography>
                <Chip size="small" label={lbl} sx={{ height: 16, fontSize: 9, bgcolor: color, color: '#000' }} />
              </Box>
              <Typography sx={{ color: '#888', fontSize: 10 }}>
                {r.created_at?.slice(0, 16).replace('T', ' ')}
                {r.max_displacement_mm != null ? ` · u ${Number(r.max_displacement_mm).toPrecision(3)} mm` : ''}
                {r.max_von_mises_mpa != null ? ` · σ ${Number(r.max_von_mises_mpa).toPrecision(3)} MPa` : ''}
                {r.element_type ? ` · ${r.element_type}` : ''}
              </Typography>
            </ListItemButton>
          );
        })}
      </List>
    </Box>
  );
}
