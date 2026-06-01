/**
 * FieldSelector — dropdown to choose which result field to visualize.
 * FASE 2: minimal selector; full 3D integration in FASE 9.
 */
import React from 'react';
import { Box, FormControl, InputLabel, Select, MenuItem, Typography, Chip } from '@mui/material';
import useSolverStore from '../../stores/solverStore';

const FIELD_LABELS = {
  'displacement_magnitude': 'Desplazamiento |u| [m]',
  'von_mises_nodal':        'Von Mises nodal [Pa]',
  'von_mises_elemental':    'Von Mises elemental [Pa]',
  'displacement':           'Desplazamiento vectorial [m]',
};

export default function FieldSelector() {
  const { resultFields, selectedField, setSelectedField, activeRunId } = useSolverStore();

  if (!resultFields || resultFields.length === 0) return null;

  return (
    <Box sx={{ bgcolor: '#0d0d0d', border: '1px solid #333', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" sx={{ color: '#888', fontSize: 10, display: 'block', mb: 0.5 }}>
        Campo para visualización
      </Typography>
      <FormControl size="small" fullWidth>
        <InputLabel sx={{ color: '#888', fontSize: 12 }}>Campo</InputLabel>
        <Select
          value={selectedField}
          onChange={e => setSelectedField(e.target.value)}
          label="Campo"
          sx={{ color: '#fff', fontSize: 12 }}
        >
          {resultFields.map(f => (
            <MenuItem key={f.name} value={f.name} sx={{ fontSize: 12 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%', gap: 1 }}>
                <span>{FIELD_LABELS[f.name] || f.name}</span>
                <Chip
                  label={`${f.data_max?.toExponential(2)}`}
                  size="small"
                  sx={{ height: 16, fontSize: 9, bgcolor: '#1a237e', color: '#90caf9' }}
                />
              </Box>
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {activeRunId && selectedField && (
        <Typography variant="caption" sx={{ color: '#555', fontSize: 9, mt: 0.5, display: 'block' }}>
          GET /api/design/solver/{activeRunId?.slice(0,8)}…/field/{selectedField}
        </Typography>
      )}
    </Box>
  );
}
