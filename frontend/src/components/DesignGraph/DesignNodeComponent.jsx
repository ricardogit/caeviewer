/**
 * DesignNodeComponent — custom ReactFlow node renderer.
 * Renders differently based on data.node_type.
 */
import React, { memo } from 'react';
import { Handle, Position } from 'reactflow';
import { Box, Typography, Chip } from '@mui/material';
import {
  Lightbulb, ViewInAr, Science, Lock, ArrowDownward,
  Assessment, AutoAwesome,
} from '@mui/icons-material';

const NODE_CONFIG = {
  CONCEPT:      { color: '#3f51b5', bg: '#1a237e22', Icon: Lightbulb,     label: 'Concepto' },
  GEOMETRY:     { color: '#4caf50', bg: '#1b5e2022', Icon: ViewInAr,      label: 'Geometría' },
  MATERIAL:     { color: '#ff9800', bg: '#e65100222', Icon: Science,       label: 'Material' },
  BC:           { color: '#f44336', bg: '#b71c1c22', Icon: Lock,           label: 'Frontera' },
  LOAD:         { color: '#fdd835', bg: '#f57f1722', Icon: ArrowDownward,  label: 'Carga' },
  RESULT:       { color: '#00bcd4', bg: '#00697022', Icon: Assessment,     label: 'Resultado' },
  OPTIMIZATION: { color: '#9c27b0', bg: '#4a148c22', Icon: AutoAwesome,   label: 'Optimización' },
};

function DesignNodeComponent({ data, selected }) {
  const cfg = NODE_CONFIG[data.node_type] || NODE_CONFIG.CONCEPT;
  const { color, bg, Icon, label: typeLabel } = cfg;

  return (
    <Box
      sx={{
        minWidth: 140,
        maxWidth: 200,
        border: `2px solid ${selected ? '#fff' : color}`,
        borderRadius: 2,
        bgcolor: bg,
        backdropFilter: 'blur(4px)',
        boxShadow: selected ? `0 0 0 2px ${color}` : `0 2px 8px rgba(0,0,0,0.4)`,
        transition: 'box-shadow 0.15s',
        cursor: 'pointer',
        userSelect: 'none',
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex', alignItems: 'center', gap: 0.5,
          px: 1, py: 0.5,
          borderBottom: `1px solid ${color}44`,
          bgcolor: `${color}22`,
          borderRadius: '6px 6px 0 0',
        }}
      >
        <Icon sx={{ fontSize: 14, color }} />
        <Typography variant="caption" sx={{ color, fontWeight: 700, fontSize: 10, textTransform: 'uppercase' }}>
          {typeLabel}
        </Typography>
      </Box>

      {/* Label */}
      <Box sx={{ px: 1, py: 0.75 }}>
        <Typography
          variant="body2"
          sx={{ color: '#fff', fontWeight: 500, fontSize: 13, wordBreak: 'break-word' }}
        >
          {data.label}
        </Typography>

        {/* Properties preview */}
        {data.node_type === 'MATERIAL' && data.properties?.model_type && (
          <Typography variant="caption" sx={{ color: '#aaa', fontSize: 10 }}>
            {data.properties.model_type}
          </Typography>
        )}
        {data.node_type === 'LOAD' && data.properties?.magnitude != null && (
          <Typography variant="caption" sx={{ color: '#aaa', fontSize: 10 }}>
            {data.properties.magnitude} {data.properties.unit || 'N'}
          </Typography>
        )}
        {data.node_type === 'GEOMETRY' && data.tier != null && (
          <Chip label={`Tier ${data.tier}`} size="small"
                sx={{ height: 16, fontSize: 9, mt: 0.3, bgcolor: `${color}33`, color }} />
        )}
        {data.node_type === 'RESULT' && data.properties?.max_von_mises != null && (
          <Typography variant="caption" sx={{ color: '#aaa', fontSize: 10 }}>
            σ_max: {data.properties.max_von_mises?.toFixed(2)} MPa
          </Typography>
        )}
      </Box>

      {/* Connection handles */}
      <Handle type="target" position={Position.Left}
              style={{ background: color, width: 8, height: 8, border: '2px solid #121212' }} />
      <Handle type="source" position={Position.Right}
              style={{ background: color, width: 8, height: 8, border: '2px solid #121212' }} />
    </Box>
  );
}

export default memo(DesignNodeComponent);
