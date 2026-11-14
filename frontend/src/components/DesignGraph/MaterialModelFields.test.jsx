// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import OrthotropicFields from './OrthotropicFields';
import HyperelasticFields from './HyperelasticFields';
import ViscoelasticFields from './ViscoelasticFields';
import PiezoFields, { PZT5H } from './PiezoFields';
import { availableFields, fieldMeta, fieldValues } from '../Results/resultsField';
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

  it('piezo: PZT-5H preset fills every constant', () => {
    const setProp = vi.fn();
    render(<PiezoFields props={{}} setProp={setProp} />);
    expect(screen.getByText(/Faltan: c11/)).toBeTruthy();
    fireEvent.click(screen.getByText('PZT-5H'));
    expect(setProp).toHaveBeenCalledWith('e33', PZT5H.e33);
    expect(setProp).toHaveBeenCalledTimes(Object.keys(PZT5H).length);
  });

  it('results: extra fields (x_<key>) come from the pack header', () => {
    const pack = { nNodes: 2, header: { fields: ['u', 'vm'], extra_fields: [{ key: 'phi', label: 'Potencial eléctrico', unit: 'V' }] },
      u: { data: new Float32Array(6) }, x_phi: { data: new Float32Array([0, 100]) } };
    expect(availableFields(pack)).toContain('x_phi');
    expect(fieldMeta(pack, 'x_phi')).toEqual({ label: 'Potencial eléctrico', unit: 'V' });
    expect(fieldMeta(pack, 'vm').unit).toBe('MPa');
    expect(Array.from(fieldValues(pack, 'x_phi'))).toEqual([0, 100]);
    render(<SummaryRows header={{ summary: { piezo: { min_potential_V: 0, max_potential_V: 100, max_field_V_m: 5e4,
      electrodes: [{ label: 'top', voltage_V: 100, charge_C: 2e-9 }] } }, material: { c11: 127e9, c33: 117e9 } }} />);
    expect(screen.getByText('Electrodo top')).toBeTruthy();
    expect(screen.getByText('c11ᴱ / c33ᴱ')).toBeTruthy();
  });
});
