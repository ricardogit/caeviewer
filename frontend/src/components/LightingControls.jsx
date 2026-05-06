/**
 * LightingControls Component
 * ==========================
 *
 * Panel de controles para ajustar la iluminación de la escena 3D.
 * Permite seleccionar presets y ajustar manualmente cada luz.
 *
 * @module components/LightingControls
 */

import React from 'react';
import {
  Paper,
  Typography,
  Slider,
  Switch,
  FormControlLabel,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Box,
  Divider,
  IconButton,
  Collapse,
  Button,
  Stack,
} from '@mui/material';
import {
  Close,
  WbSunny,
  Brightness3,
  Brightness6,
  ExpandMore,
  ExpandLess,
} from '@mui/icons-material';

import { useViewerStore, LIGHTING_PRESETS } from '../stores/viewerStore';

/**
 * Control de slider con label
 */
function LightControl({ label, value, onChange, min = 0, max = 2, step = 0.1, icon }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
        {icon && <Box sx={{ mr: 1, display: 'flex' }}>{icon}</Box>}
        <Typography variant="body2">{label}</Typography>
        <Box sx={{ ml: 'auto', color: 'primary.main', fontWeight: 'bold' }}>
          {value.toFixed(2)}
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
 * LightingControls Component
 */
export default function LightingControls({ onClose }) {
  const [expandedSections, setExpandedSections] = React.useState({
    ambient: true,
    directional: true,
    hemisphere: false,
  });

  const {
    lightingPreset,
    ambientLightIntensity,
    directionalLightIntensity,
    directionalLightPosition,
    hemisphereLight,
    hemisphereLightIntensity,
    applyLightingPreset,
    setAmbientLightIntensity,
    setDirectionalLightIntensity,
    setDirectionalLightPosition,
    toggleHemisphereLight,
    setHemisphereLightIntensity,
  } = useViewerStore();

  const handlePresetChange = (event) => {
    applyLightingPreset(event.target.value);
  };

  const toggleSection = (section) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  return (
    <Paper
      sx={{
        p: 2,
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        backdropFilter: 'blur(10px)',
        color: 'white',
        maxHeight: '80vh',
        overflow: 'auto',
      }}
    >
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <WbSunny sx={{ mr: 1 }} />
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Lighting
        </Typography>
        {onClose && (
          <IconButton size="small" onClick={onClose} sx={{ color: 'white' }}>
            <Close />
          </IconButton>
        )}
      </Box>

      <Divider sx={{ mb: 2, borderColor: 'rgba(255, 255, 255, 0.12)' }} />

      {/* Preset Selector */}
      <FormControl fullWidth size="small" sx={{ mb: 3 }}>
        <InputLabel sx={{ color: 'white' }}>Lighting Preset</InputLabel>
        <Select
          value={lightingPreset}
          onChange={handlePresetChange}
          label="Lighting Preset"
          sx={{
            color: 'white',
            '.MuiOutlinedInput-notchedOutline': {
              borderColor: 'rgba(255, 255, 255, 0.23)',
            },
            '&:hover .MuiOutlinedInput-notchedOutline': {
              borderColor: 'rgba(255, 255, 255, 0.4)',
            },
          }}
        >
          <MenuItem value={LIGHTING_PRESETS.STUDIO}>Studio</MenuItem>
          <MenuItem value={LIGHTING_PRESETS.OUTDOOR}>Outdoor</MenuItem>
          <MenuItem value={LIGHTING_PRESETS.SOFT}>Soft</MenuItem>
          <MenuItem value={LIGHTING_PRESETS.DRAMATIC}>Dramatic</MenuItem>
          <MenuItem value={LIGHTING_PRESETS.CUSTOM}>Custom</MenuItem>
        </Select>
      </FormControl>

      {/* Ambient Light */}
      <Box sx={{ mb: 2 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            cursor: 'pointer',
            mb: 1,
          }}
          onClick={() => toggleSection('ambient')}
        >
          <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
            Ambient Light
          </Typography>
          <IconButton size="small" sx={{ color: 'white' }}>
            {expandedSections.ambient ? <ExpandLess /> : <ExpandMore />}
          </IconButton>
        </Box>

        <Collapse in={expandedSections.ambient}>
          <LightControl
            label="Intensity"
            value={ambientLightIntensity}
            onChange={setAmbientLightIntensity}
            min={0}
            max={2}
            icon={<Brightness6 sx={{ fontSize: 18 }} />}
          />
        </Collapse>
      </Box>

      <Divider sx={{ my: 2, borderColor: 'rgba(255, 255, 255, 0.12)' }} />

      {/* Directional Light */}
      <Box sx={{ mb: 2 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            cursor: 'pointer',
            mb: 1,
          }}
          onClick={() => toggleSection('directional')}
        >
          <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
            Directional Light (Sun)
          </Typography>
          <IconButton size="small" sx={{ color: 'white' }}>
            {expandedSections.directional ? <ExpandLess /> : <ExpandMore />}
          </IconButton>
        </Box>

        <Collapse in={expandedSections.directional}>
          <LightControl
            label="Intensity"
            value={directionalLightIntensity}
            onChange={setDirectionalLightIntensity}
            min={0}
            max={3}
            icon={<WbSunny sx={{ fontSize: 18 }} />}
          />

          <Typography variant="caption" sx={{ display: 'block', mt: 2, mb: 1 }}>
            Position
          </Typography>

          <Box sx={{ pl: 1 }}>
            <LightControl
              label="X"
              value={directionalLightPosition[0]}
              onChange={(val) =>
                setDirectionalLightPosition([
                  val,
                  directionalLightPosition[1],
                  directionalLightPosition[2],
                ])
              }
              min={-20}
              max={20}
              step={1}
            />

            <LightControl
              label="Y"
              value={directionalLightPosition[1]}
              onChange={(val) =>
                setDirectionalLightPosition([
                  directionalLightPosition[0],
                  val,
                  directionalLightPosition[2],
                ])
              }
              min={-20}
              max={20}
              step={1}
            />

            <LightControl
              label="Z"
              value={directionalLightPosition[2]}
              onChange={(val) =>
                setDirectionalLightPosition([
                  directionalLightPosition[0],
                  directionalLightPosition[1],
                  val,
                ])
              }
              min={-20}
              max={20}
              step={1}
            />
          </Box>
        </Collapse>
      </Box>

      <Divider sx={{ my: 2, borderColor: 'rgba(255, 255, 255, 0.12)' }} />

      {/* Hemisphere Light */}
      <Box sx={{ mb: 2 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            cursor: 'pointer',
            mb: 1,
          }}
          onClick={() => toggleSection('hemisphere')}
        >
          <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
            Hemisphere Light
          </Typography>
          <IconButton size="small" sx={{ color: 'white' }}>
            {expandedSections.hemisphere ? <ExpandLess /> : <ExpandMore />}
          </IconButton>
        </Box>

        <Collapse in={expandedSections.hemisphere}>
          <FormControlLabel
            control={
              <Switch
                checked={hemisphereLight}
                onChange={toggleHemisphereLight}
                size="small"
              />
            }
            label="Enable"
            sx={{ mb: 2 }}
          />

          {hemisphereLight && (
            <LightControl
              label="Intensity"
              value={hemisphereLightIntensity}
              onChange={setHemisphereLightIntensity}
              min={0}
              max={2}
              icon={<Brightness3 sx={{ fontSize: 18 }} />}
            />
          )}
        </Collapse>
      </Box>

      {/* Quick Actions */}
      <Divider sx={{ my: 2, borderColor: 'rgba(255, 255, 255, 0.12)' }} />

      <Typography variant="caption" sx={{ display: 'block', mb: 1 }}>
        Quick Actions
      </Typography>

      <Stack direction="row" spacing={1}>
        <Button
          size="small"
          variant="outlined"
          onClick={() => applyLightingPreset(LIGHTING_PRESETS.STUDIO)}
          fullWidth
        >
          Studio
        </Button>
        <Button
          size="small"
          variant="outlined"
          onClick={() => applyLightingPreset(LIGHTING_PRESETS.SOFT)}
          fullWidth
        >
          Soft
        </Button>
        <Button
          size="small"
          variant="outlined"
          onClick={() => applyLightingPreset(LIGHTING_PRESETS.DRAMATIC)}
          fullWidth
        >
          Dramatic
        </Button>
      </Stack>
    </Paper>
  );
}
