/**
 * ExperimentUpload — FASE 8: upload a test of the study.
 *   tensile     σ-ε (or force-displacement) CSV of a specimen of a library material
 *   structural  CSV of sensors on the part: label, x, y, z [mm], quantity (ux|uy|uz|umag|strain),
 *               value [mm | µε], optional std, dx, dy, dz (gauge direction)
 * The file is previewed by the backend before storing (detected columns, points, ranges).
 */
import React, { useEffect, useState } from 'react';
import {
  Box, Typography, Button, TextField, Select, MenuItem, FormControl, InputLabel, Checkbox, FormControlLabel,
  Alert, ToggleButtonGroup, ToggleButton,
} from '@mui/material';
import { UploadFile } from '@mui/icons-material';
import useValidationStore from '../../stores/validationStore';
import useMaterialStore from '../../stores/materialStore';

const tf = { size: 'small', inputProps: { style: { color: '#fff', fontSize: 12 } }, InputLabelProps: { style: { color: '#888' } } };
const sel = { color: '#fff', fontSize: 12, '& .MuiSvgIcon-root': { color: '#888' } };

export const SENSOR_TEMPLATE = 'sensor,x,y,z,quantity,value,std,dx,dy,dz\n'
  + 'LVDT1,500,0,12.5,uy,-0.85,0.01,,,\n'
  + 'G1,60,25,12.5,strain,-410,5,1,0,0\n';

