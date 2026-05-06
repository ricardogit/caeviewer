import React, { useState, useEffect } from 'react';
import * as THREE from 'three';
import {
  Box,
  Typography,
  ToggleButtonGroup,
  ToggleButton,
  Slider,
  Switch,
  FormControlLabel,
  Divider,
  Chip,
} from '@mui/material';
import { ContentCut } from '@mui/icons-material';

/**
 * SectionCutPanel — controls a clipping plane applied to the 3D model.
 *
 * Props:
 *   onPlaneChange(plane: THREE.Plane | null) — called whenever the plane changes.
 */
export default function SectionCutPanel({ onPlaneChange }) {
  const [enabled, setEnabled] = useState(false);
  const [axis, setAxis] = useState('Y');
  const [position, setPosition] = useState(0);
  const [flipped, setFlipped] = useState(false);

  useEffect(() => {
    if (!enabled) {
      onPlaneChange?.(null);
      return;
    }
    const normals = {
      X: new THREE.Vector3(1, 0, 0),
      Y: new THREE.Vector3(0, 1, 0),
      Z: new THREE.Vector3(0, 0, 1),
    };
    const normal = normals[axis].clone();
    if (flipped) normal.negate();
    // plane equation: n·x + d = 0 → d = -position along axis
    const plane = new THREE.Plane(normal, -position);
    onPlaneChange?.(plane);
  }, [enabled, axis, position, flipped]);

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <ContentCut fontSize="small" />
          <Typography variant="subtitle2">Section Cut</Typography>
          {enabled && <Chip label="Active" size="small" color="warning" />}
        </Box>
      </Box>

      <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Enable toggle */}
        <FormControlLabel
          control={
            <Switch
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              color="warning"
            />
          }
          label={enabled ? 'Cut enabled' : 'Cut disabled'}
        />

        <Divider />

        {/* Axis selector */}
        <Box>
          <Typography variant="caption" color="text.secondary" gutterBottom>
            Cut axis
          </Typography>
          <ToggleButtonGroup
            value={axis}
            exclusive
            onChange={(_, v) => v && setAxis(v)}
            size="small"
            fullWidth
            disabled={!enabled}
            sx={{ mt: 1 }}
          >
            <ToggleButton value="X" sx={{ flex: 1 }}>X</ToggleButton>
            <ToggleButton value="Y" sx={{ flex: 1 }}>Y</ToggleButton>
            <ToggleButton value="Z" sx={{ flex: 1 }}>Z</ToggleButton>
          </ToggleButtonGroup>
        </Box>

        {/* Position slider */}
        <Box>
          <Typography variant="caption" color="text.secondary">
            Position: <strong>{position} mm</strong>
          </Typography>
          <Slider
            value={position}
            onChange={(_, v) => setPosition(v)}
            min={-2000}
            max={2000}
            step={5}
            disabled={!enabled}
            marks={[
              { value: -2000, label: '-2000' },
              { value: 0, label: '0' },
              { value: 2000, label: '2000' },
            ]}
            sx={{ mt: 1 }}
          />
        </Box>

        {/* Flip direction */}
        <FormControlLabel
          control={
            <Switch
              checked={flipped}
              onChange={(e) => setFlipped(e.target.checked)}
              disabled={!enabled}
            />
          }
          label="Flip cut direction"
        />

        <Divider />

        <Box>
          <Typography variant="caption" color="text.secondary">
            The cut removes everything on one side of the selected plane.
            Use "Flip" to switch which side is removed.
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}
