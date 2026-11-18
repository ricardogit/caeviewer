// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import axios from 'axios';
import TransportFields, { ConcentrationBCFields, SpeciesLoadFields, SP_SPECIES } from './TransportFields';
import { SummaryRows } from '../Results/ResultsViewer';
import { availableFields, fieldMeta } from '../Results/resultsField';
import useDesignStore from '../../stores/designStore';

vi.mock('axios');

describe('transport fields (FASE 10.1)', () => {
  beforeEach(() => {
    cleanup();
    axios.get.mockResolvedValue({ data: { runs: [] } });
  });

  it('Streeter–Phelps switches to the BOD + oxygen-deficit species', () => {
    const setProp = vi.fn();
    render(<TransportFields props={{}} setProp={setProp} />);
    expect(screen.getByTestId('species-0')).toBeTruthy();
    fireEvent.click(screen.getByText('Streeter–Phelps'));
    expect(setProp).toHaveBeenCalledWith('reaction_model', 'streeter_phelps');
    expect(setProp).toHaveBeenCalledWith('species', SP_SPECIES);
  });

  it('edits a species and adds a control point', () => {
    const setProp = vi.fn();
    render(<TransportFields props={{ species: [{ name: 'A', D: 1e-6 }] }} setProp={setProp} />);
    fireEvent.change(screen.getByLabelText('nombre especie 1'), { target: { value: 'Nitrato' } });
    expect(setProp).toHaveBeenCalledWith('species', [{ name: 'Nitrato', D: 1e-6 }]);
    fireEvent.click(screen.getByText('Punto'));
    expect(setProp).toHaveBeenCalledWith('probes', [{ label: 'P1', x: 0, y: 0, z: 0 }]);
  });

  it('velocity from a fluid run lists only finished fluid runs', async () => {
    axios.get.mockResolvedValue({ data: { runs: [
      { run_id: 'aaaaaaaa-1', status: 'done', physics: ['fluid'], n_nodes: 10, created_at: '2026-11-15T10:00' },
      { run_id: 'bbbbbbbb-2', status: 'done', physics: ['structural'] },
    ] } });
    render(<TransportFields props={{ velocity_source: 'run' }} setProp={vi.fn()} />);
    expect(await screen.findByLabelText('Run de fluido')).toBeTruthy();
    expect(axios.get).toHaveBeenCalledWith('/api/design/solver/runs', { params: { limit: 200 } });
  });

  it('BC and loads pick the species of the study material', () => {
    useDesignStore.setState({ graphData: { nodes: [{ id: 'm', data: { node_type: 'MATERIAL', properties: {
      model_type: 'scalar_transport', species: [{ name: 'DBO' }, { name: 'Déficit de OD' }] } } }], edges: [] } });
    const setProp = vi.fn();
    render(<ConcentrationBCFields props={{}} setProp={setProp} showFaceSet />);
    expect(screen.getByLabelText('Especie')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Concentración impuesta'), { target: { value: '12' } });
    expect(setProp).toHaveBeenCalledWith('concentration', 12);
    cleanup();
    render(<SpeciesLoadFields lt="point_source" props={{}} setProp={setProp} showFaceSet />);
    expect(screen.getByLabelText('x [mm]')).toBeTruthy();
    expect(screen.getByText(/caudal es g\/s/)).toBeTruthy();
  });

  it('results: transport summary rows and series fields', () => {
    const header = {
      fields: [], times: [0, 1, 2], step: 2,
      extra_fields: [{ key: 'c0', label: 'Trazador', unit: 'mg/L', series: true, min_all: 0, max_all: 1 }],
      summary: { element_type: 'T10', transport: {
        n_species: 1, steady: false, time: { scheme: 'bdf2', dt: 0.1 }, velocity: { source: 'uniform', velocity_m_s: [1, 0, 0] },
        peclet_max: 21.4, stabilization: 'supg', courant_max: 0.15, mass_balance_error: 1e-14,
        species: [{ name: 'Trazador', unit: 'mg/L', max_c: 1, max_c_any_time: 1, mass_initial: 0, mass_final: 0.5,
          mass_unit: 'g', threshold: 0.5, volume_above_m3: 0.2, volume_above_max_m3: 0.2 }],
        probes: [{ label: 'P1', max: [0.9], t_max: [2], inside: true }] } },
    };
    render(<SummaryRows header={header} />);
    expect(screen.getByText('Péclet de elemento máx.')).toBeTruthy();
    expect(screen.getByText('Masa Trazador')).toBeTruthy();
    expect(screen.getByText('Punto P1')).toBeTruthy();
    expect(availableFields({ header })).toEqual(['x_c0']);
    expect(fieldMeta({ header }, 'x_c0')).toEqual({ label: 'Trazador', unit: 'mg/L' });
  });
});
