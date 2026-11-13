"""
Hito FASE 5 — "Mover el slider de carga en ROMExplorer actualiza el campo en < 100 ms".

1. Construye un ROM POD-Galerkin de la viga en voladizo T10 (E, ν, carga de punta variables).
2. Precisión: compara el ROM con la solución completa en puntos aleatorios del rango
   (no usados como snapshots): error relativo en u y en σvM máx.
3. Latencia: simula un barrido del slider de carga (200 posiciones). Para cada una mide la
   evaluación en servidor (ROMOnlineSolver.evaluate) + la reconstrucción del campo de superficie
   (equivalente numpy de romPack.reconstruct del navegador).
4. Opcional (--server URL --rom-id ID): round-trip real por socket.io (`rom_evaluate` con ack)
   contra un servidor en marcha.

Uso:  python validate_rom.py [--server http://localhost:8080 --rom-id <id>]
"""
import argparse
import os
import sys
import tempfile
import time

import numpy as np

from app.design.services.fem.mesh import FEMMesh
from app.design.services.rom.online_solver import ROMOnlineSolver
from app.design.services.rom.pod import PODROMBuilder, evaluate_arrays, latin_hypercube, von_mises_voigt, \
    stress_from_strain

LIMIT_MS = 100.0
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
SPEC = {
    'material': {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7850},
    'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
    'loads': [{'face_set': 'tip', 'force': [0, -1000, 0], 'label': 'Punta'}],
}
SPACE = {'E': [70e9, 210e9], 'nu': [0.25, 0.35], 'load_0': [100, 2000]}


def reconstruct_surface(rom, ur, lam, mu):
    """numpy twin of frontend/src/utils/romPack.js reconstruct()."""
    c = ur.astype(np.float32)
    disp = rom['surf_phi'] @ c                                  # (n, 3)
    eps = (rom['surf_strain'] @ c).astype(np.float64)           # (n, 6)
    vm = von_mises_voigt(stress_from_strain(eps, lam, mu))
    return np.linalg.norm(disp, axis=1), vm


def socket_round_trip(url, rom_id, n=100):
    import socketio
    sio = socketio.Client()
    sio.connect(url, transports=['polling', 'websocket'], wait_timeout=10)
    times = []
    try:
        for i, load in enumerate(np.linspace(100, 2000, n)):
            t0 = time.perf_counter()
            res = sio.call('rom_evaluate', {'rom_id': rom_id, 'params': {'load_0': float(load)}, 'seq': i},
                           timeout=10)
            times.append((time.perf_counter() - t0) * 1000)
            if 'error' in res:
                raise RuntimeError(res['error'])
    finally:
        sio.disconnect()
    return np.array(times)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    ap.add_argument('--rom-id')
    args = ap.parse_args()
    ok = True

    mesh = FEMMesh.generate_cantilever(1.0, 0.05, 0.05, n_along_length=20, order=2)
    print(f'Malla: {mesh.n_nodes} nodos T10, {mesh.n_dof_structural} GDL')
    b = PODROMBuilder(mesh, SPEC, SPACE, {'n_snapshots': 20, 'n_test': 0})
    t0 = time.perf_counter()
    rom = b.build()
    print(f"ROM: {rom['r']} modos de 20 snapshots en {time.perf_counter() - t0:.1f} s")

    # --- precisión en puntos nuevos
    errs_u, errs_vm = [], []
    for q in latin_hypercube(SPACE, 5, seed=7):
        p = b.full_params(q)
        u_f = b.full_solve(q)                                  # free DOFs
        ev = evaluate_arrays(rom, p, with_u=True)
        errs_u.append(np.linalg.norm(ev['u_free'] - u_f) / np.linalg.norm(u_f))
        u_full = np.zeros(mesh.n_dof_structural)
        u_full[rom['free']] = u_f
        vm_full = b._max_vm(u_full, q)
        errs_vm.append(abs(ev['max_von_mises_pa'] - vm_full) / vm_full)
    eu, evm = max(errs_u), max(errs_vm)
    print(f'Error vs. modelo completo (5 puntos nuevos): u {eu:.2e}, σvM máx {evm:.2e}')
    ok &= eu < 1e-3 and evm < 1e-3

    # --- latencia: barrido del slider de carga
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'rom.npz')
        np.savez(path, **{k: v for k, v in rom.items() if k not in ('validation', 'samples', 'build_s')})
        solver = ROMOnlineSolver()
        loaded = solver.load_rom('hito', path)
        server_ms, field_ms = [], []
        for load in np.linspace(100, 2000, 200):
            out = solver.evaluate('hito', {'load_0': float(load)})
            server_ms.append(out['response_ms'])
            t1 = time.perf_counter()
            reconstruct_surface(loaded, np.array(out['coefficients']), out['lambda'], out['mu'])
            field_ms.append((time.perf_counter() - t1) * 1000)
    server_ms, field_ms = np.array(server_ms), np.array(field_ms)
    total = server_ms + field_ms
    print(f"Superficie: {len(rom['surf_nodes'])} nodos")
    print(f'Evaluación servidor: mediana {np.median(server_ms):.3f} ms, p95 {np.percentile(server_ms, 95):.3f} ms')
    print(f'Reconstrucción campo: mediana {np.median(field_ms):.3f} ms, p95 {np.percentile(field_ms, 95):.3f} ms')
    print(f'Total (sin red): p95 {np.percentile(total, 95):.2f} ms  (límite {LIMIT_MS:.0f} ms)')
    ok &= np.percentile(total, 95) < LIMIT_MS

    if args.server and args.rom_id:
        rt = socket_round_trip(args.server, args.rom_id)
        print(f'Round-trip socket.io ({args.server}): mediana {np.median(rt):.1f} ms, '
              f'p95 {np.percentile(rt, 95):.1f} ms, máx {rt.max():.1f} ms')
        ok &= np.percentile(rt, 95) < LIMIT_MS

    print('HITO FASE 5:', 'CUMPLIDO' if ok else 'NO CUMPLIDO')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
