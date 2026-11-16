import React, { useEffect, useRef, useState } from 'react';
import {
  Box, Typography, Button, Select, MenuItem, TextField, IconButton, Tooltip, Checkbox, Chip, Alert, LinearProgress,
  Divider,
} from '@mui/material';
import { Delete, UploadFile, Visibility, VisibilityOff, ShowChart } from '@mui/icons-material';
import { LineChart, Line, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer } from 'recharts';
import axios from 'axios';
import useGeoMapStore from '../../stores/geoMapStore';

/**
 * Mapa mode sidebar: geographic datasets (FASE 10.5). Upload by kind (format from the extension; CRS when the
 * file does not declare it), show / hide on the map, use in the domain (land, bathymetry priority, zones,
 * points), preview forcings.
 */
export const GEO_KINDS = {
  coastline: { label: 'Costa (tierra)', accept: '.geojson,.json,.kml,.zip', help: 'Polígonos de tierra: GeoJSON, KML o shapefile en .zip (con .prj)' },
  bathymetry: { label: 'Batimetría', accept: '.tif,.tiff,.nc,.nc4,.grd,.xyz,.csv,.txt', help: 'GeoTIFF, NetCDF (GEBCO) o sondas XYZ' },
  zones: { label: 'Zonas', accept: '.geojson,.json,.kml,.zip', help: 'Polígonos con atributos (p. ej. Manning n)' },
  points: { label: 'Puntos', accept: '.geojson,.json,.kml,.zip,.csv', help: 'Vertidos, playas, estaciones: CSV nombre,lon,lat o vectorial' },
  forcing: { label: 'Forzamiento', accept: '.csv,.txt', help: 'Serie temporal (tiempo; valores) o armónicos (constituyente, amplitud, fase)' },
};
const USE_KEY = { coastline: 'land_datasets', bathymetry: 'bathymetry_datasets', points: 'points_datasets' };

function summaryText(ds) {
  const s = ds.summary || {};
  if (ds.kind === 'bathymetry') {
    const g = s.kind === 'grid' ? `rejilla ${s.nx}×${s.ny}` : `${s.n_points} sondas`;
    return `${g} · ${s.depth_min_m?.toFixed(1)}–${s.depth_max_m?.toFixed(1)} m · ${s.convention === 'elevation' ? 'cota (GEBCO)' : 'profundidad'}`;
  }
  if (ds.kind === 'forcing') {
    if (s.kind === 'harmonics') return `armónicos ${s.constituents?.join(' ')} · carrera ≈ ${s.range_m?.toFixed(2)} m`;
    return `serie ${s.n} filas · ${(s.duration_s / 3600).toFixed(1)} h · ${Object.keys(s.columns || {}).join(', ')}`;
  }
  return `${s.n_features} elementos · ${Object.entries(s.geometry_types || {}).map(([k, v]) => `${v} ${k}`).join(', ')}`;
}

