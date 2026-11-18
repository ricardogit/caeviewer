import React, { useEffect, useMemo } from 'react';
import {
  MapContainer, TileLayer, GeoJSON, ImageOverlay, Polyline, Polygon, Marker, CircleMarker, Tooltip, useMap,
  useMapEvents, ScaleControl,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Box, Button, ButtonGroup, Chip, Paper, Typography } from '@mui/material';
import useGeoMapStore from '../../stores/geoMapStore';
import { SEGMENT_STYLE, edges } from '../../utils/geoDomain';
import MeshCanvasLayer from './MeshCanvasLayer';

/**
 * Mapa mode viewport (FASE 10.5): OSM base map (VITE_MAP_TILES overrides the tile URL), dataset layers, the
 * 2D domain (draw: click vertices, double click / «Cerrar» closes; drag vertices; right click removes one;
 * click an edge to select it — Alt+click inserts a vertex), points of interest and the generated mesh.
 */
const TILES = import.meta.env.VITE_MAP_TILES || 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const ATTRIB = import.meta.env.VITE_MAP_ATTRIBUTION || '&copy; colaboradores de OpenStreetMap';
const KIND_STYLE = {
  coastline: { color: '#8d6e63', weight: 1, fillColor: '#d7ccc8', fillOpacity: 0.55 },
  zones: { color: '#ab47bc', weight: 1, fillOpacity: 0.12, dashArray: '4 3' },
  bathymetry: { color: '#1e88e5', weight: 1, fillOpacity: 0, dashArray: '2 4' },
};

