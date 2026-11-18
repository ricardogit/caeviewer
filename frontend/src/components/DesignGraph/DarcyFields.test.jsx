// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import axios from 'axios';
import DarcyFields, { HeadBCFields, DarcyLoadFields } from './DarcyFields';
import TransportFields from './TransportFields';
import { SummaryRows } from '../Results/ResultsViewer';

vi.mock('axios');

describe('Darcy fields (FASE 10.6)', () => {
  beforeEach(() => {
    cleanup();
    axios.get.mockResolvedValue({ data: { runs: [] } });
  });

  it('aquifer preset, zones and pumping-test time settings', () => {
    const setProp = vi.fn();
    render(<DarcyFields props={{ transient: true }} setProp={setProp} />);
    fireEvent.click(screen.getByText('Arena'));
    expect(setProp).toHaveBeenCalledWith('K', 1e-4);
    expect(setProp).toHaveBeenCalledWith('porosity', 0.3);
    fireEvent.click(screen.getByText('Zona'));
    expect(setProp).toHaveBeenCalledWith('K_zones', [expect.objectContaining({ label: 'Zona 1' })]);
    fireEvent.change(screen.getByLabelText('Crecimiento Δt'), { target: { value: '1.08' } });
    expect(setProp).toHaveBeenCalledWith('dt_growth', 1.08);
    expect(screen.getByText('Piezómetros (carga en el tiempo)')).toBeTruthy();
  });

  it('head BC and well at a point', () => {
    const setProp = vi.fn();
    render(<HeadBCFields props={{}} setProp={setProp} showFaceSet />);
    fireEvent.change(screen.getByLabelText('Carga hidráulica h [m]'), { target: { value: '12' } });
    expect(setProp).toHaveBeenCalledWith('head', 12);
    cleanup();
    render(<DarcyLoadFields lt="well" props={{ at_point: true }} setProp={setProp} showFaceSet />);
    expect(screen.getByLabelText('x [mm]')).toBeTruthy();
    expect(screen.queryByLabelText('Conjunto de caras (viga de prueba)')).toBeNull();
  });

  it('transport in a porous medium lists Darcy runs and shows retardation', async () => {
    axios.get.mockResolvedValue({ data: { runs: [
      { run_id: 'dddddddd-1', status: 'done', physics: ['darcy'], n_nodes: 10, created_at: '2026-11-15T10:00' },
      { run_id: 'ssssssss-2', status: 'done', physics: ['structural'] },
    ] } });
    render(<TransportFields props={{ velocity_source: 'run', porous: true, species: [{ name: 'N' }] }} setProp={vi.fn()} />);
    expect(await screen.findByLabelText('Run de fluido')).toBeTruthy();
    expect(screen.getByLabelText('Retardo R')).toBeTruthy();
    expect(screen.getByLabelText('α_L [m]')).toBeTruthy();
  });

  it('results: Darcy summary rows', () => {
    const header = { fields: [], extra_fields: [], summary: { element_type: 'T10', darcy: {
      steady: false, time: { scheme: 'bdf2', n_steps: 80, dt_first: 14.7, dt_last: 6414 }, K: 1e-4, zones: [],
      min_head_m: -14, max_head_m: 0, max_drawdown_m: 14, max_darcy_flux_m_d: 1, max_pore_velocity_m_d: 4,
      wells: [{ label: 'P1', rate_m3_s: 0.01, head_m: -14, drawdown_m: 14 }], balance_error: 1e-13 } } };
    render(<SummaryRows header={header} />);
    expect(screen.getByText('Pozo P1')).toBeTruthy();
    expect(screen.getByText('Descenso máx.')).toBeTruthy();
    expect(screen.getByText('Balance de agua')).toBeTruthy();
  });
});
