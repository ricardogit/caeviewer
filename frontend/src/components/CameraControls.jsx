/**
 * CameraControls Component
 * ========================
 *
 * Panel de controles para ajustar la cámara de la escena 3D.
 * Permite cambiar FOV, posición, auto-rotate y vistas predefinidas.
 *
 * @module components/CameraControls
 */

import React from 'react';
import {
  Paper,
  Typography,
  Slider,
  Switch,
  FormControlLabel,
  Box,
  Divider,
  IconButton,
  Button,
  Stack,
  ButtonGroup,
  Tooltip,
} from '@mui/material';
import {
  Close,
  CameraAlt,
  ThreeDRotation,
  CenterFocusStrong,
  ViewInAr,
} from '@mui/icons-material';

import { useViewerStore } from '../stores/viewerStore';
import { useThree } from '@react-three/fiber';

/**
 * Control de slider con label
 */
function CameraSlider({ label, value, onChange, min, max, step = 1 }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
        <Typography variant="body2">{label}</Typography>
        <Box sx={{ ml: 'auto', color: 'primary.main', fontWeight: 'bold' }}>
          {typeof value === 'number' ? value.toFixed(1) : value}
        </Box>
      </Box>
      <Slider
        value={value}
        onChange={(e, newValue) => onChange(newValue)}
        min={min}
        max={max}
        step={step}
        valueLabelDisplay="auto"
        size="small"
      />
    </Box>
  );
}

/**
 * Botón de vista predefinida
 */
function ViewButton({ label, position, tooltip, onClick }) {
  const handleClick = () => {
    onClick?.(position);
  };

  return (
    <Tooltip title={tooltip}>
      <Button
        size="small"
        variant="outlined"
        onClick={handleClick}
        sx={{ minWidth: 'auto', px: 1 }}
      >
        {label}
      </Button>
    </Tooltip>
  );
}

/**
 * CameraControls Component
 */
