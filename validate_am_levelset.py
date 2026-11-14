"""FASE 4.2–4.3 hito — level-set topology optimization and the additive-manufacturing overhang filter.

Same bridge problem as validate_topology.py (plate 200 × 100 × 10 mm, pinned bottom supports,
10 kN on the deck, volume fraction 0.3), solved three ways:

  A. SIMP (reference)
  B. Level set (reaction-diffusion, Yamada 2010)
     1. 0/1 volume fraction 0.30 ± 0.005
     2. compliance of the 0/1 design within 10 % of SIMP's
     3. bridge topology: symmetric (IoU > 0.85), supports solid, void under mid-span, supports
        connected to the deck
  C. SIMP + AM overhang filter (Langelaar), printed along +X (the bridge lies on its left end), 45°.
     Along +Y plain SIMP is already almost self-supporting (inclined legs), so that direction proves
     little; along +X plain SIMP has ~38 % unsupported volume.
     4. unsupported volume (sharp printing recursion) < ⅓ of plain SIMP's
     5. down-facing overhang area of the iso-surface (facets steeper than 45° below the horizontal,
        off the plate) < 0.8 × plain SIMP's
     6. compliance penalty vs SIMP < 15 %
     7. still a connected bridge

Measured (h = 5 mm, 9055 T4): see the end of this docstring. The AM run is slow: PCG fails on the
near-void designs and every iteration falls back to a direct solve (~6 s), 250 iterations ≈ 26 min.
The AM design is not fully printable under the sharp check (~12 % unsupported remains: the smooth max
P = 40 and the grey elements are more permissive than the 0/1 recursion).

Measured, h = 5 mm:  SIMP C0/1 0.1581, 38.2 % unsupported, 9.4 % overhang area (40 s);
level set C0/1 0.1642 (+3.8 %), IoU 0.87, 69 it (27 s); SIMP + AM (+X) C0/1 0.1722 (+8.9 %),
11.9 % unsupported, 6.5 % overhang, 250 it without converging (≈ 28 min).

Usage: python validate_am_levelset.py [mesh size m, default 0.005] [output prefix for PNGs]
"""
import sys
import time

import numpy as np

from app.design.services.fem.constitutive import build_material
from app.design.services.fem.mesh import FEMMesh
from app.design.services.topology.am_constraints import AMConstraints, overhang_area_fraction
from app.design.services.topology.isosurface import extract_isosurface
from app.design.services.topology.levelset import LevelSetOptimizer
from app.design.services.topology.simp import SIMPOptimizer
from validate_topology import L, H, T, raster

BUILD = [1.0, 0.0, 0.0]
ANGLE = 45.0


def bridge_checks(opt, rho):
    from scipy.ndimage import label
    bw = raster(opt.centroids, rho) >= 0.5
    Hp, W = bw.shape
    iou = (bw & bw[:, ::-1]).sum() / max((bw | bw[:, ::-1]).sum(), 1)
    sup = 0.5 * (bw[int(0.85 * Hp):, :int(0.06 * W)].mean() + bw[int(0.85 * Hp):, -int(0.06 * W):].mean())
    under = bw[int(0.5 * Hp):, int(0.3 * W):int(0.7 * W)].mean()
    lab, _ = label(bw)
    deck = set(np.unique(lab[:3][bw[:3]]))
    left = set(np.unique(lab[-3:, :int(0.06 * W)][bw[-3:, :int(0.06 * W)]]))
    right = set(np.unique(lab[-3:, -int(0.06 * W):][bw[-3:, -int(0.06 * W):]]))
    return bw, iou, sup, under, bool(deck & left & right)


