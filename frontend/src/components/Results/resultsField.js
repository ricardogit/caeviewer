/**
 * Pure helpers of the Results viewer (FASE 9): field extraction, range and deformation scale.
 * pack = parsePack(GET /api/design/solver/<run>/surface): xyz [mm], tris, u [mm], vm [MPa].
 */
export const FIELDS = {
  vm: { label: 'Von Mises', unit: 'MPa' },
  umag: { label: '|u|', unit: 'mm' },
  ux: { label: 'ux', unit: 'mm' },
  uy: { label: 'uy', unit: 'mm' },
  uz: { label: 'uz', unit: 'mm' },
  ep: { label: 'εp plástica', unit: '' },
  T: { label: 'Temperatura', unit: '°C' },
  q: { label: '|q| flujo', unit: 'W/m²' },
};

/** Fields present in a pack: header.fields lists the stored groups ('u', 'vm', 'T', 'q'). */
export function availableFields(pack) {
  const groups = pack?.header?.fields || ['u', 'vm'];
  const out = [];
  if (groups.includes('u')) out.push('vm', 'umag', 'ux', 'uy', 'uz');
  if (groups.includes('ep')) out.push('ep');
  if (groups.includes('T')) out.push('T', 'q');
  return out;
}

export function fieldValues(pack, field) {
  const n = pack.nNodes;
  const out = new Float32Array(n);
  const u = pack.u.data;
  if (field === 'vm' || field === 'T' || field === 'q' || field === 'ep') {
    out.set(pack[field].data);
  } else if (field === 'umag') {
    for (let i = 0; i < n; i += 1) out[i] = Math.hypot(u[3 * i], u[3 * i + 1], u[3 * i + 2]);
  } else {
    const c = { ux: 0, uy: 1, uz: 2 }[field];
    for (let i = 0; i < n; i += 1) out[i] = u[3 * i + c];
  }
  return out;
}

export function range(values) {
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    if (values[i] < lo) lo = values[i];
    if (values[i] > hi) hi = values[i];
  }
  return values.length ? [lo, hi] : [0, 0];
}

/** Model diagonal [mm] and the max surface displacement [mm]. */
export function geometryScale(pack) {
  const [lo, hi] = pack.header?.bbox_mm || [[0, 0, 0], [1, 1, 1]];
  const diag = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) || 1;
  const [, umax] = range(fieldValues(pack, 'umag'));
  return { diag, umax };
}

/** Deformation factor that draws the max displacement as 8 % of the model size (≥ 1: never shrink). */
export function autoScale(pack) {
  const { diag, umax } = geometryScale(pack);
  if (!(umax > 0)) return 1;
  return Math.max(1, (0.08 * diag) / umax);
}

/** Normalized colour coordinate; signed components use a symmetric range so 0 is the mid colour. */
export function normalizer(field, [lo, hi]) {
  if (field === 'ux' || field === 'uy' || field === 'uz') {
    const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1;
    return { min: -m, max: m, t: (v) => (v + m) / (2 * m) };
  }
  const span = hi - lo || 1;
  return { min: lo, max: hi, t: (v) => (v - lo) / span };
}

export const fmt = (v) => {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(2);
  return Number(v.toPrecision(4)).toString();
};
