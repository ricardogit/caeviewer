import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  ButtonGroup,
  List,
  ListItem,
  IconButton,
  Chip,
  TextField,
  CircularProgress,
  Alert,
  Divider,
  Tooltip,
} from '@mui/material';
import {
  Straighten,
  SquareFoot,
  ViewInAr,
  DeleteOutline,
  Calculate,
  Crop,
  MyLocation,
  Check,
} from '@mui/icons-material';
import axios from 'axios';

/**
 * MeasurementTools
 *
 * Props:
 *   headerId            — STEP file header ID
 *   onMeasurementCreate — called with result when measurement computed
 *   pickingMode         — boolean, true when 3D pick is active
 *   onActivatePicking   — callback() to request a 3D point pick
 *   pickedPoint         — [x,y,z] | null, last point picked from 3D model
 *   onPickConsumed      — callback() to clear pickedPoint after reading it
 */
export default function MeasurementTools({
  headerId,
  onMeasurementCreate,
  pickingMode,
  onActivatePicking,
  pickedPoint,
  onPickConsumed,
}) {
  const [measurementType, setMeasurementType] = useState('distance');
  const [measurements, setMeasurements] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Which input is waiting for a pick: null | 'p1' | 'p2' | 'v1' | 'v2'
  const [pendingPick, setPendingPick] = useState(null);

  const [point1, setPoint1] = useState({ x: '', y: '', z: '' });
  const [point2, setPoint2] = useState({ x: '', y: '', z: '' });
  const [vector1, setVector1] = useState({ x: '', y: '', z: '' });
  const [vector2, setVector2] = useState({ x: '', y: '', z: '' });
  const [shapeIndex, setShapeIndex] = useState(0);

  useEffect(() => {
    if (headerId) loadMeasurements();
  }, [headerId]);

  // Consume a picked point and fill the pending input
  useEffect(() => {
    if (!pickedPoint || !pendingPick) return;
    const [x, y, z] = pickedPoint;
    if (pendingPick === 'p1') setPoint1({ x, y, z });
    else if (pendingPick === 'p2') setPoint2({ x, y, z });
    else if (pendingPick === 'v1') setVector1({ x, y, z });
    else if (pendingPick === 'v2') setVector2({ x, y, z });
    setPendingPick(null);
    onPickConsumed?.();
  }, [pickedPoint]);

  function activatePick(target) {
    setPendingPick(target);
    onActivatePicking?.();
  }

  async function loadMeasurements() {
    try {
      const res = await axios.get(`/api/step-view/measurement/${headerId}/list`);
      setMeasurements(res.data.measurements || []);
    } catch (err) {
      console.error('Error loading measurements:', err);
    }
  }

  async function handleCalculate() {
    setLoading(true);
    setError(null);
    try {
      let result;

      if (measurementType === 'distance') {
        const p1 = [parseFloat(point1.x), parseFloat(point1.y), parseFloat(point1.z)];
        const p2 = [parseFloat(point2.x), parseFloat(point2.y), parseFloat(point2.z)];
        if (p1.some(isNaN) || p2.some(isNaN)) { setError('Enter valid coordinates for both points'); return; }
        result = await axios.post('/api/step-view/measurement/distance', { p1, p2 });

      } else if (measurementType === 'angle') {
        const v1 = [parseFloat(vector1.x), parseFloat(vector1.y), parseFloat(vector1.z)];
        const v2 = [parseFloat(vector2.x), parseFloat(vector2.y), parseFloat(vector2.z)];
        if (v1.some(isNaN) || v2.some(isNaN)) { setError('Enter valid coordinates for both vectors'); return; }
        result = await axios.post('/api/step-view/measurement/angle', { v1, v2 });

      } else if (measurementType === 'area') {
        result = await axios.post('/api/step-view/measurement/area', { header_id: headerId, shape_index: shapeIndex });
      } else if (measurementType === 'volume') {
        result = await axios.post('/api/step-view/measurement/volume', { header_id: headerId, shape_index: shapeIndex });
      } else if (measurementType === 'bbox') {
        result = await axios.post('/api/step-view/measurement/bbox', { header_id: headerId, shape_index: shapeIndex });
      }

      if (result?.data) {
        await axios.post(`/api/step-view/measurement/${headerId}/save`, {
          measurement: result.data.measurement || result.data,
        });
        await loadMeasurements();
        onMeasurementCreate?.(result.data);
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleClearAll() {
    if (!window.confirm('Clear all measurements?')) return;
    await axios.delete(`/api/step-view/measurement/${headerId}/clear`);
    setMeasurements([]);
  }

  function formatValue(m) {
    if (m.type === 'bbox') {
      const d = m.dimensions || [0, 0, 0];
      return `${d[0].toFixed(1)} × ${d[1].toFixed(1)} × ${d[2].toFixed(1)} mm`;
    }
    if (!m.value) return 'N/A';
    const unit = m.type === 'angle' ? '°' : ` ${m.unit || 'mm'}`;
    return `${parseFloat(m.value).toFixed(2)}${unit}`;
  }

  const typeColor = { distance: 'primary', angle: 'secondary', area: 'success', volume: 'warning', bbox: 'info' };

  // Point input row with optional Pick button
  function PointRow({ label, value, onChange, pickTarget }) {
    const isPending = pendingPick === pickTarget;
    return (
      <Box sx={{ mb: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5, gap: 1 }}>
          <Typography variant="caption" sx={{ flex: 1 }}>{label}</Typography>
          {onActivatePicking && (
            <Tooltip title={isPending ? 'Waiting for click on model…' : 'Pick from 3D model'}>
              <span>
                <IconButton
                  size="small"
                  color={isPending ? 'success' : 'default'}
                  onClick={() => activatePick(pickTarget)}
                  sx={{ width: 24, height: 24 }}
                >
                  {isPending ? <Check fontSize="inherit" /> : <MyLocation fontSize="inherit" />}
                </IconButton>
              </span>
            </Tooltip>
          )}
        </Box>
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {['x', 'y', 'z'].map(axis => (
            <TextField
              key={axis}
              size="small"
              label={axis.toUpperCase()}
              type="number"
              value={value[axis]}
              onChange={(e) => onChange({ ...value, [axis]: e.target.value })}
              sx={{ flex: 1, '& input': { fontSize: '0.8rem', py: 0.5 } }}
              inputProps={{ step: 'any' }}
            />
          ))}
        </Box>
      </Box>
    );
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="subtitle2" gutterBottom>Measurement Tools</Typography>

        <ButtonGroup size="small" fullWidth sx={{ mb: 1 }}>
          <Button variant={measurementType === 'distance' ? 'contained' : 'outlined'} onClick={() => setMeasurementType('distance')} startIcon={<Straighten />}>Dist</Button>
          <Button variant={measurementType === 'angle' ? 'contained' : 'outlined'} onClick={() => setMeasurementType('angle')} startIcon={<Calculate />}>Angle</Button>
        </ButtonGroup>
        <ButtonGroup size="small" fullWidth sx={{ mb: 1 }}>
          <Button variant={measurementType === 'area' ? 'contained' : 'outlined'} onClick={() => setMeasurementType('area')} startIcon={<SquareFoot />}>Area</Button>
          <Button variant={measurementType === 'volume' ? 'contained' : 'outlined'} onClick={() => setMeasurementType('volume')} startIcon={<ViewInAr />}>Vol</Button>
        </ButtonGroup>
        <Button size="small" fullWidth variant={measurementType === 'bbox' ? 'contained' : 'outlined'} onClick={() => setMeasurementType('bbox')} startIcon={<Crop />}>Bounding Box</Button>
      </Box>

      {/* Inputs */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        {pickingMode && pendingPick && (
          <Alert severity="info" sx={{ mb: 1, py: 0 }}>
            Click on the 3D model to pick a point
          </Alert>
        )}

        {measurementType === 'distance' && (
          <>
            <PointRow label="Point 1 (x, y, z)" value={point1} onChange={setPoint1} pickTarget="p1" />
            <PointRow label="Point 2 (x, y, z)" value={point2} onChange={setPoint2} pickTarget="p2" />
          </>
        )}

        {measurementType === 'angle' && (
          <>
            <PointRow label="Vector 1 (x, y, z)" value={vector1} onChange={setVector1} pickTarget="v1" />
            <PointRow label="Vector 2 (x, y, z)" value={vector2} onChange={setVector2} pickTarget="v2" />
          </>
        )}

        {['area', 'volume', 'bbox'].includes(measurementType) && (
          <TextField
            size="small" fullWidth label="Shape Index" type="number"
            value={shapeIndex}
            onChange={(e) => setShapeIndex(parseInt(e.target.value))}
            helperText="0 = first shape in assembly"
            sx={{ mb: 1 }}
          />
        )}

        <Button variant="contained" fullWidth onClick={handleCalculate} disabled={loading} sx={{ mt: 1 }}>
          {loading ? <CircularProgress size={20} /> : 'Calculate'}
        </Button>

        {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
      </Box>

      {/* Results list */}
      <Box sx={{ flexGrow: 1, overflow: 'auto', p: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="caption" color="text.secondary">
            {measurements.length} measurement{measurements.length !== 1 ? 's' : ''}
          </Typography>
          {measurements.length > 0 && (
            <IconButton size="small" onClick={handleClearAll}><DeleteOutline fontSize="small" /></IconButton>
          )}
        </Box>

        {measurements.length === 0 ? (
          <Alert severity="info">No measurements yet.</Alert>
        ) : (
          <List dense disablePadding>
            {measurements.map((m, i) => (
              <ListItem key={i} sx={{ px: 0, flexDirection: 'column', alignItems: 'flex-start' }}>
                <Chip label={m.type} size="small" color={typeColor[m.type] || 'default'} sx={{ fontSize: '0.7rem', height: 18, mb: 0.5 }} />
                <Typography variant="body2" fontWeight="medium">{formatValue(m)}</Typography>
                {m.label && <Typography variant="caption" color="text.secondary">{m.label}</Typography>}
                {i < measurements.length - 1 && <Divider sx={{ width: '100%', mt: 1 }} />}
              </ListItem>
            ))}
          </List>
        )}
      </Box>
    </Box>
  );
}
