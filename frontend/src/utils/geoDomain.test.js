import { describe, it, expect } from 'vitest';
import {
  closeRing, domainFromProps, domainSpec, emptyDomain, insertVertex, nextKind, removeVertex, selfIntersects, setSegment,
} from './geoDomain';

const square = [[0, 0], [1, 0], [1, 1], [0, 1]];

describe('geoDomain', () => {
  it('closes a ring with open edges and cycles kinds', () => {
    const r = closeRing(square);
    expect(r.segments).toEqual(['open', 'open', 'open', 'open']);
    expect(nextKind('open')).toBe('river');
    expect(nextKind('coast')).toBe('open');
  });

  it('keeps one kind per edge when inserting and removing vertices', () => {
    let d = { ...emptyDomain(), ...closeRing(square) };
    d = setSegment(d, 1, { kind: 'coast', label: 'Costa este' });
    d = insertVertex(d, 1, [1, 0.5]);                 // splits edge 1
    expect(d.domain).toHaveLength(5);
    expect(d.segments).toEqual(['open', 'coast', 'coast', 'open', 'open']);
    expect(d.segment_labels[2]).toBe('Costa este');
    d = removeVertex(d, 2);                           // merges the two halves back
    expect(d.domain).toEqual(square);
    expect(d.segments).toEqual(['open', 'coast', 'open', 'open']);
    d = removeVertex(d, 0);                           // edges 3 and 0 merge, keep edge 3's kind
    expect(d.domain).toEqual([[1, 0], [1, 1], [0, 1]]);
    expect(d.segments).toEqual(['coast', 'open', 'open']);
    expect(removeVertex(d, 0)).toBe(d);               // a triangle cannot lose a vertex
  });

  it('detects self-intersection', () => {
    expect(selfIntersects(square)).toBe(false);
    expect(selfIntersects([[0, 0], [1, 1], [1, 0], [0, 1]])).toBe(true);
  });

  it('round-trips the GEOMETRY node properties', () => {
    const d = {
      ...emptyDomain(), ...closeRing(square), land_datasets: ['a'], bathymetry_datasets: ['b', 'c'],
      points: [{ label: 'P1', lon: 0.5, lat: 0.5, size: 40 }], mesh: { h_min: 20, h_max: 500, poi_size: null },
    };
    const spec = domainSpec(d);
    expect(spec.mesh).toEqual({ h_min: 20, h_max: 500 });
    expect(spec.zone_dataset).toBeUndefined();
    const back = domainFromProps({ shape: 'domain_2d', ...spec });
    expect(back.domain).toEqual(square);
    expect(back.bathymetry_datasets).toEqual(['b', 'c']);
    expect(back.mesh.h_min).toBe(20);
    expect(back.mesh.growth).toBe(0.25);
    expect(domainFromProps({ shape: 'beam' }).domain).toEqual([]);
  });
});
