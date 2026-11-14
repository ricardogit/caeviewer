// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';
import MaterialImportDialog from './MaterialImportDialog';

vi.mock('axios');

const PLAN = {
  filename: 'm.csv', mode: 'skip', notes: ['«Límite elástico» sin unidad: se interpreta en MPa.'],
  columns: [{ column: 'Material', property: 'name' }, { column: 'E [GPa]', property: 'E', unit: 'gpa' }],
  rows: [
    { row: 2, name: 'Mi aluminio', category: 'Aluminio', action: 'create', errors: [], warnings: [],
      parameters: { E: { value: 69e9 }, nu: { value: 0.33 }, alpha: { value: 23.6e-6 } } },
    { row: 3, name: 'Sin E', category: null, action: 'error', errors: ['Falta E (obligatorio).'], warnings: [],
      parameters: { nu: { value: 0.3 } } },
  ],
  counts: { create: 1, update: 0, skip: 0, error: 1 },
};

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

describe('MaterialImportDialog', () => {
  it('previews the file, shows row errors and imports the valid rows', async () => {
    axios.post.mockImplementation((url) => Promise.resolve({
      data: url.endsWith('/preview') ? PLAN : { ...PLAN, material_ids: ['n1'] },
    }));
    const onImported = vi.fn();
    render(<MaterialImportDialog open onClose={() => {}} onImported={onImported} />);
    const file = new File(['x'], 'm.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('import-file'), { target: { files: [file] } });
    expect(await screen.findByText('Mi aluminio')).toBeTruthy();
    expect(screen.getByText('69')).toBeTruthy();                       // E in GPa
    expect(screen.getByText('23.6')).toBeTruthy();                     // α in µm/m·K
    expect(screen.getByText('Falta E (obligatorio).')).toBeTruthy();
    expect(screen.getByText(/sin unidad/)).toBeTruthy();
    fireEvent.click(screen.getByText('Importar 1 material'));
    await waitFor(() => expect(onImported).toHaveBeenCalledWith(['n1']));
    expect(axios.post).toHaveBeenLastCalledWith('/api/design/material/import', expect.any(FormData));
    expect(await screen.findByText(/1 nuevos/)).toBeTruthy();
  });

  it('re-previews when the duplicate mode changes', async () => {
    axios.post.mockResolvedValue({ data: PLAN });
    render(<MaterialImportDialog open onClose={() => {}} />);
    fireEvent.change(screen.getByTestId('import-file'), { target: { files: [new File(['x'], 'm.csv')] } });
    await screen.findByText('Mi aluminio');
    fireEvent.click(screen.getByText('Actualizar existentes'));
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1].get('on_duplicate')).toBe('update');
  });
});
