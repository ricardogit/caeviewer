// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';
import TopBar from '../TopBar';
import { statusLines } from './GraphStatusStrip';
import ResultsRunList from '../Results/ResultsRunList';
import { autoScale, availableFields, fieldValues, normalizer, range } from '../Results/resultsField';
import { SummaryRows } from '../Results/ResultsViewer';
import useDesignStore from '../../stores/designStore';
import useSolverStore from '../../stores/solverStore';
import useWorkspaceStore from '../../stores/workspaceStore';
import useResultsStore from '../../stores/resultsStore';

vi.mock('axios');
vi.mock('../JobMonitor', () => ({ default: () => <div /> }));
vi.mock('../../services/socket', () => ({ getSocket: () => ({ on: vi.fn(), off: vi.fn(), emit: vi.fn() }) }));

const PREFLIGHT = {
  graph_id: 'g1', name: 'Viga', version: 3, status: 'draft', ready: true,
  issues: [{ severity: 'warning', message: 'LOAD sin arista APPLIED_TO' }],
  physics_label: 'Estructural 3D (elástico lineal)',
  size: { n_dof: 12345, n_nodes: 4115, n_elements: 2000, estimated: true },
  tier_declared: 1, tier_needed: 0, tier_ok: true,
  confidence: { factor: 0.72, n_similar: 3 },
  latest_run: { run_id: 'r1', status: 'done', max_displacement_mm: 0.81, max_von_mises_mpa: 120 },
};

function pack({ u, vm, bbox = [[0, 0, 0], [100, 10, 10]] }) {
  return { nNodes: vm.length, header: { bbox_mm: bbox }, u: { data: Float32Array.from(u) }, vm: { data: Float32Array.from(vm) } };
}

describe('status strip lines (plan §9.4)', () => {
  it('lists warnings, physics, tier, confidence and the latest run', () => {
    const lines = statusLines(PREFLIGHT);
    const text = lines.map((l) => l.text).join('\n');
    expect(text).toMatch('LOAD sin arista APPLIED_TO');
    expect(text).toMatch('Grafo válido para física: Estructural 3D');
    expect(text).toMatch(/Tier estimado: 0 \(≈ 12[.,]345 DOF\) · declarado 1/);
    expect(text).toMatch('Factor de confianza: 0.72 (3 simulación(es) similar(es)');
    expect(lines.find((l) => l.text.startsWith('Última simulación')).text).toMatch('u máx 0.810 mm');
  });

  it('flags errors and a declared tier that is too small', () => {
    const lines = statusLines({ ...PREFLIGHT, ready: false, tier_needed: 2, tier_ok: false,
      issues: [{ severity: 'error', message: 'Falta nodo MATERIAL' }] });
    expect(lines[0]).toEqual({ kind: 'error', text: 'Falta nodo MATERIAL' });
    expect(lines.some((l) => l.kind === 'warn' && /Necesita Tier 2.*declara Tier 1/.test(l.text))).toBe(true);
    expect(lines.some((l) => l.kind === 'ok' && /válido/.test(l.text))).toBe(false);
  });
});

describe('results field helpers', () => {
  const p = pack({ u: [0, 0, 0, 0, -2, 0, 0, -4, 1], vm: [10, 50, 200] });
  it('extracts magnitude, components and von Mises', () => {
    expect(Array.from(fieldValues(p, 'uy'))).toEqual([0, -2, -4]);
    expect(fieldValues(p, 'umag')[2]).toBeCloseTo(Math.hypot(4, 1), 5);
    expect(range(fieldValues(p, 'vm'))).toEqual([10, 200]);
  });
  it('uses a symmetric colour range for signed components', () => {
    const n = normalizer('uy', [-4, 1]);
    expect([n.min, n.max]).toEqual([-4, 4]);
    expect(n.t(0)).toBe(0.5);
  });
  it('auto scale draws the max displacement as 8 % of the model and never shrinks', () => {
    const diag = Math.hypot(100, 10, 10);
    expect(autoScale(p)).toBeCloseTo((0.08 * diag) / Math.hypot(4, 1), 4);
    expect(autoScale(pack({ u: [0, 50, 0], vm: [1] }))).toBe(1);
  });
  it('offers only the stored fields: thermal runs show temperature and heat flux', () => {
    expect(availableFields(p)).toEqual(['vm', 'umag', 'ux', 'uy', 'uz']);
    const t = { ...pack({ u: [0, 0, 0, 0, 0, 0], vm: [0, 0] }), T: { data: Float32Array.from([20, 120]) },
      q: { data: Float32Array.from([5, 9]) } };
    t.header = { ...t.header, fields: ['T', 'q'], max_T: 120, min_T: 20, max_q: 9 };
    expect(availableFields(t)).toEqual(['T', 'q']);
    expect(Array.from(fieldValues(t, 'T'))).toEqual([20, 120]);
    t.header.fields = ['u', 'vm', 'T', 'q'];
    expect(availableFields(t)).toEqual(['vm', 'umag', 'ux', 'uy', 'uz', 'T', 'q']);
    render(<SummaryRows header={{ ...t.header, fields: ['T', 'q'], summary: { thermal: { heat_balance_error: 0 } } }} />);
    expect(screen.getByText('20 … 120 °C')).toBeTruthy();
    expect(screen.queryByText('Despl. máx.')).toBeNull();
  });
});

