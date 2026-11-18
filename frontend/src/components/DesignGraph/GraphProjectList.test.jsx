// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import axios from 'axios';
import GraphProjectList from './GraphProjectList';
import { groupVersions } from './versionTree';
import useDesignStore from '../../stores/designStore';

vi.mock('axios');

const G = (id, version, parent_id, extra = {}) => ({
  id, name: 'Bracket', version, parent_id, tier: 1, status: 'draft', version_note: '',
  created_at: `2026-11-1${version}T10:00:00`, updated_at: `2026-11-1${version}T10:00:00`, ...extra,
});
const GRAPHS = [
  G('v3', 3, 'v2', { version_note: 'espesor 8 mm' }),
  { ...G('solo', 1, null), name: 'Soporte', updated_at: '2026-11-01T00:00:00' },
  G('v1', 1, null, { version_note: '' }),
  G('v2', 2, 'v1', { version_note: 'agujero de alivio' }),
  G('v2b', 4, 'v1', { version_note: 'rama: aluminio' }),
];

describe('groupVersions', () => {
  it('groups a version tree (with branches) under its root, newest project first', () => {
    const groups = groupVersions(GRAPHS);
    expect(groups.map((g) => g.root.id)).toEqual(['v1', 'solo']);
    expect(groups[0].versions.map((v) => v.version)).toEqual([1, 2, 3, 4]);
    expect(groups[0].latest.id).toBe('v2b');
  });
  it('a version whose parent was deleted becomes a root', () => {
    const groups = groupVersions([G('v2', 2, 'gone')]);
    expect(groups[0].root.id).toBe('v2');
  });
});

describe('GraphProjectList (version tree)', () => {
  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
    useDesignStore.setState({ graphs: GRAPHS, graphsLoading: false, activeGraphId: 'v3',
      fetchGraphs: vi.fn(), loadGraph: vi.fn() });
  });

  it('shows projects with their versions; the active project is expanded', () => {
    render(<GraphProjectList />);
    const groups = screen.getAllByTestId('project-group');
    expect(groups).toHaveLength(2);
    expect(within(groups[0]).getByText('4 versiones')).toBeTruthy();
    const rows = within(groups[0]).getAllByTestId('version-row');
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('v1'), expect.stringContaining('agujero de alivio'),
      expect.stringContaining('espesor 8 mm'), expect.stringContaining('rama: aluminio')]);
    fireEvent.click(within(groups[0]).getByText('Bracket'));               // collapse
    expect(within(groups[0]).queryAllByTestId('version-row')).toHaveLength(0);
  });

  it('creates a new version with a note', async () => {
    const createVersion = vi.fn().mockResolvedValue({ id: 'v5' });
    useDesignStore.setState({ createVersion });
    render(<GraphProjectList />);
    const row = screen.getAllByTestId('version-row')[2];                   // v3
    fireEvent.click(within(row).getByLabelText('nueva versión'));
    fireEvent.change(screen.getByLabelText('¿Qué cambia en esta versión?'), { target: { value: 'carga 2 kN' } });
    fireEvent.click(screen.getByText('Crear versión'));
    await waitFor(() => expect(createVersion).toHaveBeenCalledWith('v3', 'carga 2 kN'));
  });

  it('shows the changes of a version against the previous one', async () => {
    axios.get.mockResolvedValue({ data: {
      against_version: 2, nodes_added: [{ id: 'n9', type: 'BC', label: 'Apoyo' }], nodes_removed: [],
      nodes_changed: [{ id: 'n1', type: 'GEOMETRY', label: 'Viga', old_label: 'Viga',
        properties: { length_mm: [500, 800] } }],
      edges_added: [], edges_removed: [{ source: 'F', target: 'Viga', type: 'APPLIED_TO' }],
    } });
    render(<GraphProjectList />);
    const row = screen.getAllByTestId('version-row')[2];
    fireEvent.click(within(row).getByLabelText('cambios'));
    await waitFor(() => expect(screen.getByTestId('version-diff')).toBeTruthy());
    expect(axios.get).toHaveBeenCalledWith('/api/design/graph/v3/diff');
    const text = screen.getByTestId('version-diff').textContent;
    expect(text).toMatch('+ BC «Apoyo»');
    expect(text).toMatch('length_mm: 500 → 800');
    expect(text).toMatch('− F —APPLIED_TO→ Viga');
    expect(screen.getByText(/cambios de v3 respecto a v2/)).toBeTruthy();
  });
});
