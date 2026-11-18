// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';
import SimHistory from './SimHistory';

vi.mock('axios');

const ENV = { fem_kernel: 3, numpy: '1.26.4', scipy: '1.17.1' };
const base = {
  graph_id: 'g', tier: 1, physics: ['structural'], created_at: '2026-11-13T07:00:00+00:00',
  converged: true, element_type: 'T10', n_nodes: 6242, max_displacement_mm: 9.67, max_von_mises_mpa: 1115.9,
  mesh_hash: 'm'.repeat(64), result_hash: 'r'.repeat(64), environment: ENV, parameter_delta: {}, error: null,
};
const RUNS = [
  { ...base, run_id: 'r3', hash: 'a'.repeat(64), purpose: 'reproduce', status: 'done', parent_run_id: 'r1', same_hash_runs: 2 },
  { ...base, run_id: 'r2', hash: 'b'.repeat(64), purpose: 'run', status: 'done', parent_run_id: 'r1',
    parameter_delta: { 'material.E': [210e9, 200e9] }, same_hash_runs: 1 },
  { ...base, run_id: 'r1', hash: 'a'.repeat(64), purpose: 'run', status: 'done', parent_run_id: null, same_hash_runs: 2 },
];

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/runs')) return Promise.resolve({ data: { runs: RUNS } });
    if (url.endsWith('/r3/reproducibility')) {
      return Promise.resolve({ data: { reproduced: true, bitwise_identical: true, same_hash: true, same_mesh: true,
        max_rel_diff_displacement: 0, max_rel_diff_von_mises: 0, environment_diff: {} } });
    }
    if (url.endsWith('/environment')) return Promise.resolve({ data: { ...ENV, scipy: '1.18.0' } });
    if (url.endsWith('/report')) return Promise.resolve({ data: '# Reporte de simulación `aaaa`' });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
});

describe('SimHistory', () => {
  it('lists runs with hash, delta and reproducibility', async () => {
    render(<SimHistory open graphId="g" onClose={() => {}} />);
    expect(await screen.findAllByText('aaaaaaaa')).toHaveLength(2);
    expect(screen.getByText('bbbbbbbb')).toBeTruthy();
    expect(screen.getByText('material.E')).toBeTruthy();
    expect(await screen.findByText('Idéntico bit a bit')).toBeTruthy();
    expect(screen.getByText('de #1')).toBeTruthy();
  });

  it('shows the report', async () => {
    render(<SimHistory open graphId="g" onClose={() => {}} />);
    fireEvent.click((await screen.findAllByText('Ver'))[0]);
    expect(await screen.findByText(/Reporte de simulación/)).toBeTruthy();
  });

  it('warns about environment mismatch and forces the reproduction', async () => {
    axios.post.mockResolvedValue({ data: { run_id: 'r4', same_hash: false } });
    render(<SimHistory open graphId="g" onClose={() => {}} />);
    fireEvent.click((await screen.findAllByText('Reproducir'))[0]);
    expect(await screen.findByText(/El entorno difiere en scipy/)).toBeTruthy();
    fireEvent.click(screen.getByText('Reproducir de todos modos'));
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
      '/api/design/solver/r3/reproduce', { force: true }));
  });
});
