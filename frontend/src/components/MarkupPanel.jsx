import React, { useState } from 'react';
import {
  Box,
  Typography,
  ToggleButtonGroup,
  ToggleButton,
  Slider,
  Button,
  Switch,
  FormControlLabel,
  Divider,
  Tooltip,
  CircularProgress,
  Alert,
} from '@mui/material';
import {
  Gesture,
  ArrowForward,
  CropSquare,
  TextFields,
  AutoFixHigh,
  Undo,
  Delete,
  Save,
  Draw,
} from '@mui/icons-material';
import axios from 'axios';

const COLORS = ['#ff4444', '#44aaff', '#44ff88', '#ffcc00', '#ff88cc', '#ffffff'];

/**
 * MarkupPanel — sidebar toolbar for the 2D annotation/markup canvas.
 *
 * Props:
 *   headerId        — STEP file header ID for persistence
 *   active          — whether markup mode is on
 *   onActiveChange  — called when markup mode toggled
 *   tool            — current tool: 'pen' | 'arrow' | 'rect' | 'text' | 'eraser'
 *   onToolChange
 *   color           — current stroke color
 *   onColorChange
 *   strokeWidth     — current stroke width (1-10)
 *   onStrokeWidthChange
 *   strokes         — current strokes array
 *   onStrokesChange — called with new strokes array
 */
export default function MarkupPanel({
  headerId,
  active, onActiveChange,
  tool, onToolChange,
  color, onColorChange,
  strokeWidth, onStrokeWidthChange,
  strokes, onStrokesChange,
}) {
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);

  async function handleSave() {
    if (!headerId) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      await axios.post(`/api/step-view/markup/${headerId}/save`, { strokes });
      setSaveMsg({ type: 'success', text: 'Saved' });
    } catch {
      setSaveMsg({ type: 'error', text: 'Save failed' });
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 3000);
    }
  }

  async function handleLoad() {
    if (!headerId) return;
    try {
      const res = await axios.get(`/api/step-view/markup/${headerId}/list`);
      onStrokesChange(res.data.strokes || []);
    } catch {
      setSaveMsg({ type: 'error', text: 'Load failed' });
    }
  }

  function handleUndo() {
    onStrokesChange(strokes.slice(0, -1));
  }

  async function handleClear() {
    if (!window.confirm('Clear all markup?')) return;
    onStrokesChange([]);
    if (headerId) {
      try { await axios.delete(`/api/step-view/markup/${headerId}/clear`); } catch { /* ignore */ }
    }
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Draw fontSize="small" />
          <Typography variant="subtitle2">Markup</Typography>
        </Box>
      </Box>

      <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2, flexGrow: 1, overflow: 'auto' }}>
        {/* Enable toggle */}
        <FormControlLabel
          control={<Switch checked={active} onChange={(e) => onActiveChange(e.target.checked)} color="error" />}
          label={active ? 'Drawing mode ON' : 'Drawing mode OFF'}
        />

        <Divider />

        {/* Tool selector */}
        <Box>
          <Typography variant="caption" color="text.secondary">Tool</Typography>
          <ToggleButtonGroup
            value={tool}
            exclusive
            onChange={(_, v) => v && onToolChange(v)}
            size="small"
            sx={{ mt: 1, flexWrap: 'wrap', gap: 0.5 }}
          >
            <Tooltip title="Freehand pen">
              <ToggleButton value="pen"><Gesture /></ToggleButton>
            </Tooltip>
            <Tooltip title="Arrow">
              <ToggleButton value="arrow"><ArrowForward /></ToggleButton>
            </Tooltip>
            <Tooltip title="Rectangle">
              <ToggleButton value="rect"><CropSquare /></ToggleButton>
            </Tooltip>
            <Tooltip title="Text">
              <ToggleButton value="text"><TextFields /></ToggleButton>
            </Tooltip>
            <Tooltip title="Eraser (undo last)">
              <ToggleButton value="eraser"><AutoFixHigh /></ToggleButton>
            </Tooltip>
          </ToggleButtonGroup>
        </Box>

        {/* Color picker */}
        <Box>
          <Typography variant="caption" color="text.secondary">Color</Typography>
          <Box sx={{ display: 'flex', gap: 1, mt: 1, flexWrap: 'wrap' }}>
            {COLORS.map(c => (
              <Box
                key={c}
                onClick={() => onColorChange(c)}
                sx={{
                  width: 28, height: 28,
                  borderRadius: '50%',
                  bgcolor: c,
                  cursor: 'pointer',
                  border: color === c ? '3px solid white' : '2px solid rgba(255,255,255,0.3)',
                  transition: 'transform 0.1s',
                  '&:hover': { transform: 'scale(1.15)' },
                }}
              />
            ))}
          </Box>
        </Box>

        {/* Stroke width */}
        <Box>
          <Typography variant="caption" color="text.secondary">
            Stroke width: <strong>{strokeWidth}</strong>
          </Typography>
          <Slider
            value={strokeWidth}
            onChange={(_, v) => onStrokeWidthChange(v)}
            min={1} max={10} step={1}
            sx={{ mt: 1 }}
          />
        </Box>

        <Divider />

        {/* Action buttons */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Button
            startIcon={<Undo />}
            size="small"
            variant="outlined"
            onClick={handleUndo}
            disabled={strokes.length === 0}
            fullWidth
          >
            Undo last stroke ({strokes.length})
          </Button>

          <Button
            startIcon={<Delete />}
            size="small"
            variant="outlined"
            color="error"
            onClick={handleClear}
            disabled={strokes.length === 0}
            fullWidth
          >
            Clear all
          </Button>

          <Button
            startIcon={saving ? <CircularProgress size={14} /> : <Save />}
            size="small"
            variant="contained"
            onClick={handleSave}
            disabled={saving || !headerId}
            fullWidth
          >
            Save to server
          </Button>

          <Button
            size="small"
            variant="outlined"
            onClick={handleLoad}
            disabled={!headerId}
            fullWidth
          >
            Load saved
          </Button>
        </Box>

        {saveMsg && (
          <Alert severity={saveMsg.type} sx={{ mt: 1 }}>
            {saveMsg.text}
          </Alert>
        )}
      </Box>
    </Box>
  );
}
