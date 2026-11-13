"""
Hito FASE 6 — "Ajustar un modelo elastoplástico a datos CSV de ensayo de tracción con R² > 0.99".

Parte 1 (hito): curvas de tracción realistas escritas como CSV (distintos formatos: %, mm/mm,
coma decimal, MPa/Pa/ksi, fuerza-desplazamiento) con ruido de medida, pie de curva y estricción,
generadas con leyes conocidas (Voce, Ramberg-Osgood, Ludwik). Cada una pasa por el camino real
(parse_curve_csv → ParametricMaterialModel.fit): el modelo elegido debe ser elastoplástico, con
R² > 0.99, σ0.2 dentro del 3 % y E dentro del 5 % de los valores verdaderos (E de un ensayo de
tracción con pocos puntos en el tramo elástico es poco preciso — por eso existe ASTM E111; el
ajuste informa su desviación estándar).
  Nota: son datos sintéticos con ley conocida (para medir el error); no hay ensayos reales en el repo.

Parte 2: propagación de incertidumbre en la viga en voladizo T10 con ROM (POD) frente a la
solución analítica de fiabilidad (σ ∝ F, F y σy normales → Pf = Φ(−β)) y frente a solves completos.

Uso:  python validate_material.py
"""
import sys

import numpy as np
from scipy import stats as st

from app.design.services.material.parametric import (ParametricMaterialModel, _hardening_curve, parse_curve_csv,
                                                     offset_yield)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

OFFSET = 0.002


def ro_curve(E, s0, n, e):
    """Ramberg-Osgood σ(ε) by dense inversion."""
    s = np.linspace(0, 3 * s0, 200000)
    eps = s / E + OFFSET * (s / s0) ** n
    return np.interp(e, eps, s)


def case_curves():
    rng = np.random.default_rng(2026)
    cases = []
    # Al 6061-T6: Voce, CSV ; + coma decimal + %
    e = np.linspace(0, 0.11, 1800)
    s = _hardening_curve(e, 69000, 276, lambda ep: 276 + 52 * (1 - np.exp(-38 * ep)))
    E_true, sy_true = 69e9, None
    cases.append(('Al 6061-T6 (Voce, %, coma decimal)', e, s, 69000, 'pct_comma', 0.09))
    # AISI 304: Ramberg-Osgood (gradual yield), mm/mm and Pa
    e = np.linspace(0, 0.35, 2500)
    s = ro_curve(193000, 260, 6.5, e)
    cases.append(('AISI 304 (Ramberg-Osgood, mm/mm, Pa)', e, s, 193000, 'pa', 0.30))
    # S355 steel: Ludwik, ksi
    e = np.linspace(0, 0.20, 2000)
    s = _hardening_curve(e, 205000, 360, lambda ep: 360 + 520 * np.power(np.maximum(ep, 0), 0.42))
    cases.append(('Acero S355 (Ludwik, ksi)', e, s, 205000, 'ksi', 0.16))
    # Cu C11000 half-hard: Voce, force-displacement (A = 20 mm², L0 = 50 mm)
    e = np.linspace(0, 0.12, 1500)
    s = _hardening_curve(e, 117000, 220, lambda ep: 220 + 60 * (1 - np.exp(-25 * ep)))
    cases.append(('Cobre C11000 (Voce, fuerza-desplazamiento)', e, s, 117000, 'force', 0.10))

    out = []
    for name, e, s, E, fmt, e_neck in cases:
        sy = offset_yield(e, s, E)
        s = s.copy()
        neck = e > e_neck
        s[neck] *= 1 - 3 * (e[neck] - e_neck) ** 1.4               # necking / fracture drop
        s = s + rng.normal(0, 0.004 * s.max(), len(s))             # 0.4 % of UTS load-cell noise
        em = e + 0.0003                                            # slack / toe
        if fmt == 'pct_comma':
            txt = 'Ensayo;;\nDeformación (%);Esfuerzo (MPa)\n' + '\n'.join(
                f'{a * 100:.5f};{b:.3f}'.replace('.', ',') for a, b in zip(em, s))
            parsed = parse_curve_csv(txt)
        elif fmt == 'pa':
            txt = 'strain [mm/mm],stress [Pa]\n' + '\n'.join(f'{a:.7f},{b * 1e6:.1f}' for a, b in zip(em, s))
            parsed = parse_curve_csv(txt)
        elif fmt == 'ksi':
            txt = 'Strain,Stress (ksi)\n' + '\n'.join(f'{a:.7f},{b / 6.894757:.4f}' for a, b in zip(em, s))
            parsed = parse_curve_csv(txt)
        else:
            A, L0 = 20.0, 50.0
            txt = 'Time (s)\tLoad (kN)\tExtension (mm)\n' + '\n'.join(
                f'{i * 0.1:.1f}\t{b * A / 1000:.5f}\t{a * L0:.5f}' for i, (a, b) in enumerate(zip(em, s)))
            parsed = parse_curve_csv(txt, area_mm2=A, gauge_mm=L0)
        out.append((name, parsed, E * 1e6, sy * 1e6))
    return out


