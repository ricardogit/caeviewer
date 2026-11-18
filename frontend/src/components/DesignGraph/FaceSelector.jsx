/**
 * FaceSelector — BC/LOAD nodes reference CAD faces by persistent UUID (FASE 2).
 *
 * The study geometry is the ``geometry_id`` of the graph's GEOMETRY node. Stored
 * ``entity_ids`` may belong to another version of the part; the backend resolves
 * them along the version remap (``POST /api/geometry/<id>/resolve``). Picking reuses
 * the Geometría viewer (``_FACE_ID`` per vertex) inside a dialog; on accept the
 * selection is saved as UUIDs of the study version.
 */
import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Typography,
} from '@mui/material';
import { AdsClick } from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';
import useGeometryStore from '../../stores/geometryStore';
import GeometryViewer from '../Geometry/GeometryViewer';

const fmtArea = (v) => (v == null ? '—' : `${Number(v).toFixed(v < 10 ? 2 : 0)} mm²`);

/** geometry_id of the study (first GEOMETRY node that has one). */
export function useStudyGeometryId() {
  const nodes = useDesignStore((s) => s.graphData.nodes);
  return useMemo(() => {
    const g = nodes.find((n) => n.data?.node_type === 'GEOMETRY' && n.data?.properties?.geometry_id);
    return g?.data.properties.geometry_id || null;
  }, [nodes]);
}

function useResolvedFaces(geometryId, entityIds) {
  const [state, setState] = useState({ faces: [], missing: 0, carried: 0, loading: false, error: null });
  const key = (entityIds || []).join(',');
  useEffect(() => {
    if (!geometryId || !entityIds?.length) {
      setState({ faces: [], missing: 0, carried: 0, loading: false, error: null });
      return undefined;
    }
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    Promise.all([
      axios.post(`/api/geometry/${geometryId}/resolve`, { entity_ids: entityIds }),
      axios.get(`/api/geometry/${geometryId}/entities`, { params: { type: 'face' } }),
    ]).then(([{ data: r }, { data: e }]) => {
      if (!alive) return;
      const byIndex = {};
      e.entities.forEach((x) => { byIndex[x.entity_index] = x; });
      const vals = Object.values(r.faces);
      setState({
        faces: vals.filter((v) => v.index != null).map((v) => ({ ...byIndex[v.index], status: v.status })),
        missing: vals.filter((v) => v.index == null).length,
        carried: vals.filter((v) => v.status === 'carried').length,
        loading: false, error: null,
      });
    }).catch((err) => alive && setState({ faces: [], missing: 0, carried: 0, loading: false,
      error: err.response?.data?.error || err.message }));
    return () => { alive = false; };
  }, [geometryId, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

function FacePickerDialog({ open, geometryId, initialIndices, onClose, onAccept }) {
  const selectedFaces = useGeometryStore((s) => s.selectedFaces);
  const entities = useGeometryStore((s) => s.entities);
  const [prev, setPrev] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open || !geometryId) return undefined;
    let alive = true;
    const store = useGeometryStore.getState();
    setPrev(store.selected);
    setError(null);
    axios.get(`/api/geometry/${geometryId}`)
      .then(async ({ data }) => {
        if (!alive) return;
        await useGeometryStore.getState().select(data);
        useGeometryStore.setState({ selectedFaces: [...initialIndices] });
      })
      .catch((e) => setError(e.response?.data?.error || e.message));
    return () => { alive = false; };
  }, [open, geometryId]); // eslint-disable-line react-hooks/exhaustive-deps

  const close = (accept) => {
    if (accept) onAccept(selectedFaces.map((i) => entities[i]?.id).filter(Boolean));
    // restore whatever the Geometría mode had selected
    if (prev && prev.id !== geometryId) useGeometryStore.getState().select(prev);
    onClose();
  };

  const area = selectedFaces.reduce((a, i) => a + (entities[i]?.measure || 0), 0);
  return (
    <Dialog open={open} onClose={() => close(false)} maxWidth="lg" fullWidth>
      <DialogTitle>Seleccionar caras</DialogTitle>
      <DialogContent sx={{ height: '70vh', p: 0, position: 'relative' }}>
        {error ? <Alert severity="error" sx={{ m: 2 }}>{error}</Alert> : open && <GeometryViewer />}
      </DialogContent>
      <DialogActions>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1, pl: 2 }}>
          {selectedFaces.length} cara(s) · {fmtArea(area)}
        </Typography>
        <Button onClick={() => close(false)}>Cancelar</Button>
        <Button variant="contained" onClick={() => close(true)}>Usar selección</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function FaceSelector({ entityIds, onChange, required }) {
  const geometryId = useStudyGeometryId();
  const { faces, missing, carried, loading, error } = useResolvedFaces(geometryId, entityIds);
  const [open, setOpen] = useState(false);
  const total = faces.reduce((a, f) => a + (f.measure || 0), 0);

  if (!geometryId) {
    return (
      <Alert severity="info" sx={{ fontSize: 12 }}>
        Asigna una geometría CAD al nodo GEOMETRY para aplicar esto sobre caras.
      </Alert>
    );
  }
  return (
    <Box>
      <Typography variant="caption" sx={{ color: '#888', display: 'block', mb: 0.5 }}>
        Caras de aplicación{required ? ' (requerido)' : ''}
      </Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 0.75 }}>
        {faces.map((f) => (
          <Chip key={f.id} size="small" variant="outlined"
            color={f.status === 'carried' ? 'warning' : 'default'}
            label={`#${f.entity_index} · ${f.surface_type} · ${fmtArea(f.measure)}`}
            onDelete={() => onChange((entityIds || []).filter((id) => id !== f.id))} />
        ))}
        {!faces.length && !loading && (
          <Typography variant="caption" sx={{ color: '#666' }}>Ninguna cara seleccionada</Typography>
        )}
      </Box>
      {faces.length > 1 && (
        <Typography variant="caption" sx={{ color: '#888', display: 'block' }}>Área total {fmtArea(total)}</Typography>
      )}
      {missing > 0 && (
        <Alert severity="error" sx={{ fontSize: 12, my: 0.5 }}>
          {missing} cara(s) ya no existen en esta versión de la geometría. Vuelve a seleccionarlas.
        </Alert>
      )}
      {carried > 0 && (
        <Alert severity="warning" sx={{ fontSize: 12, my: 0.5 }}>
          {carried} cara(s) trasladadas desde otra versión. Revísalas y guarda para fijarlas.
        </Alert>
      )}
      {error && <Alert severity="error" sx={{ fontSize: 12, my: 0.5 }}>{error}</Alert>}
      <Button size="small" variant="outlined" startIcon={<AdsClick />} fullWidth onClick={() => setOpen(true)}>
        Seleccionar caras en 3D
      </Button>
      <FacePickerDialog
        open={open}
        geometryId={geometryId}
        initialIndices={faces.map((f) => f.entity_index)}
        onClose={() => setOpen(false)}
        onAccept={(ids) => onChange(ids)}
      />
    </Box>
  );
}
