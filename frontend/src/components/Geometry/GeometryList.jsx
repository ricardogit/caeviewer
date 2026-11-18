import React, { useEffect, useRef } from 'react';
import {
  Box, Button, List, ListItemButton, ListItemText, Typography, Chip, LinearProgress, Alert, Stack,
  Tooltip, IconButton,
} from '@mui/material';
import { UploadFile, Refresh, LibraryAdd, Replay } from '@mui/icons-material';
import useGeometryStore from '../../stores/geometryStore';
import useJobStore from '../../stores/jobStore';

const STATUS_COLOR = { pending: 'default', processing: 'primary', ready: 'success', failed: 'error' };
const STATUS_LABEL = { pending: 'en cola', processing: 'importando', ready: 'lista', failed: 'falló' };
const ACCEPT = '.stp,.step,.p21';

export default function GeometryList() {
  const {
    geometries, versions, selected, uploading, error, init, fetchList, upload, select, reimport,
  } = useGeometryStore();
  const jobs = useJobStore((s) => s.jobs);
  const initJobs = useJobStore((s) => s.init);
  const fileRef = useRef();
  const versionRef = useRef();

  useEffect(() => { init(); initJobs(); }, [init, initJobs]);

  const lineageVersions = selected ? versions[selected.lineage_id] || [] : [];

  return (
    <Box sx={{ p: 1.5 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>Geometrías</Typography>
        <IconButton size="small" onClick={fetchList}><Refresh fontSize="small" /></IconButton>
      </Stack>
      <Button fullWidth variant="contained" startIcon={<UploadFile />} disabled={uploading}
        onClick={() => fileRef.current?.click()}>
        {uploading ? 'Subiendo…' : 'Subir STEP'}
      </Button>
      <input ref={fileRef} type="file" accept={ACCEPT} hidden
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) upload(f); }} />
      <input ref={versionRef} type="file" accept={ACCEPT} hidden
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f && selected) upload(f, selected.id); }} />
      {uploading && <LinearProgress sx={{ mt: 1 }} />}
      {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}

      <List dense sx={{ mt: 1 }}>
        {geometries.map((g) => {
          const job = g.import_job_id ? jobs[g.import_job_id] : null;
          const active = ['pending', 'processing'].includes(g.status);
          const isSel = selected?.lineage_id === g.lineage_id;
          return (
            <Box key={g.id}>
              <ListItemButton selected={isSel} onClick={() => select(g)} sx={{ borderRadius: 1 }}>
                <ListItemText
                  primary={<Stack direction="row" spacing={0.5} alignItems="center">
                    <Typography variant="body2" noWrap sx={{ flex: 1 }}>{g.name}</Typography>
                    <Chip size="small" label={`v${g.version}`} sx={{ height: 18 }} />
                  </Stack>}
                  secondary={<Stack direction="row" spacing={0.5} alignItems="center" component="span">
                    <Chip size="small" color={STATUS_COLOR[g.status]} label={STATUS_LABEL[g.status]}
                      sx={{ height: 18 }} component="span" />
                    {g.n_faces != null && <span>{g.n_faces} caras</span>}
                  </Stack>}
                  secondaryTypographyProps={{ component: 'div', variant: 'caption' }}
                />
              </ListItemButton>
              {active && <LinearProgress variant={job?.progress ? 'determinate' : 'indeterminate'}
                value={job?.progress || 0} sx={{ mx: 2, mb: 0.5 }} />}
              {active && job?.message && (
                <Typography variant="caption" color="text.secondary" sx={{ px: 2 }} display="block" noWrap>
                  {job.message}
                </Typography>
              )}
            </Box>
          );
        })}
        {geometries.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ px: 1 }}>No hay geometrías todavía.</Typography>
        )}
      </List>

      {selected && (
        <Box sx={{ mt: 1, p: 1, border: 1, borderColor: 'divider', borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">Versiones de «{selected.name}»</Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, my: 0.5 }}>
            {lineageVersions.map((v) => (
              <Chip key={v.id} size="small" label={`v${v.version}`} color={v.id === selected.id ? 'primary' : 'default'}
                onClick={() => select(v)} />
            ))}
          </Box>
          <Stack direction="row" spacing={1} sx={{ '& .MuiButton-root': { whiteSpace: 'nowrap' } }}>
            <Button size="small" startIcon={<LibraryAdd />} onClick={() => versionRef.current?.click()}>
              Nueva versión
            </Button>
            <Tooltip title="Reimportar (comprueba que los IDs de cara se conservan)">
              <span>
                <Button size="small" startIcon={<Replay />} onClick={() => reimport(selected.id)}
                  disabled={['pending', 'processing'].includes(selected.status)}>
                  Reimportar
                </Button>
              </span>
            </Tooltip>
          </Stack>
          {selected.meta?.digest_changed_on_reimport && (
            <Alert severity="warning" sx={{ mt: 1 }}>La firma cambió al reimportar: los IDs de cara podrían no coincidir.</Alert>
          )}
          {selected.meta?.remap_warning && (
            <Alert severity="warning" sx={{ mt: 1 }}>{selected.meta.remap_warning}. Reimporte esta versión cuando la anterior esté lista.</Alert>
          )}
          {selected.meta?.remap?.parent_version != null && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              Respecto a v{selected.meta.remap.parent_version}: {selected.meta.remap.matched_exact} idénticas,
              {' '}{selected.meta.remap.matched_tight + selected.meta.remap.matched_loose} emparejadas,
              {' '}{selected.meta.remap.new_faces?.length ?? 0} nuevas,
              {' '}{selected.meta.remap.removed_parent_faces?.length ?? 0} eliminadas
            </Typography>
          )}
        </Box>
      )}
    </Box>
  );
}
