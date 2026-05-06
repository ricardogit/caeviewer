import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, Slider, Select, MenuItem, FormControl, InputLabel,
  Typography, Box, CircularProgress, Alert, Chip, Divider,
} from '@mui/material';
import { CheckCircle, Hub } from '@mui/icons-material';
import axios from 'axios';

const ALGORITHMS = [
  { value: 'hxt',      label: 'HXT — más rápido (paralelo)' },
  { value: 'delaunay', label: 'Delaunay — robusto' },
  { value: 'frontal',  label: 'Frontal — mayor calidad, lento' },
];

const REFINEMENT_LABELS = ['', 'Muy gruesa', 'Gruesa', 'Media', 'Fina', 'Muy fina'];

// Rough element-count estimates for the refinement level (per unit of complexity)
const REFINEMENT_HINT = [
  '', '~1k–5k elem.', '~5k–20k elem.', '~20k–100k elem.',
  '~100k–500k elem.', '~500k+ elem. (lento)',
];

export default function MeshFromStepDialog({ open, onClose, stepFile, onMeshCreated }) {
  const [refinement, setRefinement] = useState(3);
  const [algorithm,  setAlgorithm]  = useState('hxt');
  const [optimize,   setOptimize]   = useState(true);
  const [loading,    setLoading]    = useState(false);
  const [result,     setResult]     = useState(null);   // success payload
  const [error,      setError]      = useState(null);

  const reset = () => { setResult(null); setError(null); setLoading(false); };

  const handleClose = () => { reset(); onClose(); };

  const handleGenerate = async () => {
    if (!stepFile?.id) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await axios.post('/api/cae/meshes/from-step', {
        part_id:   stepFile.id,
        refinement,
        algorithm,
        optimize,
      });
      setResult(res.data);
    } catch (e) {
      setError(e.response?.data?.error || 'Error al generar la malla');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenInCAE = () => {
    if (result) {
      onMeshCreated({
        id:                result.mesh_id,
        original_filename: result.original_filename,
        node_count:        result.node_count,
        element_count:     result.element_count,
      });
    }
    handleClose();
  };

  return (
    <Dialog open={open} onClose={loading ? undefined : handleClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Hub fontSize="small" color="info" />
        Generar Malla FEA
      </DialogTitle>

      <DialogContent>
        {stepFile && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
            Origen: <strong>{stepFile.original_filename || stepFile.name}</strong>
          </Typography>
        )}

        {/* Refinement slider */}
        <Typography variant="body2" gutterBottom>
          Fineza de malla: <strong>{REFINEMENT_LABELS[refinement]}</strong>
        </Typography>
        <Slider
          value={refinement}
          onChange={(_, v) => setRefinement(v)}
          min={1} max={5} step={1}
          marks={[1,2,3,4,5].map(v => ({ value: v, label: String(v) }))}
          disabled={loading}
          sx={{ mb: 0.5 }}
        />
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
          {REFINEMENT_HINT[refinement]}
        </Typography>

        {/* Algorithm */}
        <FormControl fullWidth size="small" sx={{ mb: 2 }} disabled={loading}>
          <InputLabel>Algoritmo</InputLabel>
          <Select value={algorithm} onChange={e => setAlgorithm(e.target.value)} label="Algoritmo">
            {ALGORITHMS.map(a => (
              <MenuItem key={a.value} value={a.value}>{a.label}</MenuItem>
            ))}
          </Select>
        </FormControl>

        <Divider sx={{ mb: 2 }} />

        {/* Status */}
        {loading && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
            <CircularProgress size={20} />
            <Typography variant="body2" color="text.secondary">
              Generando malla… puede tardar varios segundos.
            </Typography>
          </Box>
        )}

        {error && (
          <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 1 }}>
            {error}
          </Alert>
        )}

        {result && (
          <Alert
            severity="success"
            icon={<CheckCircle />}
            sx={{ mb: 1 }}
          >
            <Typography variant="body2" gutterBottom>
              <strong>Malla generada en {result.elapsed_s}s</strong>
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
              <Chip label={`${result.node_count.toLocaleString()} nodos`}   size="small" />
              <Chip label={`${result.element_count.toLocaleString()} elem.`} size="small" />
              {Object.entries(result.element_types).map(([t, n]) => (
                <Chip key={t} label={`${t}: ${n}`} size="small" variant="outlined" />
              ))}
            </Box>
          </Alert>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 2, pb: 2, gap: 1 }}>
        <Button onClick={handleClose} disabled={loading}>
          {result ? 'Cerrar' : 'Cancelar'}
        </Button>

        {!result && (
          <Button
            onClick={handleGenerate}
            variant="contained"
            disabled={loading || !stepFile}
          >
            {loading ? 'Generando…' : 'Generar'}
          </Button>
        )}

        {result && (
          <Button onClick={handleOpenInCAE} variant="contained" color="success">
            Abrir en CAEViewer
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
