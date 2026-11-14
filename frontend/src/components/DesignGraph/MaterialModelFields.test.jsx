// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import OrthotropicFields from './OrthotropicFields';
import HyperelasticFields from './HyperelasticFields';
import ViscoelasticFields from './ViscoelasticFields';
import { SummaryRows } from '../Results/ResultsViewer';

describe('material model fields (item 8)', () => {
  beforeEach(() => cleanup());

  it('orthotropic: lists missing constants and edits an axis component', () => {
    const setProp = vi.fn();
    render(<OrthotropicFields props={{ E1: 140e9 }} setProp={setProp} />);
    expect(screen.getByText(/Faltan: E2, E3, G12/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Eje 1 y'), { target: { value: '1' } });
    expect(setProp).toHaveBeenCalledWith('axis_1', [1, 1, 0]);
  });

  it('neo-hookean: shows μ and κ from E and ν', () => {
    render(<HyperelasticFields props={{ E: 10e6, nu: 0.45 }} setProp={vi.fn()} />);
    expect(screen.getByText(/μ = 3.448 MPa · κ = 33.33 MPa/)).toBeTruthy();
  });

  it('viscoelastic: adds Prony terms and flags Σg ≥ 1', () => {
    const setProp = vi.fn();
    const { rerender } = render(<ViscoelasticFields props={{}} setProp={setProp} />);
    expect(screen.getByText('Falta al menos un término.')).toBeTruthy();
    fireEvent.click(screen.getByText('+ término de Prony'));
    expect(setProp).toHaveBeenCalledWith('prony_terms', [{ g: 0.3, tau: 10 }]);
    rerender(<ViscoelasticFields props={{ prony_terms: [{ g: 0.7, tau: 1 }, { g: 0.4, tau: 5 }] }} setProp={setProp} />);
    expect(screen.getByText(/Σg debe ser < 1/)).toBeTruthy();
  });

  it('results summary shows the model-specific rows', () => {
    render(<SummaryRows header={{ summary: { viscoelastic: { prony: [{}], t_end_s: 60, E0: 3e9, E_inf: 1.5e9,
      creep_ratio: 2 } }, material: { E1: 140e9, E2: 10e9, E3: 10e9 } }} />);
    expect(screen.getByText('Maxwell (1 términos)')).toBeTruthy();
    expect(screen.getByText('E1 / E2 / E3')).toBeTruthy();
  });
});
