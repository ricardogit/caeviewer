/**
 * EdgePanel — right-side property panel for the selected design edge.
 */
import React from 'react';
import { Box, Typography, IconButton, Chip, Button } from '@mui/material';
import { Close, Delete } from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';

const EDGE_COLORS = {
  FUNCTIONAL: '#2196f3', PHYSICAL: '#9e9e9e', DEPENDS_ON: '#607d8b',
  MANUFACTURED_BY: '#4caf50', CONSTRAINS: '#f44336', PRODUCES: '#00bcd4',
};

const EDGE_DESCRIPTIONS = {
  FUNCTIONAL:      'A realiza la función de B',
  PHYSICAL:        'A está físicamente conectado a B',
  DEPENDS_ON:      'La simulación A necesita el resultado de B',
  MANUFACTURED_BY: 'A se fabrica mediante el proceso B',
  CONSTRAINS:      'A restringe o condiciona el comportamiento de B',
  PRODUCES:        'A genera o produce B como salida',
};

export default function EdgePanel({ edge, onClose }) {
  const { deleteEdge } = useDesignStore();
  const edgeType = edge.data?.edge_type || 'PHYSICAL';
  const color = EDGE_COLORS[edgeType] || '#888';

  const handleDelete = () => {
    deleteEdge(edge.id);
    onClose();
  };

  return (
    <Box
      sx={{
        position: 'absolute', top: 0, right: 0, bottom: 0,
        width: 260,
        bgcolor: '#1a1a1a',
        borderLeft: `2px solid ${color}`,
        zIndex: 20,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', px: 1.5, py: 1,
                 borderBottom: '1px solid #333', bgcolor: `${color}18` }}>
        <Chip label="ARISTA" size="small"
              sx={{ bgcolor: color, color: '#000', fontWeight: 700, fontSize: 10, mr: 1 }} />
        <Typography variant="subtitle2" sx={{ color: '#fff', flex: 1, fontSize: 13 }}>
          Relación
        </Typography>
        <IconButton size="small" onClick={handleDelete} sx={{ color: '#f44336', mr: 0.5 }}>
          <Delete fontSize="small" />
        </IconButton>
        <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}>
          <Close fontSize="small" />
        </IconButton>
      </Box>

      <Box sx={{ p: 1.5, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        <Box>
          <Typography variant="caption" sx={{ color: '#888' }}>Tipo</Typography>
          <Typography variant="body1" sx={{ color, fontWeight: 700 }}>{edgeType}</Typography>
          <Typography variant="caption" sx={{ color: '#aaa' }}>
            {EDGE_DESCRIPTIONS[edgeType] || ''}
          </Typography>
        </Box>

        <Box>
          <Typography variant="caption" sx={{ color: '#888' }}>Peso</Typography>
          <Typography variant="body2" sx={{ color: '#fff', fontFamily: 'monospace' }}>
            {edge.data?.weight ?? 1.0}
          </Typography>
        </Box>

        <Box>
          <Typography variant="caption" sx={{ color: '#888' }}>IDs</Typography>
          <Typography variant="caption" sx={{ color: '#555', fontFamily: 'monospace', display: 'block' }}>
            src: {edge.source?.slice(0, 12)}…
          </Typography>
          <Typography variant="caption" sx={{ color: '#555', fontFamily: 'monospace', display: 'block' }}>
            tgt: {edge.target?.slice(0, 12)}…
          </Typography>
        </Box>
      </Box>

      <Box sx={{ p: 1.5, borderTop: '1px solid #333', mt: 'auto' }}>
        <Button
          variant="outlined" fullWidth size="small" color="error"
          onClick={handleDelete} startIcon={<Delete />}
        >
          Eliminar arista
        </Button>
      </Box>
    </Box>
  );
}