const vertexIcon = (selected) => L.divIcon({
  className: '',
  html: `<div style="width:12px;height:12px;border-radius:50%;background:${selected ? '#ffeb3b' : '#fff'};`
    + 'border:2px solid #1565c0;box-sizing:border-box"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});
const pointIcon = L.divIcon({
  className: '',
  html: '<div style="width:14px;height:14px;transform:rotate(45deg);background:#ef5350;border:2px solid #fff;'
    + 'box-sizing:border-box"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

function ClickHandler() {
  const tool = useGeoMapStore((s) => s.tool);
  const addDrawVertex = useGeoMapStore((s) => s.addDrawVertex);
  const finishDrawing = useGeoMapStore((s) => s.finishDrawing);
  const addPoint = useGeoMapStore((s) => s.addPoint);
  const map = useMapEvents({
    click: (e) => {
      const ll = [e.latlng.lng, e.latlng.lat];
      if (tool === 'draw') addDrawVertex(ll);
      else if (tool === 'point') addPoint(ll);
    },
    dblclick: () => { if (tool === 'draw') finishDrawing(); },
  });
  useEffect(() => {
    if (tool === 'draw') map.doubleClickZoom.disable();
    else map.doubleClickZoom.enable();
    map.getContainer().style.cursor = tool === 'pan' ? '' : 'crosshair';
  }, [tool, map]);
  return null;
}

/** Fit the view once to the domain, or to the first dataset, when they appear. */
function FitOnce({ bounds }) {
  const map = useMap();
  const key = bounds ? bounds.flat().map((v) => v.toFixed(4)).join(',') : '';
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [30, 30] });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function DatasetLayers() {
  const datasets = useGeoMapStore((s) => s.datasets);
  const visible = useGeoMapStore((s) => s.visible);
  const layers = useGeoMapStore((s) => s.layers);
  return datasets.filter((ds) => visible[ds.id]).map((ds) => {
    if (ds.kind === 'bathymetry' && ds.has_preview && ds.bbox) {
      const [w, s, e, n] = ds.bbox;
      return <ImageOverlay key={ds.id} url={`/api/geodata/${ds.id}/preview.png`} bounds={[[s, w], [n, e]]} opacity={0.7} />;
    }
    const fc = layers[ds.id];
    if (!fc) return null;
    if (ds.kind === 'points' || (ds.kind === 'bathymetry' && fc.features?.[0]?.geometry?.type === 'Point')) {
      return fc.features.map((f, i) => (
        <CircleMarker key={`${ds.id}-${i}`} center={[f.geometry.coordinates[1], f.geometry.coordinates[0]]}
          radius={ds.kind === 'points' ? 6 : 2} pathOptions={{ color: ds.kind === 'points' ? '#ff7043' : '#1e88e5', weight: 1 }}>
          {ds.kind === 'points' && <Tooltip>{f.properties?.name || `${ds.name} ${i + 1}`}</Tooltip>}
          {ds.kind === 'bathymetry' && <Tooltip>{`${f.properties.depth.toFixed(1)} m`}</Tooltip>}
        </CircleMarker>
      ));
    }
    return <GeoJSON key={ds.id} data={fc} style={KIND_STYLE[ds.kind] || {}} />;
  });
}

function DomainLayer() {
  const d = useGeoMapStore((s) => s.d);
  const tool = useGeoMapStore((s) => s.tool);
  const drawing = useGeoMapStore((s) => s.drawing);
  const selectedEdge = useGeoMapStore((s) => s.selectedEdge);
  const { moveVertex, removeVertex, insertVertex, selectEdge, updatePoint, removePoint } = useGeoMapStore.getState();
  const segs = useMemo(() => (d.domain.length >= 3 ? edges(d.domain) : []), [d.domain]);
  return (
    <>
      {drawing.length > 0 && (
        <Polyline positions={drawing.map(([lon, lat]) => [lat, lon])} pathOptions={{ color: '#ffeb3b', dashArray: '6 4' }} />
      )}
      {drawing.map(([lon, lat], i) => (
        <CircleMarker key={`dv${i}`} center={[lat, lon]} radius={4} pathOptions={{ color: '#ffeb3b' }} />
      ))}
      {segs.length > 0 && (
        <Polygon positions={d.domain.map(([lon, lat]) => [lat, lon])} pathOptions={{ stroke: false, fillColor: '#4fc3f7', fillOpacity: 0.08 }} interactive={false} />
      )}
      {segs.map(([a, b], i) => (
        <Polyline key={`e${i}`} positions={[[a[1], a[0]], [b[1], b[0]]]}
          pathOptions={{ color: SEGMENT_STYLE[d.segments[i]]?.color || '#fff', weight: selectedEdge === i ? 7 : 4, opacity: 0.95 }}
          eventHandlers={{
            click: (e) => {
              L.DomEvent.stopPropagation(e);
              if (tool !== 'pan') return;
              if (e.originalEvent.altKey) insertVertex(i, [e.latlng.lng, e.latlng.lat]);
              else selectEdge(i);
            },
          }}>
          <Tooltip sticky>{`${d.segment_labels[i] || `Lado ${i + 1}`} · ${SEGMENT_STYLE[d.segments[i]]?.label}`}</Tooltip>
        </Polyline>
      ))}
      {tool === 'pan' && d.domain.map(([lon, lat], i) => (
        <Marker key={`v${i}-${d.domain.length}`} position={[lat, lon]} draggable icon={vertexIcon(selectedEdge === i)}
          eventHandlers={{
            dragend: (e) => { const p = e.target.getLatLng(); moveVertex(i, [p.lng, p.lat]); },
            contextmenu: () => removeVertex(i),
          }} />
      ))}
      {d.points.map((p, i) => (
        <Marker key={`p${i}-${d.points.length}`} position={[p.lat, p.lon]} draggable icon={pointIcon}
          eventHandlers={{
            dragend: (e) => { const q = e.target.getLatLng(); updatePoint(i, { lon: q.lng, lat: q.lat }); },
            contextmenu: () => removePoint(i),
          }}>
          <Tooltip>{`${p.label}${p.size ? ` · ${p.size} m` : ''}`}</Tooltip>
        </Marker>
      ))}
    </>
  );
}

function Toolbar() {
  const tool = useGeoMapStore((s) => s.tool);
  const drawing = useGeoMapStore((s) => s.drawing);
  const setTool = useGeoMapStore((s) => s.setTool);
  const finishDrawing = useGeoMapStore((s) => s.finishDrawing);
  const undoDrawVertex = useGeoMapStore((s) => s.undoDrawVertex);
  const hasMesh = useGeoMapStore((s) => !!s.mesh);
  const showMesh = useGeoMapStore((s) => s.showMesh);
  const setShowMesh = useGeoMapStore((s) => s.setShowMesh);
  const hint = {
    pan: 'Arrastre vértices · clic derecho borra · clic en un lado lo selecciona · Alt+clic inserta vértice',
    draw: 'Clic añade vértices · doble clic o «Cerrar» termina',
    point: 'Clic añade un punto de interés (vertido, playa, mareógrafo)',
  }[tool];
  return (
    <Paper sx={{ position: 'absolute', top: 10, left: 54, zIndex: 1000, p: 0.75, bgcolor: 'rgba(30,30,30,0.92)', display: 'flex', alignItems: 'center', gap: 1 }}>
      <ButtonGroup size="small" variant="outlined">
        {[['pan', 'Mover'], ['draw', 'Dibujar dominio'], ['point', 'Punto']].map(([k, l]) => (
          <Button key={k} variant={tool === k ? 'contained' : 'outlined'} onClick={() => setTool(k)} sx={{ textTransform: 'none' }}>{l}</Button>
        ))}
      </ButtonGroup>
      {tool === 'draw' && (
        <>
          <Button size="small" onClick={undoDrawVertex} disabled={!drawing.length} sx={{ textTransform: 'none' }}>Deshacer</Button>
          <Button size="small" variant="contained" color="success" onClick={finishDrawing} disabled={drawing.length < 3} sx={{ textTransform: 'none' }}>
            Cerrar ({drawing.length})
          </Button>
        </>
      )}
      {hasMesh && (
        <Chip size="small" label={showMesh ? 'Ocultar malla' : 'Mostrar malla'} onClick={() => setShowMesh(!showMesh)} />
      )}
      <Typography sx={{ fontSize: 11, color: '#aaa', maxWidth: 360 }}>{hint}</Typography>
    </Paper>
  );
}

function Legend() {
  return (
    <Paper sx={{ position: 'absolute', bottom: 40, left: 10, zIndex: 1000, p: 1, bgcolor: 'rgba(30,30,30,0.9)' }}>
      {Object.entries(SEGMENT_STYLE).map(([k, s]) => (
        <Box key={k} sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
          <Box sx={{ width: 18, height: 4, bgcolor: s.color }} />
          <Typography sx={{ fontSize: 11, color: '#ddd' }}>{s.label}</Typography>
        </Box>
      ))}
    </Paper>
  );
}

export default function MapView() {
  const d = useGeoMapStore((s) => s.d);
  const datasets = useGeoMapStore((s) => s.datasets);
  const mesh = useGeoMapStore((s) => s.mesh);
  const showMesh = useGeoMapStore((s) => s.showMesh);
  const bounds = useMemo(() => {
    if (d.domain.length >= 3) {
      const lons = d.domain.map((v) => v[0]);
      const lats = d.domain.map((v) => v[1]);
      return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
    }
    const ds = datasets.find((x) => x.bbox);
    return ds ? [[ds.bbox[1], ds.bbox[0]], [ds.bbox[3], ds.bbox[2]]] : null;
  }, [d.domain.length > 0, datasets.length]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Box sx={{ width: '100%', height: '100%', position: 'relative' }} data-testid="map-view">
      <MapContainer center={[40, -4]} zoom={5} style={{ width: '100%', height: '100%' }} preferCanvas>
        <TileLayer url={TILES} attribution={ATTRIB} maxZoom={19} />
        <ScaleControl position="bottomleft" imperial={false} />
        <DatasetLayers />
        {mesh && showMesh && <MeshCanvasLayer mesh={mesh} />}
        <DomainLayer />
        <ClickHandler />
        <FitOnce bounds={bounds} />
      </MapContainer>
      <Toolbar />
      <Legend />
    </Box>
  );
}
