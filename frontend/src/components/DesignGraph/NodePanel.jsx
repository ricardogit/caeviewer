/**
 * NodePanel — right-side property panel for the selected design node.
 * Shows type-specific form fields and updates node via API.
 */
import React, { useState, useEffect } from 'react';
import {
  Box, Typography, TextField, Select, MenuItem, FormControl, InputLabel,
  Divider, IconButton, Chip, Button, Slider, Tooltip,
} from '@mui/material';
import { Close, Delete } from '@mui/icons-material';
import useDesignStore from '../../stores/designStore';
import { NODE_COLORS } from './GraphEditor';

const MATERIAL_TYPES = [
  'linear_elastic_isotropic', 'linear_elastic_orthotropic',
  'elastoplastic_vonmises', 'hyperelastic_neohookean', 'viscoelastic_maxwell',
  'fourier_isotropic', 'thermoelastic', 'piezoelectric', 'newtonian_fluid',
];

const BC_TYPES = ['fixed', 'pinned', 'roller_x', 'roller_y', 'roller_z', 'symmetry'];
const LOAD_TYPES = ['force', 'pressure', 'torque', 'gravity', 'thermal_flux'];

export default function NodePanel({ node, graphId, onClose }) {
  const { updateNode, deleteNode } = useDesignStore();
  const [label, setLabel] = useState(node.data.label || '');
  const [props, setProps] = useState(node.data.properties || {});
  const [level, setLevel] = useState(node.data.level || 0);
  const [dirty, setDirty] = useState(false);

  const nodeType = node.data.node_type;
  const color = NODE_COLORS[nodeType] || '#888';

  // Reset when selection changes
  useEffect(() => {
    setLabel(node.data.label || '');
    setProps(node.data.properties || {});
    setLevel(node.data.level || 0);
    setDirty(false);
  }, [node.id]);

  const setProp = (key, value) => {
    setProps(p => ({ ...p, [key]: value }));
    setDirty(true);
  };

  const handleSave = () => {
    updateNode(node.id, { label, level, properties: props });
    setDirty(false);
  };

  const handleDelete = () => {
    deleteNode(node.id);
    onClose();
  };

  return (
    <Box
      sx={{
        position: 'absolute', top: 0, right: 0, bottom: 0,
        width: 280,
        bgcolor: '#1a1a1a',
        borderLeft: `2px solid ${color}`,
        zIndex: 20,
        overflow: 'auto',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', px: 1.5, py: 1,
                 borderBottom: '1px solid #333', bgcolor: `${color}18` }}>
        <Chip label={nodeType} size="small"
              sx={{ bgcolor: color, color: '#000', fontWeight: 700, fontSize: 10, mr: 1 }} />
        <Typography variant="subtitle2" sx={{ color: '#fff', flex: 1, fontSize: 13 }}>
          Propiedades
        </Typography>
        <Tooltip title="Eliminar nodo (Delete)">
          <IconButton size="small" onClick={handleDelete} sx={{ color: '#f44336', mr: 0.5 }}>
            <Delete fontSize="small" />
          </IconButton>
        </Tooltip>
        <IconButton size="small" onClick={onClose} sx={{ color: '#888' }}>
          <Close fontSize="small" />
        </IconButton>
      </Box>

      <Box sx={{ p: 1.5, flex: 1, display: 'flex', flexDirection: 'column', gap: 1.5 }}>

        {/* Label */}
        <TextField
          label="Etiqueta"
          value={label}
          onChange={e => { setLabel(e.target.value); setDirty(true); }}
          size="small"
          fullWidth
          inputProps={{ style: { color: '#fff' } }}
          InputLabelProps={{ style: { color: '#888' } }}
          sx={{ '& .MuiOutlinedInput-root': { borderColor: color } }}
        />

        {/* Level */}
        <Box>
          <Typography variant="caption" sx={{ color: '#888' }}>
            Nivel de abstracción: {['Sistema', 'Subsistema', 'Componente', 'Feature'][level]}
          </Typography>
          <Slider
            value={level}
            min={0} max={3} step={1} marks
            onChange={(_, v) => { setLevel(v); setDirty(true); }}
            sx={{ color, mt: 0.5 }}
          />
        </Box>

        <Divider sx={{ borderColor: '#333' }} />

        {/* Type-specific fields */}
        {nodeType === 'CONCEPT' && (
          <TextField
            label="Descripción"
            multiline rows={3}
            value={props.description || ''}
            onChange={e => setProp('description', e.target.value)}
            size="small" fullWidth
            inputProps={{ style: { color: '#fff' } }}
            InputLabelProps={{ style: { color: '#888' } }}
          />
        )}

        {nodeType === 'GEOMETRY' && (
          <>
            <FormControl size="small" fullWidth>
              <InputLabel sx={{ color: '#888' }}>Tipo de representación</InputLabel>
              <Select
                value={props.sdf_func || 'custom'}
                onChange={e => setProp('sdf_func', e.target.value)}
                label="Tipo de representación"
                sx={{ color: '#fff' }}
              >
                {['custom', 'sphere', 'box', 'cylinder', 'torus'].map(t => (
                  <MenuItem key={t} value={t}>{t}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel sx={{ color: '#888' }}>Tier (límite de modelo)</InputLabel>
              <Select
                value={props.tier ?? 1}
                onChange={e => setProp('tier', e.target.value)}
                label="Tier"
                sx={{ color: '#fff' }}
              >
                {[
                  [0, 'Tier 0 — Nano (≤ 5K nodos)'],
                  [1, 'Tier 1 — Interactivo (≤ 100K nodos)'],
                  [2, 'Tier 2 — Estándar (≤ 1M nodos)'],
                  [3, 'Tier 3 — HPC local (≤ 10M nodos)'],
                ].map(([v, lbl]) => <MenuItem key={v} value={v}>{lbl}</MenuItem>)}
              </Select>
            </FormControl>
          </>
        )}

        {nodeType === 'MATERIAL' && (
          <>
            <FormControl size="small" fullWidth>
              <InputLabel sx={{ color: '#888' }}>Modelo constitutivo</InputLabel>
              <Select
                value={props.model_type || 'linear_elastic_isotropic'}
                onChange={e => setProp('model_type', e.target.value)}
                label="Modelo constitutivo"
                sx={{ color: '#fff' }}
              >
                {MATERIAL_TYPES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </Select>
            </FormControl>
            {[['E', 'Módulo de Young [Pa]', 70e9],
              ['nu', 'Coeficiente de Poisson', 0.33],
              ['rho', 'Densidad [kg/m³]', 2700]].map(([k, lbl, def]) => (
              <TextField
                key={k} label={lbl} size="small" fullWidth
                type="number"
                value={props[k] ?? def}
                onChange={e => setProp(k, parseFloat(e.target.value))}
                inputProps={{ style: { color: '#fff' } }}
                InputLabelProps={{ style: { color: '#888' } }}
              />
            ))}
          </>
        )}

        {nodeType === 'BC' && (
          <>
            <FormControl size="small" fullWidth>
              <InputLabel sx={{ color: '#888' }}>Tipo de BC</InputLabel>
              <Select
                value={props.bc_type || 'fixed'}
                onChange={e => setProp('bc_type', e.target.value)}
                label="Tipo de BC"
                sx={{ color: '#fff' }}
              >
                {BC_TYPES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField
              label="Descripción / superficie"
              size="small" fullWidth
              value={props.surface_label || ''}
              onChange={e => setProp('surface_label', e.target.value)}
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
            />
          </>
        )}

        {nodeType === 'LOAD' && (
          <>
            <FormControl size="small" fullWidth>
              <InputLabel sx={{ color: '#888' }}>Tipo de carga</InputLabel>
              <Select
                value={props.load_type || 'force'}
                onChange={e => setProp('load_type', e.target.value)}
                label="Tipo de carga"
                sx={{ color: '#fff' }}
              >
                {LOAD_TYPES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField
              label="Magnitud"
              size="small" fullWidth type="number"
              value={props.magnitude ?? 0}
              onChange={e => setProp('magnitude', parseFloat(e.target.value))}
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
            />
            <TextField
              label="Unidad"
              size="small" fullWidth
              value={props.unit || 'N'}
              onChange={e => setProp('unit', e.target.value)}
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
            />
            <Box sx={{ display: 'flex', gap: 1 }}>
              {['dir_x', 'dir_y', 'dir_z'].map((k, i) => (
                <TextField
                  key={k} label={['Dx', 'Dy', 'Dz'][i]}
                  size="small" type="number"
                  value={props[k] ?? [0, 0, -1][i]}
                  onChange={e => setProp(k, parseFloat(e.target.value))}
                  inputProps={{ style: { color: '#fff', fontSize: 12 } }}
                  InputLabelProps={{ style: { color: '#888', fontSize: 12 } }}
                  sx={{ flex: 1 }}
                />
              ))}
            </Box>
          </>
        )}

        {nodeType === 'RESULT' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            {[
              ['run_id', 'Run ID'],
              ['max_von_mises', 'σ_max von Mises [Pa]'],
              ['max_displacement', 'Desplazamiento máx [m]'],
              ['safety_factor', 'Factor de seguridad'],
            ].map(([k, lbl]) => props[k] != null && (
              <Box key={k} sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Typography variant="caption" sx={{ color: '#888' }}>{lbl}</Typography>
                <Typography variant="caption" sx={{ color: '#00bcd4', fontFamily: 'monospace' }}>
                  {typeof props[k] === 'number' ? props[k].toExponential(3) : props[k]}
                </Typography>
              </Box>
            ))}
            {Object.keys(props).length === 0 && (
              <Typography variant="caption" sx={{ color: '#666' }}>
                Sin resultados — ejecuta una simulación primero
              </Typography>
            )}
          </Box>
        )}
      </Box>

      {/* Save button */}
      {nodeType !== 'RESULT' && (
        <Box sx={{ p: 1.5, borderTop: '1px solid #333' }}>
          <Button
            variant="contained" fullWidth size="small"
            disabled={!dirty}
            onClick={handleSave}
            sx={{ bgcolor: color, '&:hover': { bgcolor: `${color}cc` }, color: '#000', fontWeight: 700 }}
          >
            Guardar cambios
          </Button>
        </Box>
      )}
    </Box>
  );
}
