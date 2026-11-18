// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import PlasticityFields, { defaultHardening } from './PlasticityFields';
import { availableFields, fieldValues } from '../Results/resultsField';

describe('PlasticityFields (FASE 2.5)', () => {
  beforeEach(() => cleanup());

  it('defaults the hardening law from what the node has', () => {
    expect(defaultHardening({})).toBe('perfect');
    expect(defaultHardening({ H: 2e9 })).toBe('linear');
    expect(defaultHardening({ hardening_table: { ep: [0, 0.1], sy: [1, 2] } })).toBe('fit');
    expect(defaultHardening({ hardening_type: 'voce', H: 1 })).toBe('voce');
  });

  it('shows the fields of the chosen law and edits them', () => {
    const setProp = vi.fn();
    const { rerender } = render(<PlasticityFields props={{ yield_strength: 250e6, H: 2e9 }} setProp={setProp} />);
    fireEvent.change(screen.getByLabelText('Módulo plástico H [Pa]'), { target: { value: '3e9' } });
    expect(setProp).toHaveBeenCalledWith('H', 3e9);
    rerender(<PlasticityFields props={{ hardening_type: 'voce' }} setProp={setProp} />);
    expect(screen.getByLabelText('Q [Pa]')).toBeTruthy();
    expect(screen.getByText('Falta el límite elástico σy.')).toBeTruthy();
    rerender(<PlasticityFields props={{ yield_strength: 1, hardening_table: { ep: [0, 0.05], sy: [250e6, 330e6], model: 'voce' } }}
      setProp={setProp} />);
    expect(screen.getByText(/2 puntos de la ley voce: σy de 250 a 330 MPa con εp hasta 5.0 %/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Descargar al final'));
    expect(setProp).toHaveBeenCalledWith('unload', true);
  });

  it('the results viewer offers εp when the run stored it', () => {
    const pack = { nNodes: 2, header: { fields: ['u', 'vm', 'ep'] }, u: { data: new Float32Array(6) },
      vm: { data: new Float32Array(2) }, ep: { data: Float32Array.from([0, 0.02]) } };
    expect(availableFields(pack)).toEqual(['vm', 'umag', 'ux', 'uy', 'uz', 'ep']);
    expect(fieldValues(pack, 'ep')[1]).toBeCloseTo(0.02);
  });
});
