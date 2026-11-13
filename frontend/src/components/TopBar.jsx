import React, { useEffect, useState } from 'react';
import {
  AppBar, Toolbar, IconButton, Typography, Box, Badge, Popover, Chip, Tooltip, Button, Menu, MenuItem, Divider,
} from '@mui/material';
import {
  Menu as MenuIcon, PlayArrow, GridOn, ViewInAr, AccountTree, Category, Apps, Assessment, FactCheck, History,
  Download, Bolt,
} from '@mui/icons-material';
import JobMonitor from './JobMonitor';
import useJobStore, { selectActiveCount } from '../stores/jobStore';
import useDesignStore from '../stores/designStore';
import useSolverStore from '../stores/solverStore';
import useWorkspaceStore from '../stores/workspaceStore';

/**
 * TopBar — FASE 9 §9.2. Three sections:
 *   1. work mode: Design | Resultados | Geometría | STEP | CAE/FEA | Catálogo
 *   2. project context: study name · version · graph status · tier (estimated vs declared)
 *   3. contextual actions on the study: Validar · Simular · Historial · Exportar
 */
export const MODES = [
  { key: 'design', label: 'Design', Icon: AccountTree, color: '#7986cb' },
  { key: 'results', label: 'Resultados', Icon: Assessment, color: '#4db6ac' },
  { key: 'geometry', label: 'Geometría', Icon: Category, color: '#ffb74d' },
  { key: 'step', label: 'STEP', Icon: ViewInAr, color: '#90caf9' },
  { key: 'cae', label: 'CAE/FEA', Icon: GridOn, color: '#80cbc4' },
  { key: 'hub', label: 'Catálogo', Icon: Apps, color: '#ce93d8' },
];

const STATUS_COLOR = { draft: '#9e9e9e', simulating: '#2196f3', optimizing: '#9c27b0', validated: '#4caf50' };
const STATUS_LABEL = { draft: 'borrador', simulating: 'simulando', optimizing: 'optimizando', validated: 'validado' };
const actionSx = { color: '#ddd', fontSize: 12, textTransform: 'none', minWidth: 0, px: 1 };

function ProjectContext({ meta, preflight }) {
  if (!meta) {
    return <Typography sx={{ color: '#777', fontSize: 12 }}>Sin estudio abierto</Typography>;
  }
  const p = preflight && preflight.graph_id === meta.id ? preflight : null;
  const nErr = p ? (p.issues || []).filter((i) => i.severity === 'error').length : 0;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }} data-testid="project-context">
      <Typography sx={{ color: '#fff', fontSize: 13, fontWeight: 600 }} noWrap title={meta.name}>
        {meta.name}
      </Typography>
      <Typography sx={{ color: '#888', fontSize: 12 }}>v{meta.version}</Typography>
      <Chip size="small" label={STATUS_LABEL[meta.status] || meta.status}
        sx={{ height: 18, fontSize: 10, bgcolor: STATUS_COLOR[meta.status] || '#555', color: '#000' }} />
      {p && (
        <Tooltip title={p.ready ? 'Grafo completo para simular' : `${nErr} problema(s) en el grafo`}>
          <Chip size="small" label={p.ready ? '✓ listo' : `⚠ ${nErr}`}
            sx={{ height: 18, fontSize: 10, bgcolor: p.ready ? '#1b5e20' : '#7f0000', color: '#fff' }} />
        </Tooltip>
      )}
      {p?.tier_needed != null && (
        <Tooltip title={`Tier necesario ${p.tier_needed} (${p.size?.estimated ? 'estimado' : 'exacto'}: ${Number(p.size?.n_dof || 0).toLocaleString('es-MX')} DOF) · declarado ${p.tier_declared}`}>
          <Chip size="small" label={`Tier ${p.tier_needed}${p.tier_ok ? '' : ` > ${p.tier_declared}`}`}
            sx={{ height: 18, fontSize: 10, bgcolor: p.tier_ok ? '#263238' : '#e65100', color: '#fff' }} />
        </Tooltip>
      )}
    </Box>
  );
}

