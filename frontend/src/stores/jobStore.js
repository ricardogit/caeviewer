/**
 * Job Store — Postgres job queue (Engineering Hub, Fase 0).
 * Initial list via REST, then live updates from socket.io `job_update`
 * (worker → Postgres NOTIFY → Flask listener → socket.io).
 */
import { create } from 'zustand';
import axios from 'axios';
import { getSocket } from '../services/socket';

export const TERMINAL = ['done', 'failed', 'cancelled'];
const MAX_JOBS = 50;

const useJobStore = create((set, get) => ({
  jobs: {},            // id -> job
  stats: null,
  error: null,
  subscribed: false,

  /** Load recent jobs and subscribe once to live updates. */
  init: async () => {
    if (!get().subscribed) {
      getSocket().on('job_update', (ev) => get().applyEvent(ev));
      set({ subscribed: true });
    }
    await get().refresh();
  },

  refresh: async () => {
    try {
      const [{ data: list }, { data: stats }] = await Promise.all([
        axios.get('/api/jobs', { params: { limit: MAX_JOBS } }),
        axios.get('/api/jobs/stats'),
      ]);
      const jobs = {};
      list.jobs.forEach((j) => { jobs[j.id] = j; });
      set({ jobs, stats, error: null });
    } catch (e) {
      set({ error: e.response?.data?.error || e.message });
    }
  },

  applyEvent: (ev) => {
    if (!ev?.job_id) return;
    set((s) => {
      const prev = s.jobs[ev.job_id] || { id: ev.job_id, created_at: new Date().toISOString() };
      const next = {
        ...prev,
        kind: ev.kind ?? prev.kind,
        queue: ev.queue ?? prev.queue,
        status: ev.status ?? prev.status,
        progress: ev.progress ?? prev.progress,
        message: ev.message ?? prev.message,
        simulation_run_id: ev.simulation_run_id ?? prev.simulation_run_id,
        error: ev.error ?? prev.error,
      };
      if (ev.status === 'running' && !prev.started_at) next.started_at = new Date().toISOString();
      if (TERMINAL.includes(ev.status) && !prev.finished_at) next.finished_at = new Date().toISOString();
      return { jobs: { ...s.jobs, [ev.job_id]: next } };
    });
  },

  enqueueDummy: async (payload = { steps: 10, delay_s: 0.5 }) => {
    const { data } = await axios.post('/api/jobs', { kind: 'dummy', payload });
    get().applyEvent({ job_id: data.id, ...data });
    return data;
  },

  cancel: async (id) => {
    const { data } = await axios.post(`/api/jobs/${id}/cancel`);
    get().applyEvent({ job_id: data.id, ...data });
  },

  fetchLog: async (id, tail = 200) => {
    const { data } = await axios.get(`/api/jobs/${id}/log`, { params: { tail } });
    return data.lines;
  },
}));

/** Jobs sorted newest first. */
export const selectJobList = (s) =>
  Object.values(s.jobs).sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));

export const selectActiveCount = (s) =>
  Object.values(s.jobs).filter((j) => !TERMINAL.includes(j.status)).length;

export default useJobStore;