function ForcingChart({ id }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    axios.get(`/api/geodata/${id}/series`).then(({ data: d }) => {
      const cols = Object.keys(d.columns);
      setData({ cols, rows: d.t.map((t, i) => ({ h: +(t / 3600).toFixed(2), ...Object.fromEntries(cols.map((c) => [c, d.columns[c][i]])) })) });
    }).catch(() => setData({ cols: [], rows: [] }));
  }, [id]);
  if (!data) return <LinearProgress />;
  const colors = ['#4fc3f7', '#81c784', '#ffb74d'];
  return (
    <Box sx={{ height: 120, mt: 0.5 }}>
      <ResponsiveContainer>
        <LineChart data={data.rows} margin={{ top: 4, right: 6, left: -18, bottom: 0 }}>
          <XAxis dataKey="h" tick={{ fontSize: 9, fill: '#999' }} unit=" h" />
          <YAxis tick={{ fontSize: 9, fill: '#999' }} />
          <RTooltip contentStyle={{ background: '#222', fontSize: 11 }} />
          {data.cols.map((c, i) => <Line key={c} dataKey={c} dot={false} stroke={colors[i % 3]} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </Box>
  );
}

export default function GeoDataList() {
  const datasets = useGeoMapStore((s) => s.datasets);
  const visible = useGeoMapStore((s) => s.visible);
  const uploading = useGeoMapStore((s) => s.uploading);
  const error = useGeoMapStore((s) => s.error);
  const d = useGeoMapStore((s) => s.d);
  const { init, upload, toggleVisible, toggleUse, removeDataset, clearError } = useGeoMapStore.getState();
  const [kind, setKind] = useState('coastline');
  const [crs, setCrs] = useState('');
  const [convention, setConvention] = useState('auto');
  const [timeUnit, setTimeUnit] = useState('s');
  const [chart, setChart] = useState(null);
  const fileRef = useRef(null);

  useEffect(() => { init(); }, [init]);

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    await upload(f, kind, {
      crs: crs.trim() || null,
      convention: kind === 'bathymetry' ? convention : null,
      time_unit: kind === 'forcing' ? timeUnit : null,
    });
  };
  const used = (ds) => (ds.kind === 'zones' ? d.zone_dataset === ds.id : (d[USE_KEY[ds.kind]] || []).includes(ds.id));
  const prio = (ds) => (ds.kind === 'bathymetry' && used(ds) ? d.bathymetry_datasets.indexOf(ds.id) + 1 : null);

  return (
    <Box sx={{ p: 1.5, color: '#ddd', height: '100%', overflowY: 'auto' }} data-testid="geodata-list">
      <Typography sx={{ fontWeight: 600, fontSize: 14, mb: 1 }}>Datos geográficos</Typography>
      <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
        <Select size="small" value={kind} onChange={(e) => setKind(e.target.value)} sx={{ flex: 1, fontSize: 12 }}>
          {Object.entries(GEO_KINDS).map(([k, v]) => <MenuItem key={k} value={k} sx={{ fontSize: 12 }}>{v.label}</MenuItem>)}
        </Select>
        <Button size="small" variant="contained" startIcon={<UploadFile />} disabled={uploading}
          onClick={() => fileRef.current?.click()} sx={{ textTransform: 'none' }}>Subir</Button>
        <input ref={fileRef} type="file" hidden accept={GEO_KINDS[kind].accept} onChange={onFile} data-testid="geodata-file" />
      </Box>
      <Typography sx={{ fontSize: 11, color: '#999', mb: 1 }}>{GEO_KINDS[kind].help}</Typography>
      <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
        {kind !== 'forcing' && (
          <TextField size="small" label="CRS si el archivo no lo indica" placeholder="EPSG:25829" value={crs}
            onChange={(e) => setCrs(e.target.value)} sx={{ flex: 1 }} InputProps={{ sx: { fontSize: 12 } }} InputLabelProps={{ sx: { fontSize: 12 } }} />
        )}
        {kind === 'bathymetry' && (
          <Select size="small" value={convention} onChange={(e) => setConvention(e.target.value)} sx={{ fontSize: 12 }}>
            <MenuItem value="auto" sx={{ fontSize: 12 }}>auto</MenuItem>
            <MenuItem value="depth" sx={{ fontSize: 12 }}>profundidad (+ abajo)</MenuItem>
            <MenuItem value="elevation" sx={{ fontSize: 12 }}>cota (− bajo el mar)</MenuItem>
          </Select>
        )}
        {kind === 'forcing' && (
          <Select size="small" value={timeUnit} onChange={(e) => setTimeUnit(e.target.value)} sx={{ fontSize: 12 }}>
            {['s', 'min', 'h', 'd'].map((u) => <MenuItem key={u} value={u} sx={{ fontSize: 12 }}>tiempo en {u}</MenuItem>)}
          </Select>
        )}
      </Box>
      {uploading && <LinearProgress sx={{ mb: 1 }} />}
      {error && <Alert severity="error" onClose={clearError} sx={{ mb: 1, fontSize: 12 }}>{error}</Alert>}
      <Divider sx={{ my: 1, borderColor: '#333' }} />
      {Object.entries(GEO_KINDS).map(([k, v]) => {
        const list = datasets.filter((ds) => ds.kind === k);
        if (!list.length) return null;
        return (
          <Box key={k} sx={{ mb: 1.5 }}>
            <Typography sx={{ fontSize: 12, color: '#90caf9', mb: 0.5 }}>{v.label}</Typography>
            {list.map((ds) => (
              <Box key={ds.id} sx={{ mb: 0.75, p: 0.75, borderRadius: 1, bgcolor: used(ds) ? 'rgba(33,150,243,0.12)' : 'transparent', border: '1px solid #333' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  {k !== 'forcing' && (
                    <Tooltip title={k === 'bathymetry' ? 'Usar en el dominio (el orden es la prioridad)' : 'Usar en el dominio'}>
                      <Checkbox size="small" checked={used(ds)} onChange={() => toggleUse(ds)} sx={{ p: 0.25 }} />
                    </Tooltip>
                  )}
                  <Typography sx={{ fontSize: 12, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={ds.original_filename}>
                    {ds.name}
                  </Typography>
                  {prio(ds) && <Chip size="small" label={`#${prio(ds)}`} sx={{ height: 18, fontSize: 10 }} />}
                  {k === 'forcing' ? (
                    <IconButton size="small" onClick={() => setChart(chart === ds.id ? null : ds.id)}><ShowChart fontSize="inherit" /></IconButton>
                  ) : (
                    <IconButton size="small" onClick={() => toggleVisible(ds.id)}>
                      {visible[ds.id] ? <Visibility fontSize="inherit" /> : <VisibilityOff fontSize="inherit" />}
                    </IconButton>
                  )}
                  <IconButton size="small" onClick={() => removeDataset(ds.id)}><Delete fontSize="inherit" /></IconButton>
                </Box>
                <Typography sx={{ fontSize: 10.5, color: '#999' }}>{summaryText(ds)}</Typography>
                {ds.source_crs && ds.source_crs.startsWith('EPSG') && ds.source_crs !== 'EPSG:4326' && (
                  <Typography sx={{ fontSize: 10.5, color: '#777' }}>{`origen ${ds.source_crs} → WGS84`}</Typography>
                )}
                {chart === ds.id && <ForcingChart id={ds.id} />}
              </Box>
            ))}
          </Box>
        );
      })}
      {!datasets.length && <Typography sx={{ fontSize: 12, color: '#777' }}>Sin datos. Suba costa y batimetría, o dibuje el dominio directamente sobre el mapa.</Typography>}
    </Box>
  );
}