def part1():
    print('── Parte 1: ajuste elastoplástico de curvas CSV ─────────────────────────')
    ok = True
    for name, parsed, E_true, sy_true in case_curves():
        r = ParametricMaterialModel().fit({'strain': parsed['strain'], 'stress': parsed['stress']})
        best = next(x for x in r['all_results'] if x['model'] == r['best_model'])
        E = r['parameters']['E']['value']
        sy = r['parameters']['sigma_02']['value']
        eE, esy = abs(E / E_true - 1), abs(sy / sy_true - 1)
        good = best['elastoplastic'] and r['r_squared'] > 0.99 and eE < 0.05 and esy < 0.03
        ok &= good
        print(f'{name}\n   modelo {r["label"]:36s} R² = {r["r_squared"]:.5f}   '
              f'E = {E / 1e9:6.1f} ± {r["parameters"]["E"]["std"] / 1e9:4.1f} GPa (error {100 * eE:4.2f} %)   σ0.2 = {sy / 1e6:6.1f} MPa (error {100 * esy:4.2f} %)'
              f'   {"OK" if good else "FALLA"}')
        others = ', '.join(f"{x['model']} {x['r2']:.4f}" for x in r['all_results'][1:4])
        print(f'   otros: {others}')
    return ok


def part2():
    import json
    from app.design.services.fem.mesh import FEMMesh
    from app.design.services.rom.pod import PODROMBuilder
    from app.design.services.material.uncertainty import UncertaintyPropagator, ROMEvaluator, FullEvaluator
    print('\n── Parte 2: propagación de incertidumbre (viga T10) ─────────────────────')
    spec = {'material': {'type': 'linear_elastic_isotropic', 'E': 69e9, 'nu': 0.33, 'rho': 2700},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
            'loads': [{'face_set': 'tip', 'force': [0, -1000, 0]}]}
    mesh = FEMMesh.generate_cantilever(1.0, 0.05, 0.05, n_along_length=20, order=2)
    b = PODROMBuilder(mesh, spec, {'E': [50e9, 90e9], 'load_0': [400, 1600]}, {'n_snapshots': 12, 'n_test': 0})
    rom = b.build()
    rom['params'] = json.loads(str(rom['params_json']))
    rom['space'] = json.loads(str(rom['space_json']))
    ev = ROMEvaluator(rom)
    c = ev.evaluate({'load_0': 1000.0})[0] / 1000.0                  # σvM máx por newton
    muF, sdF = 1000.0, 120.0
    muY, sdY = 1.35 * c * muF, 0.06 * 1.35 * c * muF
    dists = {'E': {'mean': 69e9, 'std': 2e9}, 'load_0': {'mean': muF, 'std': sdF}}
    P = UncertaintyPropagator()
    r = P.propagate_monte_carlo(ev, dists, 2000, 0.95, seed=3, failure={'yield_mean': muY, 'yield_std': sdY})
    R = r['result']
    beta = (muY - c * muF) / np.hypot(sdY, c * sdF)
    pf = st.norm.cdf(-beta)
    rel = R['reliability']
    print(f"ROM: {rom['r']} modos · 2000 muestras en {R['wall_time_s']:.2f} s")
    print(f"Pf Monte Carlo {rel['p_failure']:.4f} (IC 95 % {rel['p_failure_ci'][0]:.4f}–{rel['p_failure_ci'][1]:.4f})"
          f" · analítica {pf:.4f}")
    print(f"β Cornell {rel['beta_cornell']:.3f} · analítico {beta:.3f}")
    ok = rel['p_failure_ci'][0] <= pf <= rel['p_failure_ci'][1] and abs(rel['beta_cornell'] / beta - 1) < 0.05
    # displacement: E[u] = u0 · E[E0/E] · E[F/F0]  with E[1/E] ≈ (1 + cv²)/μ
    u0 = ev.evaluate({'load_0': 1000.0, 'E': 69e9})[1]
    cv = 2e9 / 69e9
    u_mean = u0 * (1 + cv ** 2 + 3 * cv ** 4)
    eu = abs(R['max_displacement']['mean'] / u_mean - 1)
    print(f"E[|u| máx] Monte Carlo {R['max_displacement']['mean'] * 1e3:.4f} mm · teórica {u_mean * 1e3:.4f} mm "
          f"(error {100 * eu:.2f} %, error estándar MC {100 * R['max_displacement']['sem'] / u_mean:.2f} %)")
    ok &= eu < 4 * R['max_displacement']['sem'] / u_mean + 1e-3
    full = P.propagate_monte_carlo(FullEvaluator(PODROMBuilder(mesh, spec, {'E': [50e9, 90e9]}, {'n_snapshots': 2})),
                                   dists, 40, seed=3)
    d = np.max(np.abs(full['samples']['max_vm'] / r['samples']['max_vm'][:40] - 1))
    print(f'ROM vs solves completos (mismas 40 muestras): diferencia máx. en σvM máx {d:.1e}')
    ok &= d < 1e-4
    return ok


if __name__ == '__main__':
    a = part1()
    b = part2()
    print('\nHITO FASE 6:', 'CUMPLIDO' if a and b else 'NO CUMPLIDO')
    sys.exit(0 if a and b else 1)
