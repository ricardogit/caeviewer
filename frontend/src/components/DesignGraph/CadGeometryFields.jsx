/**
 * CadGeometryFields — GEOMETRY node → versioned CAD geometry + meshing parameters (FASE 2).
 * The solver meshes the BREP with Gmsh (cached) and maps every CAD face to a face set.
 */
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { FormControl, InputLabel, MenuItem, Select, TextField, Typography } from '@mui/material';

const inputStyle = { style: { color: '#fff' } };
const labelStyle = { style: { color: '#888' } };

export default function CadGeometryFields({ props, setProp }) {
  const [geometries, setGeometries] = useState([]);
  useEffect(() => {
    axios.get('/api/geometry').then(({ data }) => setGeometries(data.geometries || [])).catch(() => setGeometries([]));
  }, []);

  const current = props.geometry_id;
  const known = geometries.some((g) => g.id === current);
  return (
    <>
      <FormControl size="small" fullWidth>
        <InputLabel sx={{ color: '#888' }}>Geometría CAD</InputLabel>
        <Select
          value={current || ''}
          label="Geometría CAD"
          onChange={(e) => setProp('geometry_id', e.target.value || undefined)}
          sx={{ color: '#fff' }}
        >
          <MenuItem value=""><em>Ninguna (malla CAE o viga de prueba)</em></MenuItem>
          {current && !known && <MenuItem value={current}>{current.slice(0, 8)}… (otra versión)</MenuItem>}
          {geometries.map((g) => (
            <MenuItem key={g.id} value={g.id} disabled={g.status !== 'ready'}>
              {g.name} · v{g.version}{g.status !== 'ready' ? ` (${g.status})` : ` · ${g.n_faces} caras`}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      {current && (
        <>
          <FormControl size="small" fullWidth>
            <InputLabel sx={{ color: '#888' }}>Elemento</InputLabel>
            <Select
              value={props.element_order ?? 2}
              label="Elemento"
              onChange={(e) => setProp('element_order', e.target.value)}
              sx={{ color: '#fff' }}
            >
              <MenuItem value={2}>T10 cuadrático (recomendado)</MenuItem>
              <MenuItem value={1}>T4 lineal (bloquea en flexión)</MenuItem>
            </Select>
          </FormControl>
          <TextField
            label="Tamaño de elemento [mm]"
            size="small" fullWidth type="number"
            value={props.mesh_size_mm ?? ''}
            onChange={(e) => setProp('mesh_size_mm', e.target.value === '' ? undefined : parseFloat(e.target.value))}
            placeholder="automático"
            helperText="Vacío = automático (~15 000 tetraedros). La malla se guarda en caché."
            inputProps={inputStyle}
            InputLabelProps={labelStyle}
            FormHelperTextProps={{ style: { color: '#666', fontSize: 11 } }}
          />
          <Typography variant="caption" sx={{ color: '#666' }}>
            Las condiciones de frontera y cargas se aplican sobre caras de esta geometría.
          </Typography>
        </>
      )}
    </>
  );
}
