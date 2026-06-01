/**
 * ValidationOverlay — shows graph completeness errors and warnings.
 */
import React from 'react';
import { Box, Typography, IconButton, List, ListItem, ListItemIcon, Chip } from '@mui/material';
import { Close, Error, Warning, CheckCircle } from '@mui/icons-material';

export default function ValidationOverlay({ errors, readyForSimulation, onClose }) {
  const errorCount   = errors.filter(e => e.severity === 'error').length;
  const warningCount = errors.filter(e => e.severity === 'warning').length;

  return (
    <Box
      sx={{
        position: 'absolute', bottom: 16, left: '50%',
        transform: 'translateX(-50%)',
        width: 420,
        bgcolor: '#1a1a1a',
        border: `1px solid ${readyForSimulation ? '#4caf50' : '#f44336'}`,
        borderRadius: 2,
        zIndex: 30,
        boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1,
                 borderBottom: '1px solid #333' }}>
        {readyForSimulation
          ? <CheckCircle sx={{ color: '#4caf50', mr: 1 }} />
          : <Error sx={{ color: '#f44336', mr: 1 }} />
        }
        <Typography variant="subtitle2" sx={{ color: '#fff', flex: 1 }}>
          {readyForSimulation ? '✓ Grafo válido para simulación' : 'Grafo incompleto'}
        </Typography>
        <Chip label={`${errorCount} errores`} size="small" color="error" sx={{ mr: 0.5, height: 20 }} />
        {warningCount > 0 && (
          <Chip label={`${warningCount} avisos`} size="small" color="warning" sx={{ mr: 1, height: 20 }} />
        )}
        <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}>
          <Close fontSize="small" />
        </IconButton>
      </Box>
      <List dense sx={{ maxHeight: 200, overflow: 'auto', py: 0 }}>
        {errors.map((e, i) => (
          <ListItem key={i} sx={{ py: 0.5, px: 2 }}>
            <ListItemIcon sx={{ minWidth: 28 }}>
              {e.severity === 'error'
                ? <Error sx={{ color: '#f44336', fontSize: 16 }} />
                : <Warning sx={{ color: '#ff9800', fontSize: 16 }} />
              }
            </ListItemIcon>
            <Typography variant="caption" sx={{ color: e.severity === 'error' ? '#ef9a9a' : '#ffe082' }}>
              {e.message}
            </Typography>
          </ListItem>
        ))}
      </List>
    </Box>
  );
}
