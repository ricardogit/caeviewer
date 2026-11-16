// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import axios from 'axios';
import ShallowWaterFields, { OutfallLoadFields, SWBCFields, WindLoadFields } from './ShallowWaterFields';
import useDesignStore from '../../stores/designStore';
import { SummaryRows } from '../Results/ResultsViewer';

vi.mock('axios');

const domainNode = {
  id: 'g', data: {
    node_type: 'GEOMETRY',
    properties: { shape: 'domain_2d', segments: ['open', 'coast', 'river'], segment_labels: ['Bocana', null, null] },
  },
};

describe('Shallow-water fields (FASE 10.3)', () => {
  beforeEach(() => {
    cleanup();
    axios.get.mockResolvedValue({ data: { datasets: [] } });
    useDesignStore.setState({ graphData: { nodes: [domainNode], edges: [] } });
  });

  it('material: Manning, Coriolis switch, duration and control points', () => {
    const setProp = vi.fn();
    render(<ShallowWaterFields props={{}} setProp={setProp} />);
    fireEvent.change(screen.getByLabelText('Manning n [s/m^⅓]'), { target: { value: '0.03' } });
    expect(setProp).toHaveBeenCalledWith('manning_n', 0.03);
    fireEvent.click(screen.getByText('Punto de control'));
    expect(setProp).toHaveBeenCalledWith('probes', [{ label: 'P1', lon: null, lat: null }]);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(setProp).toHaveBeenCalledWith('coriolis', false);
  });

  it('tide BC lists the domain sides and edits constituents', () => {
    const setProp = vi.fn();
    render(<SWBCFields props={{ bc_type: 'tide', constituents: [{ name: 'M2', amplitude: 1, phase: 0 }] }}
      setProp={setProp} />);
    fireEvent.click(screen.getByText('Bocana'));
    expect(setProp).toHaveBeenCalledWith('boundaries', ['edge0']);
    expect(screen.getByText('Lado 3 (río)')).toBeTruthy();
    expect(screen.getByText('Costa (tierra)')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('A [m] 1'), { target: { value: '1.4' } });
    expect(setProp).toHaveBeenCalledWith('constituents', [{ name: 'M2', amplitude: 1.4, phase: 0 }]);
  });

  it('river discharge and wind', () => {
    const setProp = vi.fn();
    render(<SWBCFields props={{ bc_type: 'river_inflow' }} setProp={setProp} />);
    fireEvent.change(screen.getByLabelText('Caudal Q'), { target: { value: '35' } });
    expect(setProp).toHaveBeenCalledWith('discharge', 35);
    cleanup();
    render(<WindLoadFields props={{}} setProp={setProp} />);
    fireEvent.change(screen.getByLabelText('Procedencia [° desde N]'), { target: { value: '225' } });
    expect(setProp).toHaveBeenCalledWith('direction', 225);
  });

  it('species on the material, inflow concentrations and the outfall', () => {
    const setProp = vi.fn();
    render(<ShallowWaterFields props={{}} setProp={setProp} />);
    fireEvent.click(screen.getByText('Bacterias (T90)'));
    expect(setProp).toHaveBeenCalledWith('species', [expect.objectContaining({ name: 'E. coli', decay_unit: 'T90_h' })]);
    expect(screen.queryByText(/pulso gaussiano/)).toBeNull();
    cleanup();
    const mat = { id: 'm', data: { node_type: 'MATERIAL', properties: { model_type: 'shallow_water',
      species: [{ name: 'E. coli', unit: 'UFC/100 mL' }, { name: 'DBO' }] } } };
    useDesignStore.setState({ graphData: { nodes: [domainNode, mat], edges: [] } });
    render(<SWBCFields props={{ bc_type: 'river_inflow', concentrations: { DBO: 3 } }} setProp={setProp} />);
    fireEvent.change(screen.getByLabelText('concentración E. coli'), { target: { value: '2000' } });
    expect(setProp).toHaveBeenCalledWith('concentrations', { DBO: 3, 'E. coli': 2000 });
    cleanup();
    render(<OutfallLoadFields props={{}} setProp={setProp} />);
    fireEvent.change(screen.getByLabelText('lon'), { target: { value: '-8.72' } });
    expect(setProp).toHaveBeenCalledWith('lon', -8.72);
    expect(screen.getByLabelText('concentración DBO')).toBeTruthy();
  });

  it('no 2-D domain in the study → hint', () => {
    useDesignStore.setState({ graphData: { nodes: [], edges: [] } });
    render(<SWBCFields props={{ bc_type: 'tide' }} setProp={vi.fn()} />);
    expect(screen.getByText(/no tiene un dominio 2D/)).toBeTruthy();
  });

  it('results summary rows', () => {
    const header = {
      fields: [], summary: {
        shallow_water: {
          order: 2, n_cells: 269, n_steps: 11626, dt_min_s: 1.2, dt_max_s: 2.1, manning_default: 0.025,
          coriolis: true, latitude_mean: 42.27, wind: true, max_speed_m_s: 0.3, froude_max: 0.02,
          boundaries: [{ label: 'Mar abierto oeste', kind: 'tide', volume_in_m3: 1e8, net_outflow_m3: -2e7 },
            { label: 'Costa', kind: 'wall', volume_in_m3: 0, net_outflow_m3: 0 }],
          wet_area_final_m2: 3e8, area_m2: 3e8, flooded_area_m2: 0, balance_error: 1e-16,
          probes: [{ label: 'Centro', min_eta_m: 0.5, max_eta_m: 3.6, max_speed_m_s: 0.1, depth_m: 40 }],
        },
      },
    };
    render(<SummaryRows header={header} />);
    expect(screen.getByText(/Aguas someras 2D · orden 2/)).toBeTruthy();
    expect(screen.getByText('Contorno Mar abierto oeste')).toBeTruthy();
    expect(screen.queryByText('Contorno Costa')).toBeNull();
    expect(screen.getByText('Punto Centro')).toBeTruthy();
  });
});
