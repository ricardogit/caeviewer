import React, { useEffect, useMemo, useState } from 'react';
import {
  Box, Paper, Typography, Select, MenuItem, TextField, Button, Alert, LinearProgress, Divider, IconButton, Tooltip,
} from '@mui/material';
import { Delete, ExpandLess, ExpandMore } from '@mui/icons-material';
import useGeoMapStore from '../../stores/geoMapStore';
import useDesignStore from '../../stores/designStore';
import { SEGMENT_KINDS, SEGMENT_STYLE, domainSpec, fmtLen } from '../../utils/geoDomain';

/**
 * Right panel of the Mapa mode: boundary kind per edge, points of interest, mesh parameters, mesh generation
 * (job geo.mesh2d) with its statistics, and the link to the open study (GEOMETRY node shape domain_2d).
 */
const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
const MESH_FIELDS = [
  ['h_min', 'h mín [m]', 'Tamaño mínimo de elemento'],
  ['h_max', 'h máx [m]', 'Tamaño máximo de elemento'],
  ['wavelength_points', 'Elem. por λ de marea', '√(g·h)·T / N: más resolución en aguas someras (0 = no)'],
  ['slope_factor', 'Factor de pendiente', 'β·h/|∇h|: refina taludes (0 = no; 3–10 típico)'],
  ['growth', 'Crecimiento', 'Gradiente máximo del tamaño |∇h| (0.1–0.4)'],
  ['poi_size', 'h en puntos [m]', 'Tamaño junto a los puntos del conjunto de puntos'],
  ['max_elements', 'Máx. triángulos', 'Límite estimado antes de mallar (por defecto 300 000)'],
];

function StudyLink() {
  const graphId = useDesignStore((s) => s.activeGraphId);
  const meta = useDesignStore((s) => s.activeGraphMeta);
  const nodes = useDesignStore((s) => s.graphData.nodes);
  const d = useGeoMapStore((s) => s.d);
  const dirty = useGeoMapStore((s) => s.dirty);
  const meshKey = useGeoMapStore((s) => s.meshKey);
  const { loadFromNode, markSaved } = useGeoMapStore.getState();
  const [saving, setSaving] = useState(false);
  const geoNode = useMemo(() => nodes.find((n) => n.data?.node_type === 'GEOMETRY'), [nodes]);
  const isDomain = geoNode?.data?.properties?.shape === 'domain_2d';

  useEffect(() => {          // opening the Mapa mode on a study with a domain loads it
    if (isDomain) loadFromNode(geoNode);
  }, [graphId, isDomain]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!graphId) return <Typography sx={{ fontSize: 12, color: '#888' }}>Abra un estudio (modo Design) para guardar el dominio en él.</Typography>;
  const save = async () => {
    setSaving(true);
    const properties = { shape: 'domain_2d', ...domainSpec(d), mesh_key: meshKey || null, tier: geoNode?.data?.properties?.tier ?? 1 };
    const st = useDesignStore.getState();
    if (geoNode) await st.updateNode(geoNode.id, { properties });
    else await st.addNode('GEOMETRY', 'Dominio 2D', { x: 80, y: 80 }, properties);
    markSaved();
    setSaving(false);
  };
  return (
    <Box>
      <Typography sx={{ fontSize: 12, color: '#bbb' }}>
        Estudio <b>{meta?.name}</b>{geoNode ? ` · GEOMETRY «${geoNode.data.label}»${isDomain ? ' (dominio 2D)' : ' (otra geometría: se reemplazará)'}` : ' · sin GEOMETRY'}
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, mt: 0.75 }}>
        <Button size="small" variant="contained" disabled={saving || d.domain.length < 3} onClick={save} sx={{ textTransform: 'none' }}>
          {geoNode ? 'Guardar en el estudio' : 'Crear GEOMETRY en el estudio'}{dirty ? ' •' : ''}
        </Button>
        {isDomain && <Button size="small" onClick={() => loadFromNode(geoNode)} sx={{ textTransform: 'none' }}>Recargar</Button>}
      </Box>
    </Box>
  );
}

