/**
 * Shown in the STEP-mode panels that need the stored entity graph (entity tree, features, PMI)
 * while the backend reports it as not available (file entry `entity_graph: false`).
 */
import React from 'react';
import { Alert, AlertTitle, Box } from '@mui/material';

export default function EntityGraphUnavailable({ title }) {
  return (
    <Box sx={{ p: 2, pt: 6 }}>
      <Alert severity="info" variant="outlined">
        <AlertTitle>{title} no disponible</AlertTitle>
        El análisis de entidades STEP (árbol de entidades, features, PMI) no está disponible en CAE Viewer.
        El visor 3D, la medición, el corte y las anotaciones sí funcionan.
      </Alert>
    </Box>
  );
}
