/**
 * VersionDiffDialog — FASE 9: what changed in a version of the study with respect to its
 * previous version (GET /api/design/graph/<id>/diff).
 */
import React, { useEffect, useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography, Box, CircularProgress, Alert } from '@mui/material';
import axios from 'axios';

const val = (v) => (v === undefined || v === null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));

export default function VersionDiffDialog({ graph, onClose }) {
  const [diff, setDiff] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!graph) return;
    setDiff(null);
    setError(null);
    axios.get(`/api/design/graph/${graph.id}/diff`)
      .then((r) => setDiff(r.data))
      .catch((e) => setError(e.response?.data?.error || e.message));
  }, [graph]);
  if (!graph) return null;
  const empty = diff && !diff.nodes_added.length && !diff.nodes_removed.length && !diff.nodes_changed.length
    && !diff.edges_added.length && !diff.edges_removed.length;
  const line = (color, text, key) => <Typography key={key} sx={{ color, fontSize: 12, fontFamily: 'monospace' }}>{text}</Typography>;
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth PaperProps={{ sx: { bgcolor: '#1e1e1e', border: '1px solid #333' } }}>
      <DialogTitle sx={{ color: '#90caf9', fontSize: 15 }}>
        {graph.name}: cambios de v{graph.version}{diff ? ` respecto a v${diff.against_version}` : ''}
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {graph.version_note && <Typography sx={{ color: '#bbb', fontSize: 12, mb: 1 }}>Nota: {graph.version_note}</Typography>}
        {!diff && !error && <CircularProgress size={20} />}
        {error && <Alert severity="info" sx={{ fontSize: 12 }}>{error}</Alert>}
        {empty && <Typography sx={{ color: '#888', fontSize: 12 }}>Sin cambios en el grafo todavía.</Typography>}
        {diff && (
          <Box data-testid="version-diff">
            {diff.nodes_added.map((n) => line('#a5d6a7', `+ ${n.type} «${n.label}»`, `a${n.id}`))}
            {diff.nodes_removed.map((n) => line('#ef9a9a', `− ${n.type} «${n.label}»`, `r${n.id}`))}
            {diff.nodes_changed.map((n) => (
              <Box key={`c${n.id}`} sx={{ mb: 0.5 }}>
                {line('#ffe082', `~ ${n.type} «${n.label}»${n.old_label !== n.label ? ` (antes «${n.old_label}»)` : ''}`)}
                {Object.entries(n.properties).map(([k, [a, b]]) => line('#bbb', `    ${k}: ${val(a)} → ${val(b)}`, k))}
              </Box>
            ))}
            {diff.edges_added.map((e, i) => line('#a5d6a7', `+ ${e.source} —${e.type}→ ${e.target}`, `ea${i}`))}
            {diff.edges_removed.map((e, i) => line('#ef9a9a', `− ${e.source} —${e.type}→ ${e.target}`, `er${i}`))}
          </Box>
        )}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cerrar</Button></DialogActions>
    </Dialog>
  );
}