export default function TopBar({ onMenuClick, selectedFile, selectedMesh, onSetMode }) {
  const [jobsAnchor, setJobsAnchor] = useState(null);
  const [exportAnchor, setExportAnchor] = useState(null);
  const activeJobs = useJobStore(selectActiveCount);
  const initJobs = useJobStore((st) => st.init);
  useEffect(() => { initJobs(); }, [initJobs]);

  const { activeGraphId, activeGraphMeta, validateGraph } = useDesignStore();
  const { startRun, runStatus } = useSolverStore();
  const { appMode, preflight, openSolver, setHistoryOpen, setShowValidation, setAppMode, loadPreflight } = useWorkspaceStore();
  const setMode = onSetMode || setAppMode;
  const studyModes = appMode === 'design' || appMode === 'results';
  const meta = activeGraphMeta && activeGraphId ? { ...activeGraphMeta, id: activeGraphId } : null;
  const running = runStatus === 'queued' || runStatus === 'running';
  const latestRun = preflight?.graph_id === activeGraphId ? preflight?.latest_run : null;

  const onValidate = async () => {
    setMode('design');
    await validateGraph();
    setShowValidation(true);
    loadPreflight(activeGraphId);
  };
  const onSimulate = async () => {
    openSolver('graph');
    const v = await validateGraph();
    if (v && !v.ready_for_simulation) {
      setShowValidation(true);
      return;
    }
    await startRun(activeGraphId);
  };
  const onHistory = () => {
    openSolver('graph');
    setHistoryOpen(true);
  };
  const exportHref = (kind) => {
    if (kind === 'graph') return `/api/design/graph/${activeGraphId}/export/jsonld`;
    return `/api/design/solver/${latestRun?.run_id}/report?format=${kind}&download=1`;
  };

  return (
    <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar sx={{ gap: 1 }}>
        <IconButton color="inherit" edge="start" onClick={onMenuClick} sx={{ mr: 1 }}>
          <MenuIcon />
        </IconButton>
        <Typography variant="h6" noWrap component="div" sx={{ mr: 1.5 }}>CAE Lab</Typography>

        {/* 1. work mode */}
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          {MODES.map(({ key, label, Icon, color }) => {
            const active = appMode === key;
            const hasData = (key === 'step' && selectedFile) || (key === 'cae' && selectedMesh)
              || ((key === 'design' || key === 'results') && activeGraphId);
            return (
              <Box key={key} sx={{ position: 'relative' }}>
                <Chip
                  icon={<Icon sx={{ fontSize: 14, color: active ? '#000' : color }} />}
                  label={label} size="small" onClick={() => setMode(key)}
                  sx={{
                    cursor: 'pointer', bgcolor: active ? color : 'transparent', color: active ? '#000' : color,
                    border: '1px solid', borderColor: color, fontWeight: active ? 700 : 400,
                    '& .MuiChip-icon': { ml: 0.5 },
                  }}
                />
                {hasData && (
                  <Box sx={{ position: 'absolute', top: -4, right: -4, width: 9, height: 9, borderRadius: '50%',
                    bgcolor: color, border: '2px solid #121212' }} />
                )}
              </Box>
            );
          })}
        </Box>

        <Divider orientation="vertical" flexItem sx={{ borderColor: '#444', mx: 1 }} />

        {/* 2. project context */}
        <Box sx={{ minWidth: 0, flex: 1, display: 'flex', alignItems: 'center' }}>
          {studyModes ? <ProjectContext meta={meta} preflight={preflight} /> : (
            <Box sx={{ display: 'flex', flexDirection: 'column' }}>
              {selectedFile && (appMode === 'step' || appMode === 'cae') && (
                <Typography noWrap sx={{ maxWidth: 300, color: '#aaa', fontSize: 12 }}>{selectedFile.original_filename}</Typography>
              )}
              {selectedMesh && appMode === 'cae' && (
                <Typography noWrap sx={{ maxWidth: 300, color: '#90caf9', fontSize: 12 }}>
                  Mesh: {selectedMesh.name || selectedMesh.id?.substring(0, 8)}
                </Typography>
              )}
            </Box>
          )}
        </Box>

        {/* 3. contextual actions on the study */}
        {studyModes && (
          <Box sx={{ display: 'flex', gap: 0.25 }}>
            <Button size="small" sx={actionSx} startIcon={<FactCheck sx={{ fontSize: 16 }} />} disabled={!activeGraphId}
              onClick={onValidate}>Validar</Button>
            <Button size="small" sx={{ ...actionSx, color: '#90caf9' }} startIcon={<Bolt sx={{ fontSize: 16 }} />}
              disabled={!activeGraphId || running} onClick={onSimulate}>
              {running ? 'Simulando…' : 'Simular'}
            </Button>
            <Button size="small" sx={actionSx} startIcon={<History sx={{ fontSize: 16 }} />} disabled={!activeGraphId}
              onClick={onHistory}>Historial</Button>
            <Button size="small" sx={actionSx} startIcon={<Download sx={{ fontSize: 16 }} />} disabled={!activeGraphId}
              onClick={(e) => setExportAnchor(e.currentTarget)}>Exportar</Button>
            <Menu anchorEl={exportAnchor} open={Boolean(exportAnchor)} onClose={() => setExportAnchor(null)}>
              <MenuItem component="a" href={exportHref('markdown')} disabled={!latestRun} onClick={() => setExportAnchor(null)}
                sx={{ fontSize: 13 }}>Informe de la última simulación (Markdown)</MenuItem>
              <MenuItem component="a" href={exportHref('jsonld')} disabled={!latestRun} onClick={() => setExportAnchor(null)}
                sx={{ fontSize: 13 }}>Informe de la última simulación (JSON-LD)</MenuItem>
              <MenuItem component="a" href={exportHref('graph')} target="_blank" onClick={() => setExportAnchor(null)}
                sx={{ fontSize: 13 }}>Grafo del estudio (JSON-LD)</MenuItem>
            </Menu>
          </Box>
        )}

        {/* Job Monitor */}
        <Tooltip title="Trabajos en cola">
          <IconButton color="inherit" onClick={(e) => setJobsAnchor(e.currentTarget)}>
            <Badge badgeContent={activeJobs} color="secondary"><PlayArrow /></Badge>
          </IconButton>
        </Tooltip>
        <Popover open={Boolean(jobsAnchor)} anchorEl={jobsAnchor} onClose={() => setJobsAnchor(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
          <Box sx={{ width: 400, maxHeight: 500, overflow: 'auto', p: 2 }}><JobMonitor /></Box>
        </Popover>
      </Toolbar>
    </AppBar>
  );
}