export default function ExperimentUpload({ graphId, defaultMaterialId }) {
  const { previewFile, preview, previewError, clearPreview, upload, busy } = useValidationStore();
  const { materials, list: listMaterials } = useMaterialStore();
  const [testType, setTestType] = useState('structural');
  const [file, setFile] = useState(null);
  const [materialId, setMaterialId] = useState(defaultMaterialId || '');
  const [cond, setCond] = useState({ temperature_c: '', load_factor: '', area_mm2: '', gauge_mm: '' });
  const [description, setDescription] = useState('');
  const [calibrate, setCalibrate] = useState(true);
  const [mode, setMode] = useState('replace');

  useEffect(() => { listMaterials().catch(() => {}); }, [listMaterials]);
  useEffect(() => { if (defaultMaterialId) setMaterialId(defaultMaterialId); }, [defaultMaterialId]);

  const fields = () => ({
    test_type: testType, material_id: testType === 'tensile' ? materialId : undefined, description,
    temperature_c: cond.temperature_c, load_factor: testType === 'structural' ? cond.load_factor : undefined,
    area_mm2: cond.area_mm2, gauge_mm: cond.gauge_mm, calibrate: calibrate ? 1 : 0, mode,
  });

  const choose = (f) => {
    setFile(f);
    if (f) previewFile(f, fields());
    else clearPreview();
  };
  const changeType = (t) => {
    if (!t) return;
    setTestType(t);
    setFile(null);
    clearPreview();
  };
  const submit = async () => {
    const exp = await upload(graphId, file, fields());
    if (exp) {
      setFile(null);
      setDescription('');
    }
  };
  const downloadTemplate = () => {
    const url = URL.createObjectURL(new Blob([SENSOR_TEMPLATE], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'sensores_plantilla.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <ToggleButtonGroup value={testType} exclusive size="small" fullWidth onChange={(_, v) => changeType(v)}
        sx={{ '& .MuiToggleButton-root': { fontSize: 11, textTransform: 'none', py: 0.3 } }}>
        <ToggleButton value="structural">Pieza (sensores)</ToggleButton>
        <ToggleButton value="tensile">Tracción (probeta)</ToggleButton>
      </ToggleButtonGroup>

      {testType === 'tensile' && (
        <FormControl size="small" fullWidth>
          <InputLabel sx={{ color: '#888', fontSize: 12 }}>Material de la biblioteca</InputLabel>
          <Select value={materialId} label="Material de la biblioteca" onChange={(e) => setMaterialId(e.target.value)} sx={sel}>
            {materials.map((m) => <MenuItem key={m.id} value={m.id} sx={{ fontSize: 12 }}>{m.name}</MenuItem>)}
          </Select>
        </FormControl>
      )}

      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
        <Button component="label" size="small" variant="outlined" startIcon={<UploadFile />} sx={{ fontSize: 11 }}>
          {file ? file.name : 'Archivo CSV'}
          <input hidden type="file" accept=".csv,.txt,.tsv,.dat" data-testid="exp-file"
            onChange={(e) => choose(e.target.files?.[0] || null)} />
        </Button>
        {testType === 'structural' && (
          <Button size="small" onClick={downloadTemplate} sx={{ fontSize: 10, textTransform: 'none' }}>Plantilla</Button>
        )}
      </Box>

      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField {...tf} label="T [°C]" value={cond.temperature_c} type="number"
          onChange={(e) => setCond({ ...cond, temperature_c: e.target.value })} />
        {testType === 'structural' ? (
          <TextField {...tf} label="Carga ensayo / carga modelo" value={cond.load_factor} type="number" placeholder="1"
            onChange={(e) => setCond({ ...cond, load_factor: e.target.value })} />
        ) : (
          <>
            <TextField {...tf} label="Área [mm²]" value={cond.area_mm2} type="number"
              onChange={(e) => setCond({ ...cond, area_mm2: e.target.value })} />
            <TextField {...tf} label="L0 [mm]" value={cond.gauge_mm} type="number"
              onChange={(e) => setCond({ ...cond, gauge_mm: e.target.value })} />
          </>
        )}
      </Box>
      <TextField {...tf} label="Descripción" value={description} onChange={(e) => setDescription(e.target.value)} />

      {previewError && <Alert severity="error" sx={{ fontSize: 11, py: 0 }}>{previewError}</Alert>}
      {preview && (
        <Box data-testid="exp-preview" sx={{ bgcolor: '#1a1a1a', p: 0.75, borderRadius: 1 }}>
          {testType === 'tensile' ? (
            <Typography sx={{ color: '#aaa', fontSize: 11 }}>
              {preview.n_points} puntos · columnas {preview.columns?.join(', ')} · ε hasta{' '}
              {(100 * (preview.strain_range?.[1] || 0)).toFixed(1)} % · σ máx. {Number(preview.stress_range_mpa?.[1] || 0).toFixed(0)} MPa
              {preview.notes?.length ? ` · ${preview.notes.join('; ')}` : ''}
            </Typography>
          ) : (
            <Typography sx={{ color: '#aaa', fontSize: 11 }}>
              {preview.n_points} sensores:{' '}
              {Object.values(preview.quantities || {}).map((q) => `${q.n} × ${q.label} [${q.unit}]`).join(', ')}
            </Typography>
          )}
        </Box>
      )}

      <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap' }}>
        <FormControlLabel sx={{ '& .MuiFormControlLabel-label': { color: '#bbb', fontSize: 11 } }}
          control={<Checkbox size="small" checked={calibrate} onChange={(e) => setCalibrate(e.target.checked)} />}
          label={testType === 'tensile' ? 'Recalibrar el material al guardar' : 'Correlacionar con la última simulación'} />
        {testType === 'tensile' && calibrate && (
          <Select size="small" value={mode} onChange={(e) => setMode(e.target.value)} sx={{ ...sel, fontSize: 11, height: 26 }}>
            <MenuItem value="replace" sx={{ fontSize: 11 }}>Reemplazar</MenuItem>
            <MenuItem value="bayes" sx={{ fontSize: 11 }}>Bayesiano (combinar)</MenuItem>
          </Select>
        )}
      </Box>
      <Button variant="contained" size="small" disabled={!file || busy || !preview || (testType === 'tensile' && !materialId)}
        onClick={submit} sx={{ fontSize: 12 }}>
        Guardar ensayo
      </Button>
    </Box>
  );
}
