// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';
import MaterialEditor, { fitQuality } from './MaterialEditor';
import useMaterialStore from '../../stores/materialStore';

vi.mock('axios');
vi.mock('recharts', () => {
  const Stub = ({ children }) => <div>{children}</div>;
  return {
    ComposedChart: Stub, Line: Stub, Scatter: Stub, Area: Stub, XAxis: Stub, YAxis: Stub, Tooltip: Stub,
    ResponsiveContainer: Stub, CartesianGrid: Stub, Legend: Stub,
  };
});

const MAT = {
  id: 'm1', name: 'Al 6061-T6', model_type: 'linear_elastic_isotropic',
  parameters: { E: { value: 69e9, std: 2e9 }, nu: { value: 0.33, std: 0.01 } }, calibration: {},
};
const FIT = {
  best_model: 'voce', r_squared: 0.9991, std_source: 'specimens',
  all_results: [{
    model: 'voce', label: 'Elastoplástico Voce (saturación)', r2: 0.9991, aicc: -10, rmse_mpa: 1.7,
    parameters: { E: { value: 69e9, unit: 'Pa' } },
  }],
  specimens: [{ name: 'p1.csv', notes: ['Datos tras la resistencia máxima descartados (3 puntos: estricción/fractura).'] }],
  curves: {
    strain: [0, 0.01], specimens: [{ name: 'p1.csv', strain: [0], stress: [0] }],
    fits: { voce: { stress: [0, 280], lower: [0, 278], upper: [0, 282] } },
  },
  material: {
    ...MAT, model_type: 'elastoplastic_voce',
    parameters: { ...MAT.parameters, sigma_y: { value: 276e6, std: 4e6, unit: 'Pa' } },
    calibration: {
      best_model: 'voce', label: 'Elastoplástico Voce (saturación)', r_squared: 0.9991, n_specimens: 3,
      std_source: 'specimens',
    },
  },
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  useMaterialStore.setState({ materials: [], current: null, fit: null, files: [], busy: false, error: null });
  axios.get.mockImplementation((url) => {
    if (url === '/api/design/material/') return Promise.resolve({ data: { materials: [MAT] } });
    if (url === '/api/design/material/m1') return Promise.resolve({ data: MAT });
    return Promise.reject(new Error(url));
  });
});

describe('MaterialEditor', () => {
  it('uploads tensile curves, shows the chosen model and assigns it to the node', async () => {
    axios.post.mockImplementation((url) => {
      if (url.endsWith('/fit')) return Promise.resolve({ data: FIT });
      if (url.endsWith('/assign')) return Promise.resolve({ data: { properties: { E: 69e9, yield_strength: 276e6 } } });
      return Promise.reject(new Error(url));
    });
    const onAssigned = vi.fn();
    render(<MaterialEditor open graphId="g1" nodeId="n1" onClose={() => {}} onAssigned={onAssigned} />);
    fireEvent.click(await screen.findByText('Al 6061-T6'));
    await screen.findByDisplayValue('69');
    const file = new File(['strain,stress\n0,0'], 'p1.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('fit-files'), { target: { files: [file] } });
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith('/api/design/material/m1/fit', expect.any(FormData)));
    expect(await screen.findByText('Excelente')).toBeTruthy();
    expect(screen.getByText(/dispersión entre 3 probetas/)).toBeTruthy();
    expect(screen.getByText(/estricción/)).toBeTruthy();
    fireEvent.click(screen.getByText('Asignar al nodo'));
    await waitFor(() => expect(onAssigned).toHaveBeenCalledWith({ E: 69e9, yield_strength: 276e6 }));
  });

  it('grades the fit quality', () => {
    expect(fitQuality(0.999)[0]).toBe('Excelente');
    expect(fitQuality(0.985)[0]).toBe('Bueno');
    expect(fitQuality(0.5)[0]).toBe('Pobre');
  });
});
