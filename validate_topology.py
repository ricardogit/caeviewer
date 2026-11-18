"""FASE 4 hito — SIMP on a plate produces the classic "bridge".

Plate 200 × 100 × 10 mm (x: span, y: height, z: thickness), T4. Supports: bottom patches at
both ends, pinned (the arch thrust goes into the supports; with a roller a bottom tie appears,
i.e. a bowstring arch). z = 0 face restrained in z (plane condition, not a support, so it is
*not* kept solid). Load: 10 kN downwards spread on the top face (deck). Volume fraction 0.3.

Expected: a deck-arch bridge — inclined members from the supports up to the deck, void under
mid-span, symmetric. Checks:
  1. volume fraction 0.30 ± 0.01, grayness < 10 %
  2. compliance of the black/white design < 20 % of the uniform starting design
  3. symmetry: IoU(design, mirror) > 0.85
  4. supports solid, lower half of mid-span void (no tie: thrust goes to the supports)
  5. one connected solid region joining both supports to the deck
Optional arguments: mesh size [m] (default 0.004), hole radius [m] (default 0), output PNG.
"""
import sys
import time

import numpy as np

from app.design.services.fem.constitutive import build_material
from app.design.services.fem.mesh import FEMMesh
from app.design.services.topology.simp import SIMPOptimizer

L, H, T = 0.2, 0.1, 0.01


def raster(c, rho, W=400, Hp=200):
    from scipy.ndimage import distance_transform_edt
    ix = np.clip((c[:, 0] / L * W).astype(int), 0, W - 1)
    iy = np.clip(((1 - c[:, 1] / H) * Hp).astype(int), 0, Hp - 1)
    acc = np.zeros((Hp, W))
    cnt = np.zeros((Hp, W))
    np.add.at(acc, (iy, ix), rho)
    np.add.at(cnt, (iy, ix), 1)
    img = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    idx = distance_transform_edt(np.isnan(img), return_distances=False, return_indices=True)
    return img[tuple(idx)]


def main():
    h = float(sys.argv[1]) if len(sys.argv) > 1 else 0.004
    hole = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    png = sys.argv[3] if len(sys.argv) > 3 else None
    t0 = time.perf_counter()
    mesh = FEMMesh.generate_plate(L, H, T, h, hole_radius=hole)
    D = build_material({'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3}).get_D_matrix()
    bcs = [{'face_set': 'support_left', 'dofs': [0, 1]}, {'face_set': 'support_right', 'dofs': [0, 1]},
           {'face_set': 'back', 'dofs': [2], 'keep_solid': False}]
    loads = [{'face_set': 'top', 'force': [0, -10000, 0]}]

    def prog(it):
        if it['iter'] % 20 == 0:
            print(f"  it {it['iter']:3d}  C = {it['compliance']:.4e}  V = {it['volume_fraction']:.3f}  "
                  f"β = {it['beta']:4.0f}  gris = {it['grayness']:.3f}", flush=True)

    print(f'Placa {L*1e3:.0f}×{H*1e3:.0f}×{T*1e3:.0f} mm, h = {h*1e3:.1f} mm: {mesh.n_elements:,} T4')
    opt = SIMPOptimizer(mesh, D, loads, bcs, {'volume_fraction': 0.3, 'max_iter': 250}, progress=prog)
    r = opt.run()
    img = raster(opt.centroids, r['densities'])
    bw = img >= 0.5
    Hp, W = bw.shape
    iou = (bw & bw[:, ::-1]).sum() / max((bw | bw[:, ::-1]).sum(), 1)
    sup = 0.5 * (bw[int(0.85 * Hp):, :int(0.06 * W)].mean() + bw[int(0.85 * Hp):, -int(0.06 * W):].mean())
    under = bw[int(0.5 * Hp):, int(0.3 * W):int(0.7 * W)].mean()
    from scipy.ndimage import label
    lab, _ = label(bw)
    deck = set(np.unique(lab[:3][bw[:3]]))
    left = set(np.unique(lab[-3:, :int(0.06 * W)][bw[-3:, :int(0.06 * W)]]))
    right = set(np.unique(lab[-3:, -int(0.06 * W):][bw[-3:, -int(0.06 * W):]]))
    connected = bool(deck & left & right)
    checks = [
        ('Fracción de volumen 0.30 ± 0.01', abs(r['volume_fraction'] - 0.3) < 0.01, f"{r['volume_fraction']:.4f}"),
        ('Grises < 10 %', r['grayness'] < 0.10, f"{100 * r['grayness']:.1f} %"),
        ('Flexibilidad 0/1 < 20 % de la inicial', r['compliance_bw'] < 0.2 * r['compliance_initial'],
         f"{r['compliance_initial']:.4g} → {r['compliance_bw']:.4g} ({100 * r['compliance_bw'] / r['compliance_initial']:.1f} %)"),
        ('Simetría IoU > 0.85', iou > 0.85, f'{iou:.3f}'),
        ('Apoyos con material > 60 %', sup > 0.6, f'{100 * sup:.0f} %'),
        ('Mitad inferior del centro del vano vacía (< 5 %)', under < 0.05, f'{100 * under:.1f} %'),
        ('Apoyos conectados con el tablero', connected, 'sí' if connected else 'no'),
    ]
    print(f"\nIteraciones {r['n_iterations']} (convergió: {r['converged']}), {time.perf_counter() - t0:.0f} s")
    ok = True
    for name, passed, val in checks:
        ok &= bool(passed)
        print(f"  [{'OK' if passed else 'FALLA'}] {name}: {val}")
    if png:
        from PIL import Image
        Image.fromarray(np.where(bw, 0, 255).astype(np.uint8)).save(png)
        print('Imagen:', png)
    print(f"\nHito FASE 4 (puente por SIMP): {'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