def printability(opt, rho):
    am = AMConstraints(opt.centroids, opt.vol, opt.h_mean, BUILD, ANGLE)
    unsup = am.unsupported_fraction((rho >= 0.5).astype(float))
    surf = extract_isosurface(opt.mesh.nodes, opt.mesh.elements, rho)
    oh = overhang_area_fraction(surf['vertices'], surf['faces'], BUILD, ANGLE, plate_tol=opt.h_mean)
    return unsup, oh['overhang_fraction']


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    h = float(sys.argv[1]) if len(sys.argv) > 1 else 0.005
    png = sys.argv[2] if len(sys.argv) > 2 else None
    mesh = FEMMesh.generate_plate(L, H, T, h)
    D = build_material({'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3}).get_D_matrix()
    bcs = [{'face_set': 'support_left', 'dofs': [0, 1]}, {'face_set': 'support_right', 'dofs': [0, 1]},
           {'face_set': 'back', 'dofs': [2], 'keep_solid': False}]
    loads = [{'face_set': 'top', 'force': [0, -10000, 0]}]
    print(f'Placa {L*1e3:.0f}×{H*1e3:.0f}×{T*1e3:.0f} mm, h = {h*1e3:.1f} mm: {mesh.n_elements:,} T4\n')

    runs = {}
    for key, Opt, st in [
        ('SIMP', SIMPOptimizer, {'volume_fraction': 0.3, 'max_iter': 250}),
        ('Level set', LevelSetOptimizer, {'volume_fraction': 0.3, 'tau': 2e-4, 'dt': 0.1, 'max_iter': 200}),
        ('SIMP + AM', SIMPOptimizer, {'volume_fraction': 0.3, 'max_iter': 250, 'am_constraint': True,
                                      'build_direction': BUILD, 'max_overhang_angle': ANGLE}),
    ]:
        t0 = time.perf_counter()
        opt = Opt(mesh, D, loads, bcs, st)
        r = opt.run()
        dt = time.perf_counter() - t0
        rho = opt.black_white(r['phi']) if key == 'Level set' else r['densities']
        bw, iou, sup, under, conn = bridge_checks(opt, rho)
        unsup, oh = printability(opt, rho)
        runs[key] = dict(r=r, iou=iou, sup=sup, under=under, conn=conn, unsup=unsup, oh=oh)
        print(f"{key:10s} it {r['n_iterations']:3d} (conv. {r['converged']}) {dt:5.0f} s · C0/1 = {r['compliance_bw']:.4g}"
              f" · V0/1 = {r['volume_fraction_bw']:.3f} · grises {100 * r['grayness']:.1f} % · sin soporte "
              f"{100 * unsup:.1f} % · voladizo {100 * oh:.1f} % del área", flush=True)
        if png:
            from PIL import Image
            name = f"{png}_{key.replace(' ', '').replace('+', '_').lower()}.png"
            Image.fromarray(np.where(bw, 0, 255).astype(np.uint8)).save(name)

    s, ls, am = runs['SIMP'], runs['Level set'], runs['SIMP + AM']
    c_s = s['r']['compliance_bw']
    checks = [
        ('B1 Level set: volumen 0/1 0.30 ± 0.005', abs(ls['r']['volume_fraction_bw'] - 0.3) < 0.005,
         f"{ls['r']['volume_fraction_bw']:.4f}"),
        ('B2 Level set: flexibilidad 0/1 a ≤ 10 % de SIMP', ls['r']['compliance_bw'] < 1.10 * c_s,
         f"{ls['r']['compliance_bw']:.4g} vs {c_s:.4g} ({100 * (ls['r']['compliance_bw'] / c_s - 1):+.1f} %)"),
        ('B3 Level set: puente (simetría > 0.85, apoyos > 60 %, centro inferior < 5 %, conectado)',
         ls['iou'] > 0.85 and ls['sup'] > 0.6 and ls['under'] < 0.05 and ls['conn'],
         f"IoU {ls['iou']:.3f}, apoyos {100 * ls['sup']:.0f} %, centro {100 * ls['under']:.1f} %, "
         f"{'conectado' if ls['conn'] else 'desconectado'}"),
        ('C4 AM: volumen sin soporte < ⅓ de SIMP', am['unsup'] < s['unsup'] / 3,
         f"{100 * s['unsup']:.1f} % → {100 * am['unsup']:.1f} %"),
        ('C5 AM: área en voladizo < 0.8 × SIMP', am['oh'] < 0.8 * s['oh'],
         f"{100 * s['oh']:.1f} % → {100 * am['oh']:.1f} %"),
        ('C6 AM: penalización de flexibilidad < 15 %', am['r']['compliance_bw'] < 1.15 * c_s,
         f"{100 * (am['r']['compliance_bw'] / c_s - 1):+.1f} %"),
        ('C7 AM: puente conectado', am['conn'] and am['sup'] > 0.6, 'sí' if am['conn'] else 'no'),
    ]
    print()
    ok = True
    for name, passed, val in checks:
        ok &= bool(passed)
        print(f"  [{'OK' if passed else 'FALLA'}] {name}: {val}")
    print(f"\nHito FASE 4.2–4.3 (level set + manufactura aditiva): {'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
