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
    const updates = { label, level, properties: props };
    if (nodeType === 'GEOMETRY' && props.tier != null) {
      updates.tier = props.tier;
    }
    updateNode(node.id, updates);
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
            <TextField
              label="ID de malla CAE"
              size="small" fullWidth
              value={props.mesh_id || ''}
              onChange={e => setProp('mesh_id', e.target.value)}
              placeholder="UUID de CAEMesh"
              helperText="Opcional: vincula a una malla existente"
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
              FormHelperTextProps={{ style: { color: '#666', fontSize: 11 } }}
            />
            <TextField
              label="ID de archivo STEP"
              size="small" fullWidth
              value={props.step_file_id || ''}
              onChange={e => setProp('step_file_id', e.target.value)}
              placeholder="UUID de STEPFile"
              helperText="Opcional: origen STEP file"
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
              FormHelperTextProps={{ style: { color: '#666', fontSize: 11 } }}
            />
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
              label="Nombre del conjunto de nodos (node_set)"
              size="small" fullWidth
              value={props.node_set || ''}
              onChange={e => setProp('node_set', e.target.value)}
              placeholder="ej: fixed_base"
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
            />
            <Box>
              <Typography variant="caption" sx={{ color: '#888', mb: 0.5, display: 'block' }}>
                Grados de libertad restringidos:
              </Typography>
              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0.5 }}>
                {[['UX', 0], ['UY', 1], ['UZ', 2], ['RX', 3], ['RY', 4], ['RZ', 5]].map(([lbl, idx]) => {
                  const dofs = props.dofs || [];
                  const checked = dofs.includes(idx);
                  return (
                    <Box
                      key={lbl}
                      onClick={() => {
                        const newDofs = checked ? dofs.filter(d => d !== idx) : [...dofs, idx].sort();
                        setProp('dofs', newDofs);
                      }}
                      sx={{
                        p: 0.5,
                        border: `1px solid ${checked ? '#4caf50' : '#555'}`,
                        borderRadius: 0.5,
                        cursor: 'pointer',
                        bgcolor: checked ? '#1b5e20' : '#222',
                        color: checked ? '#81c784' : '#888',
                        fontSize: 12,
                        textAlign: 'center',
                        fontWeight: checked ? 700 : 400,
                        transition: 'all 0.15s',
                        '&:hover': { bgcolor: checked ? '#2e7d32' : '#333' },
                      }}
                    >
                      {lbl}
                    </Box>
                  );
                })}
              </Box>
            </Box>
            <TextField
              label="Valor prescrito (displacement)"
              size="small" fullWidth type="number"
              value={props.value ?? 0}
              onChange={e => setProp('value', parseFloat(e.target.value))}
              placeholder="0"
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
            />
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
              label="Nombre del conjunto de nodos (node_set)"
              size="small" fullWidth
              value={props.node_set || ''}
              onChange={e => setProp('node_set', e.target.value)}
              placeholder="ej: tip"
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
            />
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
            <Box sx={{ bgcolor: '#1b3a1b', border: '1px solid #2e7d32', borderRadius: 0.5, p: 1 }}>
              <Typography variant="caption" sx={{ color: '#81c784', fontSize: 11 }}>
                Vector de fuerza:
              </Typography>
              <Typography variant="caption" sx={{ color: '#a5d6a7', fontFamily: 'monospace', display: 'block', fontSize: 10, mt: 0.25 }}>
                F = [{((props.magnitude ?? 0) * (props.dir_x ?? 0)).toFixed(1)}, {((props.magnitude ?? 0) * (props.dir_y ?? 0)).toFixed(1)}, {((props.magnitude ?? 0) * (props.dir_z ?? -1)).toFixed(1)}]
              </Typography>
            </Box>
          </>
        )}

        {nodeType === 'RESULT' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Box sx={{ bgcolor: '#0d1b0d', border: '1px solid #2e7d32', borderRadius: 1, p: 1 }}>
              {props.run_id ? (
                <>
                  <Typography variant="caption" sx={{ color: '#81c784', fontWeight: 700, display: 'block', mb: 0.5 }}>
                    ✓ Simulación completada
                  </Typography>
                  {[
                    ['run_id', 'Run ID'],
                    ['max_von_mises_mpa', 'σ_max von Mises [MPa]'],
                    ['max_displacement_mm', 'Desplazamiento máx [mm]'],
                    ['safety_factor', 'Factor de seguridad'],
                  ].map(([k, lbl]) => props[k] != null && (
                    <Box key={k} sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.25 }}>
                      <Typography variant="caption" sx={{ color: '#888', fontSize: 10 }}>{lbl}</Typography>
                      <Typography variant="caption" sx={{ color: '#a5d6a7', fontFamily: 'monospace', fontSize: 10 }}>
                        {typeof props[k] === 'number' ? props[k].toFixed(props[k] > 100 ? 2 : 4) : props[k]}
                      </Typography>
                    </Box>
                  ))}
                </>
              ) : (
                <Typography variant="caption" sx={{ color: '#666' }}>
                  Sin resultados — ejecuta una simulación primero
                </Typography>
              )}
            </Box>
          </Box>
        )}

        {nodeType === 'OPTIMIZATION' && (
          <>
            <FormControl size="small" fullWidth>
              <InputLabel sx={{ color: '#888' }}>Objetivo</InputLabel>
              <Select
                value={props.objective || 'minimize_mass'}
                onChange={e => setProp('objective', e.target.value)}
                label="Objetivo"
                sx={{ color: '#fff' }}
              >
                {['minimize_mass', 'minimize_compliance', 'maximize_stiffness'].map(t => (
                  <MenuItem key={t} value={t}>{t.replace(/_/g, ' ')}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel sx={{ color: '#888' }}>Tipo de restricción</InputLabel>
              <Select
                value={props.constraint_type || 'volume_fraction'}
                onChange={e => setProp('constraint_type', e.target.value)}
                label="Tipo de restricción"
                sx={{ color: '#fff' }}
              >
                {['volume_fraction', 'stress_limit', 'displacement_limit'].map(t => (
                  <MenuItem key={t} value={t}>{t.replace(/_/g, ' ')}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Valor de restricción"
              size="small" fullWidth type="number"
              value={props.constraint_value ?? 0.5}
              onChange={e => setProp('constraint_value', parseFloat(e.target.value))}
              placeholder="0.5 (50% de volumen)"
              inputProps={{ style: { color: '#fff' } }}
              InputLabelProps={{ style: { color: '#888' } }}
            />
            <FormControl size="small" fullWidth>
              <InputLabel sx={{ color: '#888' }}>Método</InputLabel>
              <Select
                value={props.method || 'SIMP'}
                onChange={e => setProp('method', e.target.value)}
                label="Método"
                sx={{ color: '#fff' }}
              >
                {['SIMP', 'level_set', 'topopt'].map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </Select>
            </FormControl>
          </>
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
