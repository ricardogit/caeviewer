/**
 * EdgeTypeDialog — shown when user connects two nodes.
 * User selects the semantic type of the new edge.
 */
import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, Box, Typography, RadioGroup, FormControlLabel, Radio,
} from '@mui/material';

const EDGE_OPTIONS = [
  { type: 'FUNCTIONAL',      label: 'Funcional',        desc: 'A realiza la función de B', color: '#2196f3' },
  { type: 'PHYSICAL',        label: 'Físico',           desc: 'A está físicamente conectado a B', color: '#9e9e9e' },
  { type: 'CONSTRAINS',      label: 'Restringe',        desc: 'A restringe / condiciona a B', color: '#f44336' },
  { type: 'PRODUCED_BY',     label: 'Manufactura',      desc: 'A se fabrica mediante proceso B', color: '#4caf50' },
  { type: 'DEPENDS_ON',      label: 'Depende de',       desc: 'La simulación A necesita el resultado B', color: '#607d8b' },
  { type: 'PRODUCES',        label: 'Produce',          desc: 'A genera o produce B', color: '#00bcd4' },
];

// Remap PRODUCED_BY to MANUFACTURED_BY for API compatibility
const API_TYPE = { PRODUCED_BY: 'MANUFACTURED_BY' };

export default function EdgeTypeDialog({ open, onConfirm, onCancel }) {
  const [selected, setSelected] = useState('PHYSICAL');

  const handleConfirm = () => {
    onConfirm(API_TYPE[selected] || selected);
    setSelected('PHYSICAL');
  };

  return (
    <Dialog
      open={open}
      onClose={onCancel}
      maxWidth="xs"
      fullWidth
      PaperProps={{ sx: { bgcolor: '#1e1e1e', border: '1px solid #333' } }}
    >
      <DialogTitle sx={{ color: '#90caf9', fontSize: 15 }}>
        Tipo de relación
      </DialogTitle>
      <DialogContent>
        <RadioGroup value={selected} onChange={e => setSelected(e.target.value)}>
          {EDGE_OPTIONS.map(opt => (
            <FormControlLabel
              key={opt.type}
              value={opt.type}
              control={<Radio size="small" sx={{ color: opt.color, '&.Mui-checked': { color: opt.color } }} />}
              label={
                <Box>
                  <Typography variant="body2" sx={{ color: opt.color, fontWeight: 600 }}>
                    {opt.label}
                  </Typography>
                  <Typography variant="caption" sx={{ color: '#888' }}>
                    {opt.desc}
                  </Typography>
                </Box>
              }
              sx={{ mb: 0.5, alignItems: 'flex-start', mt: 0.25 }}
            />
          ))}
        </RadioGroup>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} size="small" sx={{ color: '#888' }}>Cancelar</Button>
        <Button onClick={handleConfirm} variant="contained" size="small">
          Crear arista
        </Button>
      </DialogActions>
    </Dialog>
  );
}
