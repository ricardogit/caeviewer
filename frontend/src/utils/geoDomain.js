/**
 * 2D water domain drawn on the map (FASE 10.5): a lon/lat polygon with one boundary kind per edge
 * (edge i = vertex i → vertex i+1). Pure helpers shared by the Mapa mode store and its tests.
 */
export const SEGMENT_KINDS = ['open', 'river', 'coast'];
export const SEGMENT_STYLE = {
  open: { color: '#29b6f6', label: 'Mar abierto' },
  river: { color: '#66bb6a', label: 'Río (caudal)' },
  coast: { color: '#a1887f', label: 'Costa (pared)' },
};
export const MESH_DEFAULTS = {
  h_min: 50, h_max: 2000, wavelength_points: 0, slope_factor: 0, growth: 0.25, d_min: 1, poi_size: null,
};

export function emptyDomain() {
  return {
    domain: [], segments: [], segment_labels: [], points: [], mesh: { ...MESH_DEFAULTS },
    land_datasets: [], bathymetry_datasets: [], zone_dataset: null, points_datasets: [], epsg: null,
  };
}

export const nextKind = (k) => SEGMENT_KINDS[(SEGMENT_KINDS.indexOf(k) + 1) % SEGMENT_KINDS.length];

/** Close a drawn ring: every edge starts as open sea. */
export function closeRing(vertices) {
  return { domain: vertices, segments: vertices.map(() => 'open'), segment_labels: vertices.map(() => null) };
}

/** Insert a vertex inside edge i (both halves keep its kind and label). */
export function insertVertex(d, i, lonlat) {
  const at = i + 1;
  return {
    ...d,
    domain: [...d.domain.slice(0, at), lonlat, ...d.domain.slice(at)],
    segments: [...d.segments.slice(0, at), d.segments[i], ...d.segments.slice(at)],
    segment_labels: [...d.segment_labels.slice(0, at), d.segment_labels[i], ...d.segment_labels.slice(at)],
  };
}

/** Remove vertex i: edges i−1 and i merge and keep the kind of edge i−1. Needs ≥ 4 vertices. */
export function removeVertex(d, i) {
  const n = d.domain.length;
  if (n <= 3) return d;
  const drop = i;                              // edge i disappears, edge i−1 now ends at vertex i+1
  return {
    ...d,
    domain: d.domain.filter((_, k) => k !== i),
    segments: d.segments.filter((_, k) => k !== drop),
    segment_labels: d.segment_labels.filter((_, k) => k !== drop),
  };
}

export function moveVertex(d, i, lonlat) {
  return { ...d, domain: d.domain.map((v, k) => (k === i ? lonlat : v)) };
}

export function setSegment(d, i, patch) {
  return {
    ...d,
    segments: d.segments.map((k, j) => (j === i && patch.kind ? patch.kind : k)),
    segment_labels: d.segment_labels.map((l, j) => (j === i && 'label' in patch ? patch.label || null : l)),
  };
}

/** Edge segments [[a, b], …] in lon/lat. */
export function edges(domain) {
  return domain.map((v, i) => [v, domain[(i + 1) % domain.length]]);
}

/** Does the polygon cross itself? (O(n²), fine for drawn domains.) */
export function selfIntersects(domain) {
  const n = domain.length;
  const cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  const hit = (p1, p2, q1, q2) => cross(p1, p2, q1) * cross(p1, p2, q2) < 0 && cross(q1, q2, p1) * cross(q1, q2, p2) < 0;
  for (let i = 0; i < n; i += 1) {
    for (let j = i + 2; j < n; j += 1) {
      if (i === 0 && j === n - 1) continue;
      if (hit(domain[i], domain[(i + 1) % n], domain[j], domain[(j + 1) % n])) return true;
    }
  }
  return false;
}

/** Spec for POST /api/geodata/mesh and the GEOMETRY node properties (shape domain_2d). */
export function domainSpec(d) {
  const mesh = Object.fromEntries(Object.entries(d.mesh || {}).filter(([, v]) => v !== null && v !== '' && v !== undefined));
  const spec = {
    domain: d.domain, segments: d.segments, segment_labels: d.segment_labels, mesh,
    points: (d.points || []).map((p) => ({ label: p.label, lon: p.lon, lat: p.lat, size: p.size ?? null })),
    land_datasets: d.land_datasets, bathymetry_datasets: d.bathymetry_datasets, points_datasets: d.points_datasets,
  };
  if (d.zone_dataset) spec.zone_dataset = d.zone_dataset;
  if (d.epsg) spec.epsg = d.epsg;
  return spec;
}

export function domainFromProps(props) {
  const e = emptyDomain();
  if (!props || props.shape !== 'domain_2d') return e;
  const n = (props.domain || []).length;
  return {
    ...e,
    ...Object.fromEntries(Object.keys(e).filter((k) => props[k] !== undefined).map((k) => [k, props[k]])),
    segments: props.segments?.length === n ? props.segments : Array(n).fill('open'),
    segment_labels: props.segment_labels?.length === n ? props.segment_labels : Array(n).fill(null),
    mesh: { ...MESH_DEFAULTS, ...(props.mesh || {}) },
  };
}

/** Depth colour (shallow light cyan → deep navy, sqrt scale), as in the backend preview PNG. */
export function depthColor(z, zmax) {
  if (z === null || z === undefined || Number.isNaN(z)) return 'rgb(144,164,174)';   // no bathymetry
  if (!(z > 0)) return 'rgb(180,160,120)';
  const t = Math.min(1, Math.sqrt(z / (zmax || 1)));
  const a = [198, 233, 247];
  const b = [8, 48, 107];
  const c = a.map((v, i) => Math.round(v * (1 - t) + b[i] * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export const fmtLen = (m) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);
