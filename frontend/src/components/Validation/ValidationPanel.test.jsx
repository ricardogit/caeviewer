// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';
import ValidationPanel from './ValidationPanel';
import CorrelationView from './CorrelationView';
import useValidationStore from '../../stores/validationStore';
import useDesignStore from '../../stores/designStore';

vi.mock('axios');
vi.mock('recharts', () => {
  const Stub = ({ children }) => <div>{children}</div>;
  return {
    ScatterChart: Stub, Scatter: Stub, LineChart: Stub, Line: Stub, XAxis: Stub, YAxis: Stub, Tooltip: Stub,
    ResponsiveContainer: Stub, CartesianGrid: Stub, Legend: Stub,
  };
});

const EXPS = [
  { id: 'e1', test_type: 'structural', description: 'Ensayo banco 1', scalar_summary: { n_sensors: 3 }, conditions: {} },
  { id: 'e2', test_type: 'tensile', description: 'Probeta 1', material_id: 'm1',
    scalar_summary: { label: 'Ludwik', E: 205e9, sigma_y: 399e6 }, conditions: { temperature_c: 23 } },
];
const CONF = {
  confidence_factor: 0.42, level: 'media',
  similar_runs: [{ correlation_id: 'c0', similarity: 0.9, same_graph: false, r2: 0.97, recalibrated: false }],
  recommendations: [{ test_type: 'structural', priority: 1, title: 'Ensayo estático de la pieza con sensores',
    reason: 'Ninguna medición', sensors: [{ quantity: 'uy', x: 500, y: 0, z: 12.5, why: 'Desplazamiento máximo', expected: -0.8, unit: 'mm' }] }],
};
const SENSORS = [
  { label: 'L1', quantity: 'uy', value: -0.8, simulated: -0.75, rel_error: 0.0625, simulated_after: -0.8 },
  { label: 'G1', quantity: 'strain', value: -400, simulated: -380, rel_error: 0.05, simulated_after: -405 },
];

function mockApi() {
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/experiments')) return Promise.resolve({ data: { experiments: EXPS } });
    if (url.endsWith('/correlations')) return Promise.resolve({ data: { correlations: [
      { id: 'c1', experiment_id: 'e1', r2: 0.93, kind: 'structural' }] } });
    if (url.endsWith('/confidence')) return Promise.resolve({ data: CONF });
    if (url.includes('/api/design/material')) return Promise.resolve({ data: { materials: [{ id: 'm1', name: 'S355' }] } });
    if (url.endsWith('/correlations/c1')) return Promise.resolve({ data: { id: 'c1', kind: 'structural',
      details: { overall: { r2: 0.93, max_rel_error: 0.06, confidence_factor: 0.5 }, sensors: SENSORS } } });
    return Promise.resolve({ data: {} });
  });
}

describe('ValidationPanel', () => {
  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
    useValidationStore.setState({ experiments: [], correlations: [], confidence: null, view: null, error: null,
      preview: null, busy: false });
    useDesignStore.setState({ activeGraphId: 'g1', graphData: { nodes: [
      { id: 'n1', data: { node_type: 'MATERIAL', properties: { material_id: 'm1' } } }], edges: [] } });
    mockApi();
  });

  it('shows confidence, recommendations and the experiments with their last R²', async () => {
    render(<ValidationPanel graphId="g1" />);
    await waitFor(() => expect(screen.getAllByTestId('exp-row')).toHaveLength(2));
    expect(screen.getByTestId('confidence').textContent).toBe('0.42');
    expect(screen.getByText(/Ensayo estático de la pieza/)).toBeTruthy();
    expect(screen.getByText(/uy en \(500.0, 0.0, 12.5\) mm/)).toBeTruthy();
    expect(screen.getByText('R² 0.930')).toBeTruthy();
    expect(screen.getByText(/E 205.0 GPa · σ0.2 399 MPa/)).toBeTruthy();
  });

  it('correlates an experiment and shows the result', async () => {
    axios.post.mockResolvedValue({ data: { id: 'c2', kind: 'structural', experiment_id: 'e1',
      details: { overall: { r2: 0.981, max_rel_error: 0.04, confidence_factor: 0.7 }, sensors: SENSORS } } });
    render(<ValidationPanel graphId="g1" />);
    await waitFor(() => expect(screen.getAllByTestId('exp-row')).toHaveLength(2));
    fireEvent.click(screen.getAllByText('Correlacionar')[0]);
    await waitFor(() => expect(screen.getByTestId('r2').textContent).toBe('R² 0.9810'));
    expect(axios.post).toHaveBeenCalledWith('/api/design/validation/g1/correlate', { experiment_id: 'e1' });
    expect(screen.getByText('L1')).toBeTruthy();
  });

  it('recalibrates a tensile test and reloads the graph', async () => {
    const loadGraph = vi.fn();
    useDesignStore.setState({ loadGraph });
    axios.post.mockResolvedValue({ data: {
      applied: true, mode: 'replace', model_before: 'Elástico lineal (E)', model_after: 'Ludwik',
      before: { r2: -2.1, max_rel_error: 0.5 }, after: { r2: 0.999, max_rel_error: 0.02 },
      delta: { E: { old: 180e9, new: 204.7e9, rel_change: 0.137, new_std: 0.9e9 } },
      curve: { strain: [0, 0.01], measured: [0, 380], before: [0, 300], after: [0, 381] }, synced_nodes: ['n1'],
    } });
    render(<ValidationPanel graphId="g1" />);
    await waitFor(() => expect(screen.getAllByTestId('exp-row')).toHaveLength(2));
    fireEvent.click(screen.getAllByText('Recalibrar')[1]);
    await waitFor(() => expect(screen.getByText('+13.7 %')).toBeTruthy());
    expect(axios.post).toHaveBeenCalledWith('/api/design/validation/g1/recalibrate',
      { experiment_id: 'e2', mode: 'replace', apply: true });
    expect(loadGraph).toHaveBeenCalledWith('g1');
    expect(screen.getByText(/1 nodo\(s\) MATERIAL actualizados/)).toBeTruthy();
  });
});

describe('CorrelationView', () => {
  it('warns when the stiffness correction does not explain the mismatch', () => {
    render(<CorrelationView view={{ type: 'recal_structural', data: {
      applied: false, before: { r2: 0.5, max_rel_error: 0.6 }, after: { r2: 0.94, max_rel_error: 0.58 },
      warning: 'la diferencia no es (solo) de E', E_new: 197e9, E_std: 1e9, E_run: 210e9,
      delta: { E: { rel_change: -0.062 } }, sensors: SENSORS } }} />);
    expect(screen.getByText(/no es \(solo\) de E/)).toBeTruthy();
    expect(screen.getByText(/Vista previa/)).toBeTruthy();
    expect(screen.getByText(/E efectivo 197.0 ± 1.0 GPa/)).toBeTruthy();
  });
});
