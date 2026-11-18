import React, { useEffect, useMemo, useState } from 'react';
import {
  Box, Typography, LinearProgress, Chip, IconButton, List, ListItem,
  Collapse, Alert, Tooltip, Button, Stack,
} from '@mui/material';
import {
  CheckCircle, Error as ErrorIcon, Cancel, HourglassEmpty, Autorenew,
  ExpandMore, ExpandLess, Refresh, Science, StopCircle,
} from '@mui/icons-material';
import useJobStore, { TERMINAL } from '../stores/jobStore';

const STATUS = {
  queued:    { color: 'default', icon: <HourglassEmpty fontSize="small" />, label: 'En cola' },
  running:   { color: 'primary', icon: <Autorenew fontSize="small" />,      label: 'Corriendo' },
  done:      { color: 'success', icon: <CheckCircle fontSize="small" />,    label: 'Completado' },
  failed:    { color: 'error',   icon: <ErrorIcon fontSize="small" />,      label: 'Falló' },
  cancelled: { color: 'warning', icon: <Cancel fontSize="small" />,         label: 'Cancelado' },
};

const KIND_LABEL = {
  dummy: 'Prueba',
  'fem.solve': 'Solver FEM',
  'geometry.import': 'Importar geometría',
  'mesh.generate': 'Mallado',
};

function elapsed(job) {
  if (!job.started_at) return '';
  const end = job.finished_at ? new Date(job.finished_at) : new Date();
  const s = Math.max(0, (end - new Date(job.started_at)) / 1000);
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

function JobRow({ job }) {
  const cancel = useJobStore((s) => s.cancel);
  const fetchLog = useJobStore((s) => s.fetchLog);
  const [open, setOpen] = useState(false);
  const [log, setLog] = useState(null);
  const st = STATUS[job.status] || STATUS.queued;
  const active = !TERMINAL.includes(job.status);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next) {
      try { setLog(await fetchLog(job.id, 60)); } catch { setLog(['(log no disponible)']); }
    }
  };

  return (
    <ListItem disableGutters sx={{ display: 'block', borderBottom: 1, borderColor: 'divider', py: 1 }}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Chip size="small" icon={st.icon} label={st.label} color={st.color} variant="outlined" />
        <Typography variant="body2" sx={{ flex: 1 }} noWrap>
          {KIND_LABEL[job.kind] || job.kind}
        </Typography>
        <Typography variant="caption" color="text.secondary">{elapsed(job)}</Typography>
        {active && (
          <Tooltip title="Cancelar">
            <IconButton size="small" onClick={() => cancel(job.id)} disabled={job.cancel_requested}>
              <StopCircle fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
        <IconButton size="small" onClick={toggle}>{open ? <ExpandLess /> : <ExpandMore />}</IconButton>
      </Stack>
      {active && (
        <LinearProgress
          variant={job.status === 'queued' ? 'indeterminate' : 'determinate'}
          value={job.progress || 0}
          sx={{ mt: 0.75 }}
        />
      )}
      {job.message && (
        <Typography variant="caption" color="text.secondary" display="block" noWrap sx={{ mt: 0.5 }}>
          {job.message}{active && job.status === 'running' ? ` · ${Math.round(job.progress || 0)}%` : ''}
        </Typography>
      )}
      <Collapse in={open} unmountOnExit>
        {job.error && <Alert severity="error" sx={{ mt: 1, whiteSpace: 'pre-wrap', fontSize: 12 }}>{job.error.split('\n')[0]}</Alert>}
        <Box component="pre" sx={{ mt: 1, p: 1, bgcolor: 'background.default', fontSize: 11, maxHeight: 180, overflow: 'auto' }}>
          {(log || ['Cargando…']).join('\n') || '(vacío)'}
        </Box>
      </Collapse>
    </ListItem>
  );
}

/**
 * JobMonitor — trabajos de la cola PostgreSQL en tiempo real (socket.io `job_update`).
 */
export default function JobMonitor() {
  const { jobs, stats, error, init, refresh, enqueueDummy } = useJobStore();
  const list = useMemo(
    () => Object.values(jobs).sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')),
    [jobs],
  );

  useEffect(() => { init(); }, [init]);

  const queued = stats ? Object.values(stats.queues).reduce((n, q) => n + q.queued, 0) : 0;
  const noWorker = stats && queued > 0 && stats.busy_workers.length === 0;

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>Trabajos</Typography>
        <Tooltip title="Encolar un trabajo de prueba (dummy)">
          <Button size="small" startIcon={<Science />} onClick={() => enqueueDummy()}>Prueba</Button>
        </Tooltip>
        <IconButton size="small" onClick={refresh}><Refresh fontSize="small" /></IconButton>
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
      {noWorker && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          Hay trabajos en cola y ningún worker activo. Inicia uno con
          {' '}<code>python -m app.jobs.worker --queues default,solve</code>
        </Alert>
      )}
      {list.length === 0 ? (
        <Typography variant="body2" color="text.secondary">No hay trabajos.</Typography>
      ) : (
        <List dense disablePadding>
          {list.map((j) => <JobRow key={j.id} job={j} />)}
        </List>
      )}
    </Box>
  );
}
