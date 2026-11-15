// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import OrthotropicFields from './OrthotropicFields';
import HyperelasticFields from './HyperelasticFields';
import ViscoelasticFields from './ViscoelasticFields';
import PiezoFields, { PZT5H } from './PiezoFields';
import FluidFields from './FluidFields';
import MagneticFields from './MagneticFields';
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

  it('fluid: preset sets μ and ρ; summary shows flow rates and Reynolds', () => {
    const setProp = vi.fn();
    render(<FluidFields props={{}} setProp={setProp} />);
    expect(screen.getByText('Falta la viscosidad μ.')).toBeTruthy();
    fireEvent.click(screen.getByText('Glicerina 20 °C'));
    expect(setProp).toHaveBeenCalledWith('mu', 1.41);
    expect(setProp).toHaveBeenCalledWith('rho', 1261);
    render(<SummaryRows header={{ fields: [], summary: { fluid: { mu: 1.41, max_velocity_m_s: 2e-3, min_pressure_pa: 0,
      max_pressure_pa: 100, mass_balance_error: 1e-12, reynolds: 2.5,
      flow_rates: [{ face_set: 'tip', label: 'Salida', flow_m3_s: 3e-9 }, { face_set: 'z0', flow_m3_s: 0 }] } } }} />);
    expect(screen.getByText('Caudal Salida')).toBeTruthy();
    expect(screen.queryByText('Caudal z0')).toBeNull();
    expect(screen.getByText(/⚠ > 1/)).toBeTruthy();
    expect(screen.queryByText('k')).toBeNull();
  });

  it('fluid: Navier-Stokes toggle, ρ check and iteration summary', () => {
    const setProp = vi.fn();
    render(<FluidFields props={{ mu: 1e-3, flow_model: 'navier_stokes' }} setProp={setProp} />);
    expect(screen.getByText(/necesita la densidad/)).toBeTruthy();
    fireEvent.click(screen.getByText('Stokes (Re ≪ 1)'));
    expect(setProp).toHaveBeenCalledWith('flow_model', 'stokes');
    render(<SummaryRows header={{ fields: [], summary: { fluid: { model: 'navier_stokes', mu: 1e-3,
      max_velocity_m_s: 0.1, min_pressure_pa: 0, max_pressure_pa: 5, mass_balance_error: 1e-12, reynolds: 150,
      flow_rates: [], navier_stokes: { picard_iterations: 4, newton_iterations: 3, continuation_steps: 1,
        element_reynolds_max: 12 } } } }} />);
    expect(screen.getByText(/Navier-Stokes laminar · μ/)).toBeTruthy();
    expect(screen.getByText('4 Picard + 3 Newton')).toBeTruthy();
    expect(screen.queryByText(/⚠/)).toBeNull();                 // Re 150 is fine for Navier-Stokes
  });

  it('magnetic: NdFeB preset sets μr and Br; summary shows poles and permeance', () => {
    const setProp = vi.fn();
    render(<MagneticFields props={{}} setProp={setProp} />);
    expect(screen.getByText('Falta la permeabilidad μr.')).toBeTruthy();
    fireEvent.click(screen.getByText('NdFeB N42 (+Z)'));
    expect(setProp).toHaveBeenCalledWith('mu_r', 1.05);
    expect(setProp).toHaveBeenCalledWith('Br_z', 1.3);
    render(<SummaryRows header={{ fields: [], summary: { magnetic: { mu_r: 1000, Br_T: [0, 0, 0], max_B_T: 3.14,
      max_H_A_m: 2500, min_potential_A: 0, max_potential_A: 100, field_energy_J: 0.0157, permeance_H: 3.14e-6,
      poles: [{ label: 'N', potential_A: 100, flux_in_Wb: 3.14e-4 }] } } }} />);
    expect(screen.getByText('Polo N')).toBeTruthy();
    expect(screen.getByText('Permeancia (L para 1 vuelta)')).toBeTruthy();
    expect(screen.queryByText('k')).toBeNull();
  });
});
