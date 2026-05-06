import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Button,
  Alert,
  CircularProgress,
  Divider,
  Slider,
  InputAdornment,
} from '@mui/material';
import { Settings, Build } from '@mui/icons-material';
import axios from 'axios';

const MATERIALS = [
  { value: 'aluminum_6061', label: 'Aluminio 6061' },
  { value: 'steel_1018', label: 'Acero 1018' },
  { value: 'stainless_steel_304', label: 'Acero Inox 304' },
  { value: 'titanium_ti6al4v', label: 'Titanio Ti-6Al-4V' },
  { value: 'brass', label: 'Latón' },
  { value: 'copper', label: 'Cobre' },
  { value: 'cast_iron', label: 'Hierro fundido' },
  { value: 'plastic_abs', label: 'Plástico ABS' },
];

const STRATEGIES = [
  { value: 'balanced', label: 'Equilibrado (recomendado)' },
  { value: 'cost', label: 'Minimizar costo' },
  { value: 'time', label: 'Minimizar tiempo' },
  { value: 'quality', label: 'Maximizar calidad' },
];

export default function PlanConfigPanel({ selectedFile, onPlanGenerate }) {
  const [config, setConfig] = useState({
    partName: '',
    material: 'aluminum_6061',
    machineId: '',
    optimizationStrategy: 'balanced',
    productionVolume: 1,
    toleranceClass: 'standard',
    surfaceFinish: '',
  });

  const [machines, setMachines] = useState([]);
  const [loadingMachines, setLoadingMachines] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    loadMachines();
  }, []);

  useEffect(() => {
    if (selectedFile) {
      setConfig(prev => ({
        ...prev,
        partName: selectedFile.original_filename || selectedFile.filename || '',
      }));
    }
  }, [selectedFile]);

  async function loadMachines() {
    setLoadingMachines(true);
    try {
      const res = await axios.get('/api/v2/machines');
      const list = res.data.machines || res.data || [];
      setMachines(list);
      if (list.length > 0) {
        setConfig(prev => ({ ...prev, machineId: String(list[0].id) }));
      }
    } catch (err) {
      console.error('Error loading machines:', err);
    } finally {
      setLoadingMachines(false);
    }
  }

  async function handleGeneratePlan() {
    if (!selectedFile) { setError('Selecciona un archivo STEP primero'); return; }
    if (!config.machineId) { setError('Selecciona una máquina'); return; }

    setIsGenerating(true);
    setError(null);
    setSuccess(null);

    const partId = selectedFile.part_id || selectedFile.id;

    try {
      const res = await axios.post('/api/v2/generate-plan', {
        part_id: partId,
        machine_id: config.machineId,
        optimization_strategy: config.optimizationStrategy,
        material: config.material,
        part_name: config.partName,
        production_volume: config.productionVolume,
        tolerance_class: config.toleranceClass,
        surface_finish: config.surfaceFinish || undefined,
      });

      const planId = res.data.plan?.id || res.data.plan_id || 'N/A';
      setSuccess(`Plan generado correctamente. ID: ${planId}`);
      onPlanGenerate?.(res.data);
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || err.message);
    } finally {
      setIsGenerating(false);
    }
  }

  function set(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }));
  }

  if (!selectedFile) {
    return (
      <Box sx={{ p: 2, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Typography variant="body2" color="text.secondary" align="center">
          Selecciona un archivo STEP para configurar el plan de fabricación
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 2, height: '100%', overflow: 'auto' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
        <Settings sx={{ mr: 1 }} />
        <Typography variant="h6">Configuración del plan</Typography>
      </Box>

      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        {selectedFile.original_filename || selectedFile.filename}
      </Typography>

      <Divider sx={{ mb: 2 }} />

      {/* Part name */}
      <TextField
        label="Nombre de la pieza"
        value={config.partName}
        onChange={(e) => set('partName', e.target.value)}
        fullWidth size="small" sx={{ mb: 2 }}
      />

      {/* Material */}
      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
        <InputLabel>Material</InputLabel>
        <Select value={config.material} onChange={(e) => set('material', e.target.value)} label="Material">
          {MATERIALS.map((m) => (
            <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Machine */}
      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
        <InputLabel>Máquina objetivo</InputLabel>
        <Select
          value={config.machineId}
          onChange={(e) => set('machineId', e.target.value)}
          label="Máquina objetivo"
          disabled={loadingMachines}
          startAdornment={loadingMachines ? <CircularProgress size={14} sx={{ ml: 1 }} /> : null}
        >
          {machines.map((m) => (
            <MenuItem key={m.id} value={String(m.id)}>
              {m.name || m.machine_name || m.model || `Máquina ${m.id}`}
              {m.machine_type && ` — ${m.machine_type}`}
            </MenuItem>
          ))}
          {machines.length === 0 && !loadingMachines && (
            <MenuItem disabled>No hay máquinas registradas</MenuItem>
          )}
        </Select>
      </FormControl>

      {/* Optimization strategy */}
      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
        <InputLabel>Estrategia de optimización</InputLabel>
        <Select
          value={config.optimizationStrategy}
          onChange={(e) => set('optimizationStrategy', e.target.value)}
          label="Estrategia de optimización"
        >
          {STRATEGIES.map((s) => (
            <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Production volume */}
      <Typography variant="caption" color="text.secondary">
        Volumen de producción: <strong>{config.productionVolume} pza{config.productionVolume > 1 ? 's' : '.'}</strong>
      </Typography>
      <Slider
        value={config.productionVolume}
        onChange={(_, v) => set('productionVolume', v)}
        min={1} max={1000} step={1}
        marks={[{ value: 1, label: '1' }, { value: 100, label: '100' }, { value: 500, label: '500' }, { value: 1000, label: '1000' }]}
        sx={{ mb: 2 }}
      />

      {/* Tolerance class */}
      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
        <InputLabel>Clase de tolerancia</InputLabel>
        <Select
          value={config.toleranceClass}
          onChange={(e) => set('toleranceClass', e.target.value)}
          label="Clase de tolerancia"
        >
          <MenuItem value="coarse">Gruesa (&gt; ±0.5 mm)</MenuItem>
          <MenuItem value="standard">Estándar (±0.1–0.5 mm)</MenuItem>
          <MenuItem value="fine">Fina (±0.05–0.1 mm)</MenuItem>
          <MenuItem value="precision">Precisión (&lt; ±0.05 mm)</MenuItem>
        </Select>
      </FormControl>

      {/* Surface finish (optional) */}
      <TextField
        label="Acabado superficial (opcional)"
        value={config.surfaceFinish}
        onChange={(e) => set('surfaceFinish', e.target.value)}
        fullWidth size="small" sx={{ mb: 3 }}
        placeholder="ej. Ra 1.6"
        InputProps={{ endAdornment: <InputAdornment position="end">μm</InputAdornment> }}
      />

      {/* Generate */}
      <Button
        variant="contained"
        color="primary"
        fullWidth
        size="large"
        onClick={handleGeneratePlan}
        disabled={isGenerating || !config.machineId}
        startIcon={isGenerating ? <CircularProgress size={20} /> : <Build />}
      >
        {isGenerating ? 'Generando plan...' : 'Generar plan de fabricación'}
      </Button>

      {error && (
        <Alert severity="error" sx={{ mt: 2 }} onClose={() => setError(null)}>{error}</Alert>
      )}
      {success && (
        <Alert severity="success" sx={{ mt: 2 }} onClose={() => setSuccess(null)}>{success}</Alert>
      )}
    </Box>
  );
}
