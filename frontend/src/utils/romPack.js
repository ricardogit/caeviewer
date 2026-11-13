/**
 * ROM surface pack (FASE 5): binary parser + client-side field reconstruction.
 *
 * Layout from GET /api/design/rom/<id>/pack: uint32 header length, JSON header, padding to
 * 4 bytes, then the arrays {xyz (n,3) mm, tris (m,3) uint32, phi (n,3,r) m, strain (n,6,r)}.
 * With the reduced coefficients from the server (rom_evaluate) the surface displacement and
 * von Mises stress are rebuilt here, so a slider move costs one tiny socket round-trip.
 */

const DTYPES = { float32: Float32Array, uint32: Uint32Array, int32: Int32Array, float64: Float64Array };

export function parsePack(buffer) {
  const view = new DataView(buffer);
  const hlen = view.getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, hlen)));
  const start = 4 + hlen + ((4 - ((4 + hlen) % 4)) % 4);
  const arrays = {};
  header.arrays.forEach(({ name, dtype, shape, offset }) => {
    const T = DTYPES[dtype];
    const n = shape.reduce((a, b) => a * b, 1);
    arrays[name] = { data: new T(buffer, start + offset, n), shape };
  });
  return { r: header.r, nNodes: arrays.xyz.shape[0], ...arrays };
}

/**
 * coeffs: reduced coordinates (length r); lam, mu: Lamé constants [Pa].
 * Returns { disp: Float32Array(3n) [m], dispMag: Float32Array(n) [m], vm: Float32Array(n) [Pa],
 *           maxDisp, maxVm }.
 */
export function reconstruct(pack, coeffs, lam, mu) {
  const { r, nNodes } = pack;
  const phi = pack.phi.data;
  const strain = pack.strain.data;
  const disp = new Float32Array(3 * nNodes);
  const dispMag = new Float32Array(nNodes);
  const vm = new Float32Array(nNodes);
  const e = new Float64Array(6);
  let maxDisp = 0;
  let maxVm = 0;
  for (let i = 0; i < nNodes; i += 1) {
    let m2 = 0;
    for (let c = 0; c < 3; c += 1) {
      const base = (3 * i + c) * r;
      let s = 0;
      for (let k = 0; k < r; k += 1) s += phi[base + k] * coeffs[k];
      disp[3 * i + c] = s;
      m2 += s * s;
    }
    dispMag[i] = Math.sqrt(m2);
    if (dispMag[i] > maxDisp) maxDisp = dispMag[i];
    for (let c = 0; c < 6; c += 1) {
      const base = (6 * i + c) * r;
      let s = 0;
      for (let k = 0; k < r; k += 1) s += strain[base + k] * coeffs[k];
      e[c] = s;
    }
    const tr = e[0] + e[1] + e[2];
    const sx = lam * tr + 2 * mu * e[0];
    const sy = lam * tr + 2 * mu * e[1];
    const sz = lam * tr + 2 * mu * e[2];
    const txy = mu * e[3];
    const tyz = mu * e[4];
    const txz = mu * e[5];
    const v = Math.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy ** 2 + tyz ** 2 + txz ** 2));
    vm[i] = v;
    if (v > maxVm) maxVm = v;
  }
  return { disp, dispMag, vm, maxDisp, maxVm };
}
