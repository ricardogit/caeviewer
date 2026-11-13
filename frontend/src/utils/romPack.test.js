import { describe, it, expect } from 'vitest';
import { parsePack, reconstruct } from './romPack';

function buildPack(r, xyz, tris, phi, strain) {
  const arrays = [['xyz', 'float32', [xyz.length / 3, 3], new Float32Array(xyz)],
    ['tris', 'uint32', [tris.length / 3, 3], new Uint32Array(tris)],
    ['phi', 'float32', [xyz.length / 3, 3, r], new Float32Array(phi)],
    ['strain', 'float32', [xyz.length / 3, 6, r], new Float32Array(strain)]];
  let off = 0;
  const meta = arrays.map(([name, dtype, shape, a]) => {
    const m = { name, dtype, shape, offset: off };
    off += a.byteLength;
    return m;
  });
  const header = new TextEncoder().encode(JSON.stringify({ r, arrays: meta }));
  const pad = (4 - ((4 + header.length) % 4)) % 4;
  const buf = new ArrayBuffer(4 + header.length + pad + off);
  new DataView(buf).setUint32(0, header.length, true);
  new Uint8Array(buf, 4, header.length).set(header);
  let p = 4 + header.length + pad;
  arrays.forEach(([, , , a]) => { new Uint8Array(buf, p, a.byteLength).set(new Uint8Array(a.buffer)); p += a.byteLength; });
  return buf;
}

describe('romPack', () => {
  it('parses the binary layout (odd header length → padding)', () => {
    const buf = buildPack(2, [0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2], new Array(18).fill(0), new Array(36).fill(0));
    const p = parsePack(buf);
    expect(p.r).toBe(2);
    expect(p.nNodes).toBe(3);
    expect(Array.from(p.tris.data)).toEqual([0, 1, 2]);
    expect(p.xyz.data[3]).toBe(1);
  });

  it('reconstructs displacement and von Mises (uniaxial check)', () => {
    // one node, r = 2: mode 0 → ux = 1, mode 1 → uy = 1; strain mode 0 → εxx = 1
    const phi = [1, 0, 0, 1, 0, 0];                       // (1,3,2)
    const strain = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];   // (1,6,2)
    const p = parsePack(buildPack(2, [0, 0, 0], [0, 0, 0], phi, strain));
    const E = 200e9;
    const nu = 0;                                          // λ = 0, μ = E/2 → σxx = E εxx
    const out = reconstruct(p, [1e-3, 2e-3], 0, E / 2);
    expect(out.disp[0]).toBeCloseTo(1e-3, 9);
    expect(out.disp[1]).toBeCloseTo(2e-3, 9);
    expect(out.dispMag[0]).toBeCloseTo(Math.hypot(1e-3, 2e-3), 9);
    expect(out.vm[0] / (E * 1e-3)).toBeCloseTo(1, 5);      // von Mises of uniaxial = |σxx|
    expect(nu).toBe(0);
  });
});
