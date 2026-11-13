/**
 * Geometry Store — versioned STEP geometries with persistent face IDs (Engineering Hub, Fase 1b/1c).
 *
 * Face identity in the UI is the 1-based CAD face index (``entity_index``), which is what the
 * viewer GLB carries per vertex (``_face_id``). ``entities[index].id`` is the persistent UUID
 * that boundary conditions will reference.
 */
import { create } from 'zustand';
import axios from 'axios';
import { getSocket } from '../services/socket';

const useGeometryStore = create((set, get) => ({
  geometries: [],          // latest version per lineage
  versions: {},            // lineage_id -> [geometry]
  selected: null,          // geometry object
  entities: {},            // entity_index -> face entity (selected geometry)
  parentIndex: {},         // entity_index -> parent face index (remap with previous version)
  selectedFaces: [],       // [entity_index]
  hoverFace: null,
  glbNonce: 0,             // bump to force the viewer to reload the GLB
  uploading: false,
  error: null,
  subscribed: false,

  init: async () => {
    if (!get().subscribed) {
      getSocket().on('job_update', (ev) => {
        if (ev.kind !== 'geometry.import') return;
        if (['done', 'failed', 'cancelled'].includes(ev.status)) get().onImportFinished();
      });
      set({ subscribed: true });
    }
    await get().fetchList();
  },

  fetchList: async () => {
    try {
      const { data } = await axios.get('/api/geometry');
      set({ geometries: data.geometries, error: null });
    } catch (e) {
      set({ error: e.response?.data?.error || e.message });
    }
  },

  onImportFinished: async () => {
    await get().fetchList();
    const sel = get().selected;
    if (!sel) return;
    const { data } = await axios.get(`/api/geometry/${sel.id}`);
    const becameReady = sel.status !== 'ready' && data.status === 'ready';
    const reimported = sel.status === 'ready' && data.status === 'ready' && data.updated_at !== sel.updated_at;
    set({ selected: data });
    if (becameReady || reimported) {
      await get().loadEntities(data);
      set((s) => ({ glbNonce: s.glbNonce + 1 }));
    }
    await get().loadVersions(data);
  },

  upload: async (file, parentId = null) => {
    const form = new FormData();
    form.append('file', file);
    if (parentId) form.append('parent_id', parentId);
    set({ uploading: true, error: null });
    try {
      const { data } = await axios.post('/api/geometry', form);
      await get().fetchList();
      await get().select(data.geometry);
      return data;
    } catch (e) {
      set({ error: e.response?.data?.error || e.message });
      return null;
    } finally {
      set({ uploading: false });
    }
  },

  select: async (geometry) => {
    set({ selected: geometry, entities: {}, parentIndex: {}, selectedFaces: [], hoverFace: null });
    await get().loadVersions(geometry);
    if (geometry.status === 'ready') await get().loadEntities(geometry);
  },

  loadVersions: async (geometry) => {
    const { data } = await axios.get(`/api/geometry/${geometry.id}/versions`);
    set((s) => ({ versions: { ...s.versions, [data.lineage_id]: data.versions } }));
  },

  loadEntities: async (geometry) => {
    const { data } = await axios.get(`/api/geometry/${geometry.id}/entities`, { params: { type: 'face' } });
    if (get().selected?.id !== geometry.id) return;
    const entities = {};
    data.entities.forEach((e) => { entities[e.entity_index] = e; });
    let parentIndex = {};
    if (geometry.parent_id) {
      try {
        const { data: rm } = await axios.get(`/api/geometry/${geometry.id}/remap`);
        rm.faces.forEach((f) => { if (f.parent_index != null) parentIndex[f.index] = f.parent_index; });
      } catch { parentIndex = {}; }
    }
    set({ entities, parentIndex });
  },

  reimport: async (id) => {
    try {
      await axios.post(`/api/geometry/${id}/reimport`);
      const { data } = await axios.get(`/api/geometry/${id}`);
      set({ selected: data });
      await get().fetchList();
    } catch (e) {
      set({ error: e.response?.data?.error || e.message });
    }
  },

  /** Click on a face: replace selection, or toggle it when ``additive`` (Shift/Ctrl). */
  pickFace: (index, additive = false) => set((s) => {
    if (index == null) return additive ? {} : { selectedFaces: [] };
    if (!additive) return { selectedFaces: s.selectedFaces.length === 1 && s.selectedFaces[0] === index ? [] : [index] };
    return {
      selectedFaces: s.selectedFaces.includes(index)
        ? s.selectedFaces.filter((i) => i !== index)
        : [...s.selectedFaces, index],
    };
  }),

  setHoverFace: (index) => { if (get().hoverFace !== index) set({ hoverFace: index }); },
  clearSelection: () => set({ selectedFaces: [] }),
}));

export default useGeometryStore;
