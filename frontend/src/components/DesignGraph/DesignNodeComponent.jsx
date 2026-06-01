/**
 * DesignNodeComponent — custom ReactFlow node renderer.
 * Renders differently based on data.node_type.
 */
import React, { memo } from 'react';
import { Handle, Position } from 'reactflow';
import { Box, Typography, Chip } from '@mui/material';
import {
  Lightbulb, ViewInAr, Science, Lock, ArrowDownward,
  CheckCircle, AutoAwesome,
} from '@mui/icons-material';

const NODE_CONFIG = {
  CONCEPT:      { color: '#3f51b5', bg: '#1a237e22', Icon: Lightbulb,     label: 'Concepto' },
  GEOMETRY:     { color: '#4caf50', bg: '#1b5e2022', Icon: ViewInAr,      label: 'Geometría' },
  MATERIAL:     { color: '#ff9800', bg: '#e65100222', Icon: Science,       label: 'Material' },
  BC:           { color: '#f44336', bg: '#b71c1c22', Icon: Lock,           label: 'Frontera' },
  LOAD:         { color: '#fdd835', bg: '#f57f1722', Icon: ArrowDownward,  label: 'Carga' },
  RESULT:       { color: '#00bcd4', bg: '#00697022', Icon: CheckCircle,    label: 'Resultado' },
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
        {data.node_type === 'MATERIAL' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, mt: 0.3 }}>
            {data.properties?.model_type && (
              <Typography variant="caption" sx={{ color: '#bbb', fontSize: 9 }}>
                {data.properties.model_type === 'linear_elastic_isotropic' ? 'Isotropic' : data.properties.model_type.substring(0, 12)}...
              </Typography>
            )}
            {data.properties?.E != null && (
              <Typography variant="caption" sx={{ color: '#aaa', fontSize: 9 }}>
                E={(data.properties.E / 1e9)?.toFixed(0)} GPa ν={data.properties.nu?.toFixed(2)}
              </Typography>
            )}
          </Box>
        )}
        {data.node_type === 'BC' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, mt: 0.3 }}>
            {data.properties?.bc_type && (
              <Typography variant="caption" sx={{ color: '#bbb', fontSize: 9 }}>
                {data.properties.bc_type}
              </Typography>
            )}
            {data.properties?.dofs?.length > 0 && (
              <Typography variant="caption" sx={{ color: '#aaa', fontSize: 9 }}>
                DOFs: {['UX', 'UY', 'UZ', 'RX', 'RY', 'RZ'].filter((_, i) => data.properties.dofs.includes(i)).join(',')}
              </Typography>
            )}
          </Box>
        )}
        {data.node_type === 'LOAD' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, mt: 0.3 }}>
            {data.properties?.magnitude != null && (
              <Typography variant="caption" sx={{ color: '#bbb', fontSize: 9 }}>
                F={data.properties.magnitude} {data.properties.unit || 'N'}
              </Typography>
            )}
            {data.properties?.dir_x != null && (
              <Typography variant="caption" sx={{ color: '#aaa', fontSize: 9 }}>
                Dir: [{data.properties.dir_x?.toFixed(1)}, {data.properties.dir_y?.toFixed(1)}, {data.properties.dir_z?.toFixed(1)}]
              </Typography>
            )}
          </Box>
        )}
        {data.node_type === 'GEOMETRY' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, mt: 0.3 }}>
            {data.properties?.sdf_func && (
              <Typography variant="caption" sx={{ color: '#bbb', fontSize: 9 }}>
                {data.properties.sdf_func}
              </Typography>
            )}
            {(data.tier != null || data.properties?.tier != null) && (
              <Chip label={`Tier ${data.tier ?? data.properties.tier ?? 1}`} size="small"
                    sx={{ height: 16, fontSize: 9, bgcolor: `${color}33`, color }} />
            )}
          </Box>
        )}
        {data.node_type === 'RESULT' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, mt: 0.3 }}>
            {data.properties?.max_von_mises_mpa != null ? (
              <Typography variant="caption" sx={{ color: '#bbb', fontSize: 9 }}>
                σ_max: {data.properties.max_von_mises_mpa?.toFixed(2)} MPa
              </Typography>
            ) : data.properties?.max_von_mises != null ? (
              <Typography variant="caption" sx={{ color: '#bbb', fontSize: 9 }}>
                σ_max: {(data.properties.max_von_mises / 1e6)?.toFixed(2)} MPa
              </Typography>
            ) : (
              <Typography variant="caption" sx={{ color: '#666', fontSize: 9 }}>
                Sin datos
              </Typography>
            )}
            {data.properties?.max_displacement_mm != null && (
              <Typography variant="caption" sx={{ color: '#aaa', fontSize: 9 }}>
                δ_max: {data.properties.max_displacement_mm?.toFixed(3)} mm
              </Typography>
            )}
          </Box>
        )}
        {data.node_type === 'OPTIMIZATION' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, mt: 0.3 }}>
            {data.properties?.objective && (
              <Typography variant="caption" sx={{ color: '#bbb', fontSize: 9 }}>
                {data.properties.objective?.replace(/_/g, ' ')}
              </Typography>
            )}
            {data.properties?.constraint_type && (
              <Typography variant="caption" sx={{ color: '#aaa', fontSize: 9 }}>
                Limit: {data.properties.constraint_value?.toFixed(2)}
              </Typography>
            )}
          </Box>
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