describe('TopBar (plan §9.2)', () => {
  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
    axios.get.mockResolvedValue({ data: { jobs: [] } });
    useWorkspaceStore.setState({ appMode: 'design', preflight: PREFLIGHT, solverOpen: false, historyOpen: false,
      showValidation: false, loadPreflight: vi.fn() });
    useDesignStore.setState({ activeGraphId: 'g1', activeGraphMeta: { name: 'Viga', version: 3, status: 'draft' } });
    useSolverStore.setState({ runStatus: 'idle' });
  });

  it('shows the project context: name, version, status, readiness and tier', () => {
    render(<TopBar />);
    const ctx = screen.getByTestId('project-context');
    expect(ctx.textContent).toMatch('Viga');
    expect(ctx.textContent).toMatch('v3');
    expect(ctx.textContent).toMatch('borrador');
    expect(ctx.textContent).toMatch('✓ listo');
    expect(ctx.textContent).toMatch('Tier 0');
  });

  it('Simular validates, opens the solver panel and launches the run', async () => {
    const validateGraph = vi.fn().mockResolvedValue({ ready_for_simulation: true });
    const startRun = vi.fn().mockResolvedValue('r2');
    useDesignStore.setState({ validateGraph });
    useSolverStore.setState({ startRun });
    render(<TopBar />);
    fireEvent.click(screen.getByText('Simular'));
    await waitFor(() => expect(startRun).toHaveBeenCalledWith('g1'));
    expect(useWorkspaceStore.getState().solverOpen).toBe(true);
    expect(useWorkspaceStore.getState().solverMode).toBe('graph');
  });

  it('Simular on an incomplete graph shows the validation instead of running', async () => {
    const startRun = vi.fn();
    useDesignStore.setState({ validateGraph: vi.fn().mockResolvedValue({ ready_for_simulation: false }) });
    useSolverStore.setState({ startRun });
    render(<TopBar />);
    fireEvent.click(screen.getByText('Simular'));
    await waitFor(() => expect(useWorkspaceStore.getState().showValidation).toBe(true));
    expect(startRun).not.toHaveBeenCalled();
  });

  it('Historial opens the history dialog and mode chips switch the workspace', () => {
    render(<TopBar />);
    fireEvent.click(screen.getByText('Historial'));
    expect(useWorkspaceStore.getState().historyOpen).toBe(true);
    fireEvent.click(screen.getByText('Resultados'));
    expect(useWorkspaceStore.getState().appMode).toBe('results');
  });
});

describe('ResultsRunList', () => {
  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
    useDesignStore.setState({ activeGraphId: 'g1', graphs: [{ id: 'g1', name: 'Viga', version: 3 }] });
    useResultsStore.setState({ runs: [], runId: null, pack: null });
  });

  it('lists only runs with fields and opens the newest finished one', async () => {
    axios.get.mockImplementation((url) => {
      if (url === '/api/design/solver/runs') {
        return Promise.resolve({ data: { runs: [
          { run_id: 'aaaaaaaa1', purpose: 'run', status: 'failed', created_at: '2026-11-13T10:00:00' },
          { run_id: 'bbbbbbbb2', purpose: 'run', status: 'done', created_at: '2026-11-13T09:00:00', max_displacement_mm: 0.8 },
          { run_id: 'cccccccc3', purpose: 'rom', status: 'done', created_at: '2026-11-13T08:00:00' },
        ] } });
      }
      return Promise.reject(new Error('no pack in test'));
    });
    render(<ResultsRunList />);
    await waitFor(() => expect(screen.getAllByTestId('run-item')).toHaveLength(2));
    await waitFor(() => expect(useResultsStore.getState().runId).toBe('bbbbbbbb2'));
    expect(axios.get).toHaveBeenCalledWith('/api/design/solver/bbbbbbbb2/surface', { responseType: 'arraybuffer' });
  });
});
