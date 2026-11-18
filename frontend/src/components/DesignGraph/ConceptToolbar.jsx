/**
 * ConceptToolbar — draggable palette of engineering concept node types.
 * Positioned as a floating panel inside the GraphEditor canvas.
 */
import React from 'react';
import { Box, Typography, Tooltip, Paper } from '@mui/material';
import {
  Lightbulb, ViewInAr, Science, Lock, ArrowDownward, AutoAwesome, CheckCircle,
} from '@mui/icons-material';
import { NODE_COLORS } from './GraphEditor';

const NODE_TYPES_CONFIG = [
  { type: 'CONCEPT',      label: 'Concepto',     Icon: Lightbulb,    defaultLabel: 'Nuevo concepto' },
  { type: 'GEOMETRY',     label: 'Geometría',    Icon: ViewInAr,     defaultLabel: 'Geometría' },
  { type: 'MATERIAL',     label: 'Material',     Icon: Science,      defaultLabel: 'Material' },
  { type: 'BC',           label: 'Frontera',     Icon: Lock,         defaultLabel: 'Condición de frontera' },
  { type: 'LOAD',         label: 'Carga',        Icon: ArrowDownward,defaultLabel: 'Carga aplicada' },
  { type: 'RESULT',       label: 'Resultado',    Icon: CheckCircle,  defaultLabel: 'Resultado de simulación' },
  { type: 'OPTIMIZATION', label: 'Optimización', Icon: AutoAwesome,  defaultLabel: 'Optimización topológica' },
];

function NodeTypeButton({ type, label, Icon, defaultLabel }) {
  const color = NODE_COLORS[type] || '#888';

  const onDragStart = (e) => {
    e.dataTransfer.setData('application/design-node-type', type);
    e.dataTransfer.setData('application/design-node-label', defaultLabel);
    e.dataTransfer.effectAllowed = 'move';
  };

  return (
    <Tooltip title={`Agregar ${label} — arrastra al lienzo`} placement="right">
      <Box
        draggable
        onDragStart={onDragStart}
        sx={{
          display: 'flex', alignItems: 'center', gap: 1,
          px: 1.5, py: 0.75,
          border: `1px solid ${color}55`,
          borderRadius: 1,
          cursor: 'grab',
          bgcolor: `${color}15`,
          '&:hover': { bgcolor: `${color}30`, borderColor: color },
          transition: 'all 0.15s',
          userSelect: 'none',
        }}
      >
        <Icon sx={{ fontSize: 16, color }} />
        <Typography variant="caption" sx={{ color, fontWeight: 600, fontSize: 11 }}>
          {label}
        </Typography>
      </Box>
    </Tooltip>
  );
}

export default function ConceptToolbar() {
  return (
    <Paper
      elevation={4}
      sx={{
        position: 'absolute',
        top: 16,
        left: 16,
        zIndex: 10,
        bgcolor: '#1a1a1a',
        border: '1px solid #333',
        borderRadius: 2,
        p: 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.5,
        minWidth: 148,
      }}
    >
      <Typography
        variant="caption"
        sx={{ color: '#666', fontSize: 9, textTransform: 'uppercase',
              letterSpacing: 1, px: 0.5, pb: 0.25 }}
      >
        Nodos — arrastra al canvas
      </Typography>
      {NODE_TYPES_CONFIG.map(cfg => (
        <NodeTypeButton key={cfg.type} {...cfg} />
      ))}
    </Paper>
  );
}
