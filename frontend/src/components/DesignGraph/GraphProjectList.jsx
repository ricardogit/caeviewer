/**
 * GraphProjectList — left sidebar listing all design graphs (projects).
 */
import React, { useEffect, useState } from 'react';
import {
  Box, Typography, List, ListItem, ListItemButton, ListItemText,
  IconButton, Tooltip, Chip, Button, TextField, Dialog,
  DialogTitle, DialogContent, DialogActions, Select, MenuItem, FormControl, InputLabel,
  CircularProgress,
} from '@mui/material';
import { Add, Delete, Refresh, AccountTree } from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';

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
    fetchGraphs, loadGraph, createGraph, deleteGraph,
  } = useDesignStore();

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newTier, setNewTier] = useState(1);

  useEffect(() => { fetchGraphs(); }, []);

  const confirmDelete = async (g) => {
    if (!window.confirm(`¿Borrar el estudio «${g.name}»?`)) return;
    try {
      await deleteGraph(g.id);
    } catch (e) {
      const d = e.response?.data;
      if (e.response?.status === 409 && window.confirm(`${d.error}

¿Borrar también todo su historial?`)) {
        await deleteGraph(g.id, true).catch((err) => window.alert(err.response?.data?.error || err.message));
      } else if (e.response?.status !== 409) {
        window.alert(d?.error || e.message);
      }
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
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1.5,
                 borderBottom: '1px solid #333' }}>
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

      {/* List */}
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
          {graphs.map(g => (
            <ListItem
              key={g.id}
              disablePadding
              secondaryAction={
                <Tooltip title="Eliminar proyecto">
                  <IconButton
                    edge="end" size="small"
                    onClick={e => { e.stopPropagation(); confirmDelete(g); }}
                    sx={{ color: '#555', '&:hover': { color: '#f44336' } }}
                  >
                    <Delete fontSize="small" />
                  </IconButton>
                </Tooltip>
              }
            >
              <ListItemButton
                selected={g.id === activeGraphId}
                onClick={() => loadGraph(g.id)}
                sx={{
                  '&.Mui-selected': { bgcolor: '#1a237e33', borderLeft: '3px solid #3f51b5' },
                  '&:hover': { bgcolor: '#1e1e2e' },
                  pl: g.id === activeGraphId ? 1.25 : 2,
                }}
              >
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <Typography variant="body2" sx={{ color: '#fff', fontSize: 13, flex: 1 }}
                                  noWrap>
                        {g.name}
                      </Typography>
                      <Chip
                        label={TIER_LABEL[g.tier] || `T${g.tier}`}
                        size="small"
                        sx={{ height: 16, fontSize: 9, bgcolor: '#1e2a3a', color: '#90caf9' }}
                      />
                    </Box>
                  }
                  secondary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}>
                      <Box sx={{ width: 6, height: 6, borderRadius: '50%',
                                 bgcolor: STATUS_COLOR[g.status] || '#666' }} />
                      <Typography variant="caption" sx={{ color: '#666', fontSize: 10 }}>
                        {g.status} · v{g.version}
                      </Typography>
                    </Box>
                  }
                />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}

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