export default function DomainPanel() {
  const d = useGeoMapStore((s) => s.d);
  const selectedEdge = useGeoMapStore((s) => s.selectedEdge);
  const mesh = useGeoMapStore((s) => s.mesh);
  const meshJob = useGeoMapStore((s) => s.meshJob);
  const meshError = useGeoMapStore((s) => s.meshError);
  const { setSegment, selectEdge, setMesh, updatePoint, removePoint, generateMesh, clearDomain, clearError } = useGeoMapStore.getState();
  const [open, setOpen] = useState(true);
  const st = mesh?.stats;

  return (
    <Paper sx={{ position: 'absolute', top: 10, right: 10, zIndex: 1000, width: 330, maxHeight: 'calc(100% - 60px)', overflowY: 'auto', bgcolor: 'rgba(28,28,28,0.95)', color: '#ddd', p: 1.25 }} data-testid="domain-panel">
      <Box sx={{ display: 'flex', alignItems: 'center' }}>
        <Typography sx={{ fontWeight: 600, fontSize: 14, flex: 1 }}>Dominio 2D</Typography>
        <IconButton size="small" onClick={() => setOpen(!open)}>{open ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}</IconButton>
      </Box>
      {open && (
        <>
          {d.domain.length < 3 ? (
            <Typography sx={{ fontSize: 12, color: '#999', my: 1 }}>Use «Dibujar dominio» y haga clic en el mapa. La tierra de las capas de costa marcadas se resta; las islas quedan como huecos.</Typography>
          ) : (
            <>
              <Typography sx={{ fontSize: 12, color: '#90caf9', mt: 1 }}>{`Contornos (${d.domain.length} lados)`}</Typography>
              {d.segments.map((k, i) => (
                <Box key={i} onClick={() => selectEdge(i)} sx={{ display: 'flex', gap: 0.5, alignItems: 'center', mt: 0.5, p: 0.25, borderRadius: 1, bgcolor: selectedEdge === i ? 'rgba(255,235,59,0.12)' : 'transparent' }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: SEGMENT_STYLE[k].color, flexShrink: 0 }} />
                  <TextField size="small" variant="standard" placeholder={`Lado ${i + 1}`} value={d.segment_labels[i] || ''}
                    onChange={(e) => setSegment(i, { label: e.target.value })} sx={{ flex: 1 }} InputProps={{ sx: { fontSize: 12 } }} />
                  <Select size="small" variant="standard" value={k} onChange={(e) => setSegment(i, { kind: e.target.value })} sx={{ fontSize: 12, width: 112 }}>
                    {SEGMENT_KINDS.map((s) => <MenuItem key={s} value={s} sx={{ fontSize: 12 }}>{SEGMENT_STYLE[s].label}</MenuItem>)}
                  </Select>
                </Box>
              ))}
              <Typography sx={{ fontSize: 10.5, color: '#888', mt: 0.5 }}>Donde un lado cruza tierra, esa parte pasa a ser «Costa».</Typography>
              <Button size="small" color="warning" onClick={clearDomain} sx={{ textTransform: 'none', mt: 0.5 }}>Borrar polígono</Button>
            </>
          )}

          {d.points.length > 0 && (
            <>
              <Typography sx={{ fontSize: 12, color: '#90caf9', mt: 1 }}>Puntos de interés</Typography>
              {d.points.map((p, i) => (
                <Box key={i} sx={{ display: 'flex', gap: 0.5, alignItems: 'center', mt: 0.5 }}>
                  <TextField size="small" variant="standard" value={p.label} onChange={(e) => updatePoint(i, { label: e.target.value })} sx={{ flex: 1 }} InputProps={{ sx: { fontSize: 12 } }} />
                  <TextField size="small" variant="standard" type="number" placeholder="h mín" value={p.size ?? ''}
                    onChange={(e) => updatePoint(i, { size: num(e.target.value) })} sx={{ width: 70 }} InputProps={{ sx: { fontSize: 12 }, endAdornment: <span style={{ fontSize: 10, color: '#888' }}>m</span> }} />
                  <IconButton size="small" onClick={() => removePoint(i)}><Delete fontSize="inherit" /></IconButton>
                </Box>
              ))}
            </>
          )}

          <Divider sx={{ my: 1, borderColor: '#333' }} />
          <Typography sx={{ fontSize: 12, color: '#90caf9' }}>Malla (triángulos, Gmsh)</Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, mt: 0.75 }}>
            {MESH_FIELDS.map(([k, l, help]) => (
              <Tooltip key={k} title={help} placement="left">
                <TextField size="small" type="number" label={l} value={d.mesh?.[k] ?? ''} onChange={(e) => setMesh({ [k]: num(e.target.value) })}
                  InputProps={{ sx: { fontSize: 12 } }} InputLabelProps={{ sx: { fontSize: 11 }, shrink: true }} />
              </Tooltip>
            ))}
          </Box>
          <Typography sx={{ fontSize: 10.5, color: '#888', mt: 0.5 }}>
            {`Batimetría: ${d.bathymetry_datasets.length ? `${d.bathymetry_datasets.length} capa(s)` : 'ninguna (profundidad mínima)'} · tierra: ${d.land_datasets.length} capa(s)${d.zone_dataset ? ' · zonas' : ''}`}
          </Typography>
          <Button fullWidth size="small" variant="contained" color="success" sx={{ mt: 1, textTransform: 'none' }}
            disabled={d.domain.length < 3 || !!meshJob} onClick={generateMesh}>Generar malla</Button>
          {meshJob && (
            <Box sx={{ mt: 1 }}>
              <LinearProgress variant={meshJob.progress ? 'determinate' : 'indeterminate'} value={meshJob.progress || 0} />
              <Typography sx={{ fontSize: 11, color: '#aaa' }}>{meshJob.message}</Typography>
            </Box>
          )}
          {meshError && <Alert severity="error" onClose={clearError} sx={{ mt: 1, fontSize: 12 }}>{meshError}</Alert>}
          {st && (
            <Box sx={{ mt: 1, fontSize: 11.5, color: '#ccc' }} data-testid="mesh-stats">
              <div>{`${st.n_nodes.toLocaleString()} nodos · ${st.n_elements.toLocaleString()} triángulos`}</div>
              <div>{`Agua ${(st.area_m2 / 1e6).toFixed(2)} km² · ${st.n_holes} isla(s) · UTM EPSG:${st.frame?.epsg}`}</div>
              <div>{`Lados ${fmtLen(st.h_min_m)} – ${fmtLen(st.h_max_m)} · ángulo mín ${st.min_angle_deg.toFixed(1)}°`}</div>
              {st.depth_max_m != null && <div>{`Profundidad ${st.depth_min_m.toFixed(1)} – ${st.depth_max_m.toFixed(1)} m`}</div>}
              {st.has_bathymetry === false && <div style={{ color: '#ffb74d' }}>Sin batimetría: el tamaño usa la profundidad mínima y los nodos no tienen profundidad.</div>}
              {st.nodes_without_depth > 0 && <div style={{ color: '#ffb74d' }}>{`${st.nodes_without_depth} nodos fuera de la batimetría (valor del vecino)`}</div>}
              {st.points_outside_water > 0 && <div style={{ color: '#ffb74d' }}>{`${st.points_outside_water} punto(s) fuera del agua`}</div>}
              <Box sx={{ mt: 0.5 }}>
                {(mesh.boundary_info || []).map((b) => (
                  <Box key={b.id} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 10, height: 3, bgcolor: SEGMENT_STYLE[b.kind]?.color }} />
                    <span style={{ flex: 1 }}>{b.label}</span>
                    <span style={{ color: '#999' }}>{fmtLen(b.length_m)}</span>
                  </Box>
                ))}
              </Box>
              <Button size="small" href={`/api/geodata/mesh/${mesh.key}?format=npz`} sx={{ textTransform: 'none', mt: 0.5, px: 0 }}>Descargar malla (.npz)</Button>
            </Box>
          )}
          <Divider sx={{ my: 1, borderColor: '#333' }} />
          <StudyLink />
          <Typography sx={{ fontSize: 10.5, color: '#777', mt: 1 }}>El solver 2D (aguas someras, FASE 10.3) usará este dominio y sus contornos.</Typography>
        </>
      )}
    </Paper>
  );
}
