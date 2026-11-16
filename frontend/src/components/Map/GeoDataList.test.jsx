// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import axios from 'axios';
import GeoDataList from './GeoDataList';
import useGeoMapStore from '../../stores/geoMapStore';
import { emptyDomain } from '../../utils/geoDomain';

vi.mock('axios');
vi.mock('../../services/socket', () => ({ getSocket: () => ({ on: vi.fn() }) }));
vi.mock('recharts', () => {
  const Stub = ({ children }) => <div>{children}</div>;
  return { LineChart: Stub, Line: Stub, XAxis: Stub, YAxis: Stub, Tooltip: Stub, ResponsiveContainer: Stub };
});

const DATASETS = [
  { id: 'c1', kind: 'coastline', name: 'Costa Galicia', source_crs: 'EPSG:25829', summary: { n_features: 2, geometry_types: { Polygon: 2 } } },
  { id: 'b1', kind: 'bathymetry', name: 'GEBCO', has_preview: true, bbox: [-9, 42, -8, 43], source_crs: 'EPSG:4326',
    summary: { kind: 'grid', nx: 81, ny: 51, depth_min_m: 2, depth_max_m: 80, convention: 'elevation' } },
  { id: 'f1', kind: 'forcing', name: 'Marea Vigo', summary: { kind: 'harmonics', constituents: ['M2', 'S2'], range_m: 3.2 } },
];

describe('GeoDataList', () => {
  beforeEach(() => {
    cleanup();
    vi.resetAllMocks();
    useGeoMapStore.setState({ datasets: [], visible: {}, layers: {}, d: emptyDomain(), error: null, subscribed: true });
    axios.get.mockImplementation((url) => Promise.resolve({ data: url === '/api/geodata' ? { datasets: DATASETS } : { type: 'FeatureCollection', features: [] } }));
  });

  it('lists datasets by kind with summaries and uses them in the domain', async () => {
    render(<GeoDataList />);
    await waitFor(() => expect(screen.getByText('Costa Galicia')).toBeTruthy());
    expect(screen.getByText(/rejilla 81×51 · 2.0–80.0 m · cota \(GEBCO\)/)).toBeTruthy();
    expect(screen.getByText(/armónicos M2 S2/)).toBeTruthy();
    expect(screen.getByText('origen EPSG:25829 → WGS84')).toBeTruthy();
    const boxes = screen.getAllByRole('checkbox');
    fireEvent.click(boxes[1]);                                   // bathymetry → priority #1
    expect(useGeoMapStore.getState().d.bathymetry_datasets).toEqual(['b1']);
    await waitFor(() => expect(screen.getByText('#1')).toBeTruthy());
    fireEvent.click(boxes[0]);
    expect(useGeoMapStore.getState().d.land_datasets).toEqual(['c1']);
  });

  it('uploads with kind and CRS, and reports errors', async () => {
    axios.post.mockRejectedValueOnce({ response: { data: { error: 'El TIFF no tiene georreferencia' } } });
    render(<GeoDataList />);
    fireEvent.change(screen.getByLabelText('CRS si el archivo no lo indica'), { target: { value: 'EPSG:25829' } });
    const file = new File(['x'], 'costa.zip');
    fireEvent.change(screen.getByTestId('geodata-file'), { target: { files: [file] } });
    await waitFor(() => expect(axios.post).toHaveBeenCalled());
    const form = axios.post.mock.calls[0][1];
    expect(form.get('kind')).toBe('coastline');
    expect(form.get('crs')).toBe('EPSG:25829');
    await waitFor(() => expect(screen.getByText('El TIFF no tiene georreferencia')).toBeTruthy());
  });
});
