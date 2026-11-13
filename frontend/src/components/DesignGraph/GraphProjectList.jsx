/**
 * GraphProjectList — left sidebar: projects as version trees (FASE 9, plan §9.1).
 *
 *   ▾ Bracket            3 versiones
 *     ├ v1  primera idea
 *     ├ v2  espesor 8 mm
 *     └ v3  (activa)
 *
 * Per version: changes vs the previous one, new version from it, delete.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Box, Typography, List, ListItem, ListItemButton, ListItemText,
  IconButton, Tooltip, Chip, Button, TextField, Dialog,
  DialogTitle, DialogContent, DialogActions, Select, MenuItem, FormControl, InputLabel,
  CircularProgress,
} from '@mui/material';
import {
  Add, Delete, Refresh, AccountTree, ExpandMore, ChevronRight, CallSplit, Difference,
} from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';
import { groupVersions } from './versionTree';
import VersionDiffDialog from './VersionDiffDialog';

const STATUS_COLOR = {
  draft: '#9e9e9e',
  simulating: '#2196f3',
  optimizing: '#9c27b0',
  validated: '#4caf50',
};

const TIER_LABEL = ['Nano', 'Interactivo', 'Estándar', 'HPC'];

export default function GraphProjectList() {
  const {
    graphs, graphsLoading, activeGraphId,
    fetchGraphs, loadGraph, createGraph, deleteGraph, createVersion,
  } = useDesignStore();
  const groups = useMemo(() => groupVersions(graphs), [graphs]);

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newTier, setNewTier] = useState(1);
  const [expanded, setExpanded] = useState({});
  const [versionOf, setVersionOf] = useState(null);
  const [versionNote, setVersionNote] = useState('');
  const [diffGraph, setDiffGraph] = useState(null);

  useEffect(() => { fetchGraphs(); }, [fetchGraphs]);

  const confirmDelete = async (g) => {
    if (!window.confirm(`¿Borrar «${g.name}» v${g.version}?`)) return;
    try {
      await deleteGraph(g.id);
    } catch (e) {
      const d = e.response?.data;
      if (e.response?.status === 409 && window.confirm(`${d.error}\n\n¿Borrar también todo su historial?`)) {
        await deleteGraph(g.id, true).catch((err) => window.alert(err.response?.data?.error || err.message));
      } else if (e.response?.status !== 409) {
        window.alert(d?.error || e.message);
      }
    }
    fetchGraphs();
  };

  const handleVersion = async () => {
    const src = versionOf;
    setVersionOf(null);
    try {
      await createVersion(src.id, versionNote.trim());
    } catch (e) {
      window.alert(e.response?.data?.error || e.message);
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    const g = await createGraph(newName.trim(), '', newTier);
    if (g) loadGraph(g.id);
    setCreating(false);
    setNewName('');
    setNewTier(1);
  };

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1.5, borderBottom: '1px solid #333' }}>
        <AccountTree sx={{ color: '#3f51b5', mr: 1, fontSize: 18 }} />
        <Typography variant="subtitle2" sx={{ color: '#90caf9', flex: 1 }}>
          Proyectos
        </Typography>
        <Tooltip title="Actualizar lista">
          <IconButton size="small" onClick={fetchGraphs} sx={{ color: '#888' }}>
            <Refresh fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      {/* New project button */}
      <Box sx={{ px: 2, py: 1, borderBottom: '1px solid #222' }}>
        <Button
          startIcon={<Add />} fullWidth size="small" variant="outlined"
          onClick={() => setCreating(true)}
          sx={{ borderColor: '#3f51b5', color: '#7986cb', fontSize: 12 }}
        >
          Nuevo proyecto
        </Button>
      </Box>

      {/* List: projects = version trees */}
      {graphsLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', pt: 4 }}>
          <CircularProgress size={24} />
        </Box>
      ) : (
        <List dense sx={{ flex: 1, overflow: 'auto', py: 0 }}>
          {graphs.length === 0 && (
            <ListItem>
              <Typography variant="caption" sx={{ color: '#555', textAlign: 'center', width: '100%' }}>
                No hay proyectos. Crea el primero.
              </Typography>
            </ListItem>
          )}
          {groups.map(({ root, versions, latest }) => {
            const multi = versions.length > 1;
            const open = multi && (expanded[root.id] ?? versions.some((v) => v.id === activeGraphId));
            return (
              <Box key={root.id} data-testid="project-group" sx={{ borderBottom: '1px solid #222' }}>
                {multi && (
                  <ListItemButton onClick={() => setExpanded((x) => ({ ...x, [root.id]: !open }))} sx={{ py: 0.5 }}>
                    {open ? <ExpandMore sx={{ fontSize: 16, color: '#888', mr: 0.5 }} />
                      : <ChevronRight sx={{ fontSize: 16, color: '#888', mr: 0.5 }} />}
                    <Typography sx={{ color: '#fff', fontSize: 13, flex: 1 }} noWrap>{latest.name}</Typography>
                    <Chip label={`${versions.length} versiones`} size="small"
                      sx={{ height: 16, fontSize: 9, bgcolor: '#2a2a3a', color: '#b39ddb' }} />
                  </ListItemButton>
                )}
                {(multi ? (open ? versions : []) : versions).map((g, i) => (
                  <VersionRow key={g.id} g={g} nested={multi} last={i === versions.length - 1}
                    active={g.id === activeGraphId} onOpen={() => loadGraph(g.id)}
                    onDelete={() => confirmDelete(g)} onDiff={() => setDiffGraph(g)}
                    onVersion={() => { setVersionOf(g); setVersionNote(''); }} />
                ))}
              </Box>
            );
          })}
        </List>
      )}

      {/* New version dialog */}
      <Dialog open={Boolean(versionOf)} onClose={() => setVersionOf(null)} maxWidth="xs" fullWidth
        PaperProps={{ sx: { bgcolor: '#1e1e1e', border: '1px solid #333' } }}>
        <DialogTitle sx={{ color: '#90caf9', fontSize: 15 }}>
          Nueva versión de «{versionOf?.name}» (desde v{versionOf?.version})
        </DialogTitle>
        <DialogContent sx={{ pt: '16px !important' }}>
          <Typography sx={{ color: '#999', fontSize: 12, mb: 1.5 }}>
            Se copia el grafo completo. Esta versión y sus simulaciones quedan intactas; la primera
            simulación de la nueva versión se compara con la última de esta.
          </Typography>
          <TextField label="¿Qué cambia en esta versión?" fullWidth size="small" autoFocus
            value={versionNote} onChange={(e) => setVersionNote(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleVersion()}
            inputProps={{ style: { color: '#fff' } }} InputLabelProps={{ style: { color: '#888' } }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVersionOf(null)} sx={{ color: '#888' }}>Cancelar</Button>
          <Button onClick={handleVersion} variant="contained">Crear versión</Button>
        </DialogActions>
      </Dialog>
      <VersionDiffDialog graph={diffGraph} onClose={() => setDiffGraph(null)} />

      {/* Create dialog */}
      <Dialog
        open={creating}
        onClose={() => setCreating(false)}
        maxWidth="xs" fullWidth
        PaperProps={{ sx: { bgcolor: '#1e1e1e', border: '1px solid #333' } }}
      >
        <DialogTitle sx={{ color: '#90caf9', fontSize: 15 }}>Nuevo proyecto de diseño</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '16px !important' }}>
          <TextField
            label="Nombre del proyecto" fullWidth size="small" autoFocus
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            inputProps={{ style: { color: '#fff' } }}
            InputLabelProps={{ style: { color: '#888' } }}
          />
          <FormControl size="small" fullWidth>
            <InputLabel sx={{ color: '#888' }}>Tier de modelo</InputLabel>
            <Select
              value={newTier}
              onChange={e => setNewTier(e.target.value)}
              label="Tier de modelo"
              sx={{ color: '#fff' }}
            >
              {[[0,'Tier 0 — Nano (≤ 5K nodos)'],
                 [1,'Tier 1 — Interactivo (≤ 100K nodos)'],
                 [2,'Tier 2 — Estándar (≤ 1M nodos)'],
                 [3,'Tier 3 — HPC local (≤ 10M nodos)']].map(([v,l]) => (
                <MenuItem key={v} value={v}>{l}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreating(false)} sx={{ color: '#888' }}>Cancelar</Button>
          <Button onClick={handleCreate} variant="contained" disabled={!newName.trim()}>
            Crear
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function VersionRow({ g, nested, last, active, onOpen, onDelete, onDiff, onVersion }) {
  const iconSx = { color: '#666', p: 0.25, '&:hover': { color: '#90caf9' } };
  return (
    <ListItem disablePadding data-testid="version-row"
      secondaryAction={
        <Box sx={{ display: 'flex' }}>
          {g.parent_id && (
            <Tooltip title="Cambios respecto a la versión anterior">
              <IconButton size="small" aria-label="cambios" onClick={(e) => { e.stopPropagation(); onDiff(); }} sx={iconSx}>
                <Difference sx={{ fontSize: 15 }} />
              </IconButton>
            </Tooltip>
          )}
          <Tooltip title="Nueva versión a partir de esta">
            <IconButton size="small" aria-label="nueva versión" onClick={(e) => { e.stopPropagation(); onVersion(); }} sx={iconSx}>
              <CallSplit sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="Eliminar">
            <IconButton size="small" aria-label="eliminar" onClick={(e) => { e.stopPropagation(); onDelete(); }}
              sx={{ ...iconSx, '&:hover': { color: '#f44336' } }}>
              <Delete sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
        </Box>
      }>
      <ListItemButton selected={active} onClick={onOpen} sx={{
        '&.Mui-selected': { bgcolor: '#1a237e33', borderLeft: '3px solid #3f51b5' },
        '&:hover': { bgcolor: '#1e1e2e' }, pl: nested ? 3 : 2, pr: 11,
      }}>
        <ListItemText
          primary={
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              {nested && <Typography sx={{ color: '#555', fontSize: 12, fontFamily: 'monospace' }}>{last ? '└' : '├'}</Typography>}
              <Typography variant="body2" sx={{ color: '#fff', fontSize: 13, flex: 1 }} noWrap>
                {nested ? `v${g.version}` : g.name}
              </Typography>
              <Chip label={TIER_LABEL[g.tier] || `T${g.tier}`} size="small"
                sx={{ height: 16, fontSize: 9, bgcolor: '#1e2a3a', color: '#90caf9' }} />
            </Box>
          }
          secondary={
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}>
              <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: STATUS_COLOR[g.status] || '#666' }} />
              <Typography variant="caption" sx={{ color: '#666', fontSize: 10 }} noWrap>
                {nested ? (g.version_note || g.status) : `${g.status} · v${g.version}`}
              </Typography>
            </Box>
          }
        />
      </ListItemButton>
    </ListItem>
  );
}
