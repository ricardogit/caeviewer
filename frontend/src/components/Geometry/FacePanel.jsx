import React from 'react';
import {
  Paper, Box, Typography, Chip, Divider, IconButton, Tooltip, Stack, Table, TableBody, TableRow, TableCell,
} from '@mui/material';
import { ContentCopy, Close } from '@mui/icons-material';
import useGeometryStore from '../../stores/geometryStore';

const MATCH = {
  exact: { label: 'idéntica', color: 'success' },
  tight: { label: 'emparejada', color: 'info' },
  loose: { label: 'emparejada (holgura)', color: 'warning' },
};

const fmt = (v, d = 3) => (v == null ? '—' : Number(v).toFixed(d));
const vec = (a, d = 3) => (a ? `(${a.map((x) => fmt(x, d)).join(', ')})` : '—');

function Row({ k, v }) {
  return (
    <TableRow>
      <TableCell sx={{ color: 'text.secondary', py: 0.4, pl: 0, border: 0, whiteSpace: 'nowrap' }}>{k}</TableCell>
      <TableCell sx={{ py: 0.4, pr: 0, border: 0, fontFamily: 'monospace', fontSize: 12 }}>{v}</TableCell>
    </TableRow>
  );
}

function FaceDetails({ face, parentIndex, hasParent }) {
  const m = MATCH[face.match_kind];
  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <Typography variant="subtitle1">Cara #{face.entity_index}</Typography>
        <Chip size="small" label={face.surface_type} variant="outlined" />
        {face.name && <Chip size="small" label={face.name} />}
      </Stack>
      <Stack direction="row" spacing={0.5} alignItems="center">
        <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }} noWrap>
          {face.id}
        </Typography>
        <Tooltip title="Copiar face_id (UUID persistente)">
          <IconButton size="small" onClick={() => navigator.clipboard?.writeText(face.id)}>
            <ContentCopy sx={{ fontSize: 14 }} />
          </IconButton>
        </Tooltip>
      </Stack>
      <Table size="small">
        <TableBody>
          <Row k="Área" v={`${fmt(face.measure, 3)} mm²`} />
          <Row k="Centroide" v={`${vec(face.centroid)} mm`} />
          <Row k="Normal" v={vec(face.normal, 4)} />
          {face.radius != null && <Row k="Radio" v={`${fmt(face.radius, 4)} mm`} />}
          <Row k="Sólido" v={face.solid_index ?? '—'} />
          <Row k="Firma" v={face.sig_hash?.slice(0, 16)} />
          {hasParent && (
            <Row
              k="Versión anterior"
              v={m ? <span>cara #{parentIndex} <Chip size="small" color={m.color} label={m.label} sx={{ ml: 0.5, height: 18 }} /></span>
                   : <Chip size="small" color="secondary" label="nueva" sx={{ height: 18 }} />}
            />
          )}
        </TableBody>
      </Table>
    </Box>
  );
}

export default function FacePanel() {
  const selected = useGeometryStore((s) => s.selected);
  const entities = useGeometryStore((s) => s.entities);
  const parentIndex = useGeometryStore((s) => s.parentIndex);
  const selectedFaces = useGeometryStore((s) => s.selectedFaces);
  const hoverFace = useGeometryStore((s) => s.hoverFace);
  const clearSelection = useGeometryStore((s) => s.clearSelection);

  if (!selected || selected.status !== 'ready') return null;
  const hasParent = Boolean(selected.parent_id);
  const faces = selectedFaces.map((i) => entities[i]).filter(Boolean);
  const totalArea = faces.reduce((a, f) => a + (f.measure || 0), 0);
  const hover = hoverFace != null && !selectedFaces.includes(hoverFace) ? entities[hoverFace] : null;

  return (
    <Paper
      elevation={4}
      sx={{ position: 'absolute', top: 16, right: 16, width: 360, maxHeight: 'calc(100% - 96px)', overflow: 'auto', p: 2, zIndex: 10 }}
    >
      <Typography variant="overline" color="text.secondary">
        {selected.name} · v{selected.version} · {selected.n_faces} caras
      </Typography>
      {faces.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Haz clic en una cara para ver su ID persistente y su firma geométrica.
        </Typography>
      ) : (
        <>
          <Stack direction="row" alignItems="center" sx={{ mt: 0.5 }}>
            <Typography variant="body2" sx={{ flex: 1 }}>
              {faces.length} cara{faces.length > 1 ? 's' : ''} seleccionada{faces.length > 1 ? 's' : ''}
              {faces.length > 1 && ` · área total ${totalArea.toFixed(2)} mm²`}
            </Typography>
            <Tooltip title="Limpiar selección"><IconButton size="small" onClick={clearSelection}><Close fontSize="small" /></IconButton></Tooltip>
          </Stack>
          {faces.length > 1 && (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, my: 1 }}>
              {faces.map((f) => <Chip key={f.entity_index} size="small" label={`#${f.entity_index}`} />)}
            </Box>
          )}
          <Divider sx={{ my: 1 }} />
          <FaceDetails face={faces[faces.length - 1]} parentIndex={parentIndex[faces[faces.length - 1].entity_index]} hasParent={hasParent} />
        </>
      )}
      {hover && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          Bajo el cursor: cara #{hover.entity_index} · {hover.surface_type} · {fmt(hover.measure, 2)} mm²
        </Typography>
      )}
    </Paper>
  );
}