export default function CameraControls({ onClose }) {
  const {
    cameraFov,
    cameraAutoRotate,
    cameraAutoRotateSpeed,
    setCameraFov,
    setAutoRotateSpeed,
    toggleAutoRotate,
    resetCamera,
  } = useViewerStore();

  // Hook para acceder a la cámara y controles de Three.js
  // (esto se usaría dentro del Canvas, pero aquí solo manejamos el store)

  const handleSetView = (position) => {
    // Esta función sería llamada desde dentro del Canvas
    // Por ahora solo actualizamos el store
    useViewerStore.getState().setCameraPosition(position);
  };

  return (
    <Paper
      sx={{
        p: 2,
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        backdropFilter: 'blur(10px)',
        color: 'white',
        minWidth: 300,
      }}
    >
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <CameraAlt sx={{ mr: 1 }} />
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Camera
        </Typography>
        {onClose && (
          <IconButton size="small" onClick={onClose} sx={{ color: 'white' }}>
            <Close />
          </IconButton>
        )}
      </Box>

      <Divider sx={{ mb: 2, borderColor: 'rgba(255, 255, 255, 0.12)' }} />

      {/* Field of View */}
      <CameraSlider
        label="Field of View"
        value={cameraFov}
        onChange={setCameraFov}
        min={10}
        max={120}
        step={1}
      />

      {/* Auto Rotate */}
      <Box sx={{ mb: 2 }}>
        <FormControlLabel
          control={
            <Switch
              checked={cameraAutoRotate}
              onChange={toggleAutoRotate}
              size="small"
            />
          }
          label={
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <ThreeDRotation sx={{ mr: 1, fontSize: 18 }} />
              Auto Rotate
            </Box>
          }
        />

        {cameraAutoRotate && (
          <CameraSlider
            label="Rotation Speed"
            value={cameraAutoRotateSpeed}
            onChange={setAutoRotateSpeed}
            min={0.1}
            max={5}
            step={0.1}
          />
        )}
      </Box>

      <Divider sx={{ my: 2, borderColor: 'rgba(255, 255, 255, 0.12)' }} />

      {/* Predefined Views */}
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        <ViewInAr sx={{ fontSize: 18, mr: 1, verticalAlign: 'middle' }} />
        Predefined Views
      </Typography>

      <Stack spacing={1}>
        {/* Standard Views */}
        <ButtonGroup variant="outlined" fullWidth size="small">
          <ViewButton
            label="Front"
            position={[0, 0, 10]}
            tooltip="Front view (Z+)"
            onClick={handleSetView}
          />
          <ViewButton
            label="Back"
            position={[0, 0, -10]}
            tooltip="Back view (Z-)"
            onClick={handleSetView}
          />
          <ViewButton
            label="Left"
            position={[-10, 0, 0]}
            tooltip="Left view (X-)"
            onClick={handleSetView}
          />
          <ViewButton
            label="Right"
            position={[10, 0, 0]}
            tooltip="Right view (X+)"
            onClick={handleSetView}
          />
        </ButtonGroup>

        <ButtonGroup variant="outlined" fullWidth size="small">
          <ViewButton
            label="Top"
            position={[0, 10, 0]}
            tooltip="Top view (Y+)"
            onClick={handleSetView}
          />
          <ViewButton
            label="Bottom"
            position={[0, -10, 0]}
            tooltip="Bottom view (Y-)"
            onClick={handleSetView}
          />
        </ButtonGroup>

        {/* Isometric Views */}
        <ButtonGroup variant="outlined" fullWidth size="small">
          <ViewButton
            label="Iso 1"
            position={[7, 7, 7]}
            tooltip="Isometric view 1"
            onClick={handleSetView}
          />
          <ViewButton
            label="Iso 2"
            position={[-7, 7, 7]}
            tooltip="Isometric view 2"
            onClick={handleSetView}
          />
          <ViewButton
            label="Iso 3"
            position={[7, 7, -7]}
            tooltip="Isometric view 3"
            onClick={handleSetView}
          />
          <ViewButton
            label="Iso 4"
            position={[-7, 7, -7]}
            tooltip="Isometric view 4"
            onClick={handleSetView}
          />
        </ButtonGroup>
      </Stack>

      <Divider sx={{ my: 2, borderColor: 'rgba(255, 255, 255, 0.12)' }} />

      {/* Actions */}
      <Stack spacing={1}>
        <Button
          variant="contained"
          startIcon={<CenterFocusStrong />}
          onClick={resetCamera}
          fullWidth
        >
          Reset Camera
        </Button>
      </Stack>

      {/* Info */}
      <Box
        sx={{
          mt: 2,
          p: 1,
          backgroundColor: 'rgba(255, 255, 255, 0.05)',
          borderRadius: 1,
        }}
      >
        <Typography variant="caption" sx={{ display: 'block', mb: 0.5 }}>
          <strong>Controls:</strong>
        </Typography>
        <Typography variant="caption" sx={{ display: 'block' }}>
          • Left Click + Drag: Rotate
        </Typography>
        <Typography variant="caption" sx={{ display: 'block' }}>
          • Right Click + Drag: Pan
        </Typography>
        <Typography variant="caption" sx={{ display: 'block' }}>
          • Scroll: Zoom
        </Typography>
      </Box>
    </Paper>
  );
}

/**
 * Componente auxiliar para implementar cambios de cámara dentro del Canvas
 * Debe usarse dentro del <Canvas> de R3F
 */
export function CameraController() {
  const { camera } = useThree();
  const cameraPosition = useViewerStore((state) => state.cameraPosition);
  const cameraFov = useViewerStore((state) => state.cameraFov);

  // Actualizar FOV
  React.useEffect(() => {
    if (camera) {
      camera.fov = cameraFov;
      camera.updateProjectionMatrix();
    }
  }, [camera, cameraFov]);

  // Actualizar posición (con animación suave)
  React.useEffect(() => {
    if (camera && cameraPosition) {
      // Aquí podrías usar gsap o similar para animar la transición
      camera.position.set(...cameraPosition);
    }
  }, [camera, cameraPosition]);

  return null;
}
