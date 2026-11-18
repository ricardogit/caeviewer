/**
 * Mapa mode store (FASE 10.5): geographic datasets (/api/geodata), the 2D water domain being edited, the mesh
 * job (geo.mesh2d via the job queue, progress from socket.io `job_update`) and the link to the study GEOMETRY node.
 */
import { create } from 'zustand';
import axios from 'axios';
import { getSocket } from '../services/socket';
import {
  closeRing, domainFromProps, domainSpec, emptyDomain, insertVertex, moveVertex, removeVertex, selfIntersects,
  setSegment,
} from '../utils/geoDomain';

const API = '/api/geodata';
const err = (e) => e.response?.data?.error || e.message;

const useGeoMapStore = create((set, get) => ({
  datasets: [],
  visible: {},              // dataset id → shown on the map
  layers: {},               // dataset id → GeoJSON (vectors / soundings)
  uploading: false,
  error: null,

  tool: 'pan',              // pan | draw | point
  drawing: [],              // vertices of the ring being drawn
  d: emptyDomain(),         // domain spec being edited
  selectedEdge: null,
  dirty: false,

  meshKey: null,
  mesh: null,               // GET /mesh/<key>
  meshJob: null,            // {id, progress, message, status}
  meshError: null,
  showMesh: true,
  subscribed: false,

  init: async () => {
    if (!get().subscribed) {
      getSocket().on('job_update', (ev) => {
        const job = get().meshJob;
        if (ev.kind !== 'geo.mesh2d' || !job || ev.job_id !== job.id) return;
        set({ meshJob: { ...job, status: ev.status, progress: ev.progress, message: ev.message } });
        if (ev.status === 'done') get().fetchMesh(get().meshKey);
        if (ev.status === 'failed' || ev.status === 'cancelled') {
          set({ meshError: ev.message || 'La generación de la malla falló.' });
          get().pollJob(job.id);
        }
      });
      set({ subscribed: true });
    }
    await get().fetchDatasets();
  },

  fetchDatasets: async () => {
    try {
      const { data } = await axios.get(API);
      set({ datasets: data.datasets, error: null });
    } catch (e) {
      set({ error: err(e) });
    }
  },

  upload: async (file, kind, opts = {}) => {
    const form = new FormData();
    form.append('file', file);
    form.append('kind', kind);
    Object.entries(opts).forEach(([k, v]) => { if (v) form.append(k, v); });
    set({ uploading: true, error: null });
    try {
      const { data } = await axios.post(API, form);
      await get().fetchDatasets();
      get().toggleVisible(data.dataset.id, true);
      return data.dataset;
    } catch (e) {
      set({ error: err(e) });
      return null;
    } finally {
      set({ uploading: false });
    }
  },

  removeDataset: async (id) => {
    try {
      await axios.delete(`${API}/${id}`);
      set((s) => {
        const visible = { ...s.visible };
        delete visible[id];
        const strip = (a) => (a || []).filter((x) => x !== id);
        return {
          visible,
          d: {
            ...s.d, land_datasets: strip(s.d.land_datasets), bathymetry_datasets: strip(s.d.bathymetry_datasets),
            points_datasets: strip(s.d.points_datasets), zone_dataset: s.d.zone_dataset === id ? null : s.d.zone_dataset,
          },
        };
      });
      await get().fetchDatasets();
    } catch (e) {
      set({ error: err(e) });
    }
  },

  toggleVisible: async (id, on) => {
    const show = on ?? !get().visible[id];
    set((s) => ({ visible: { ...s.visible, [id]: show } }));
    const ds = get().datasets.find((x) => x.id === id);
    if (show && ds && !get().layers[id] && !(ds.kind === 'forcing')) {
      try {
        const { data } = await axios.get(`${API}/${id}/geojson`);
        set((s) => ({ layers: { ...s.layers, [id]: data } }));
      } catch (e) {
        set({ error: err(e) });
      }
    }
  },

  /** Use a dataset in the domain (land / bathymetry priority list / zones / points). */
  toggleUse: (ds) => set((s) => {
    const key = { coastline: 'land_datasets', bathymetry: 'bathymetry_datasets', points: 'points_datasets' }[ds.kind];
    if (ds.kind === 'zones') {
      return { d: { ...s.d, zone_dataset: s.d.zone_dataset === ds.id ? null : ds.id }, dirty: true };
    }
    if (!key) return {};
    const list = s.d[key] || [];
    return { d: { ...s.d, [key]: list.includes(ds.id) ? list.filter((x) => x !== ds.id) : [...list, ds.id] }, dirty: true };
  }),

  // ── drawing / editing ──────────────────────────────────────────────────
  setTool: (tool) => set({ tool, drawing: tool === 'draw' ? [] : get().drawing }),
  addDrawVertex: (ll) => set((s) => ({ drawing: [...s.drawing, ll] })),
  undoDrawVertex: () => set((s) => ({ drawing: s.drawing.slice(0, -1) })),
  finishDrawing: () => {
    const v = get().drawing;
    if (v.length < 3) { set({ error: 'El dominio necesita al menos 3 vértices.' }); return; }
    if (selfIntersects(v)) { set({ error: 'El polígono se corta a sí mismo.' }); return; }
    set((s) => ({ d: { ...s.d, ...closeRing(v) }, drawing: [], tool: 'pan', dirty: true, error: null, selectedEdge: null }));
  },
  clearDomain: () => set((s) => ({ d: { ...s.d, domain: [], segments: [], segment_labels: [] }, dirty: true, selectedEdge: null })),
  moveVertex: (i, ll) => set((s) => ({ d: moveVertex(s.d, i, ll), dirty: true })),
  insertVertex: (i, ll) => set((s) => ({ d: insertVertex(s.d, i, ll), dirty: true })),
  removeVertex: (i) => set((s) => ({ d: removeVertex(s.d, i), dirty: true, selectedEdge: null })),
  selectEdge: (i) => set({ selectedEdge: i }),
  setSegment: (i, patch) => set((s) => ({ d: setSegment(s.d, i, patch), dirty: true })),
  setMesh: (patch) => set((s) => ({ d: { ...s.d, mesh: { ...s.d.mesh, ...patch } }, dirty: true })),
  addPoint: (ll) => set((s) => ({
    d: { ...s.d, points: [...s.d.points, { label: `P${s.d.points.length + 1}`, lon: ll[0], lat: ll[1], size: null }] },
    dirty: true,
  })),
  updatePoint: (i, patch) => set((s) => ({ d: { ...s.d, points: s.d.points.map((p, k) => (k === i ? { ...p, ...patch } : p)) }, dirty: true })),
  removePoint: (i) => set((s) => ({ d: { ...s.d, points: s.d.points.filter((_, k) => k !== i) }, dirty: true })),

  // ── mesh ───────────────────────────────────────────────────────────────
  generateMesh: async () => {
    const { d } = get();
    if (d.domain.length < 3) { set({ meshError: 'Dibuje primero el dominio.' }); return; }
    set({ meshError: null, meshJob: null });
    try {
      const { data, status } = await axios.post(`${API}/mesh`, domainSpec(d));
      set({ meshKey: data.key });
      if (status === 200 || data.cached) {
        await get().fetchMesh(data.key);
      } else {
        set({ meshJob: { id: data.job_id, status: 'queued', progress: 0, message: 'En cola' } });
      }
    } catch (e) {
      set({ meshError: err(e) });
    }
  },

  pollJob: async (id) => {
    try {
      const { data } = await axios.get(`/api/jobs/${id}`);
      const j = data.job || data;
      if (j.error) set({ meshError: j.error });
    } catch { /* the socket message is enough */ }
  },

  fetchMesh: async (key) => {
    if (!key) return;
    try {
      const { data } = await axios.get(`${API}/mesh/${key}`);
      set({ mesh: data, meshKey: key, meshJob: null, showMesh: true });
    } catch (e) {
      set({ meshError: err(e) });
    }
  },
  setShowMesh: (showMesh) => set({ showMesh }),

  // ── study link ─────────────────────────────────────────────────────────
  loadFromNode: (node) => {
    const props = node?.data?.properties;
    set({ d: domainFromProps(props), dirty: false, mesh: null, meshKey: props?.mesh_key || null, selectedEdge: null });
    if (props?.mesh_key) get().fetchMesh(props.mesh_key);
  },
  markSaved: () => set({ dirty: false }),
  clearError: () => set({ error: null, meshError: null }),
}));

export default useGeoMapStore;
