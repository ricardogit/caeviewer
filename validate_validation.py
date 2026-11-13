"""
Hito FASE 8 — "Un nuevo ensayo de tracción recalibra E del material con error < 2 %".

Parte 1 (hito): un material de la biblioteca con valores de catálogo erróneos (E 180 GPa,
σy 300 MPa) recibe un ensayo de tracción nuevo escrito como CSV (ruido de célula de carga 0.4 %
de la UTS, pie de curva, estricción; tramo elástico muestreado con extensómetro, como pide
ASTM E111 para medir E). Pasa por el camino real (parse_curve_csv → ModelRecalibrator.tensile):
  · modo 'replace': E dentro del 2 % del valor verdadero, R² después > 0.99 y mejor que antes;
  · modo 'bayes' con tres probetas sucesivas: E dentro del 2 % y la desviación estándar baja.

Parte 2: ensayo estructural de la pieza (viga en voladizo T10, sensores LVDT + galgas con 1 %
de ruido): la "pieza real" tiene E = 195 GPa; el modelo usa 210 GPa. El E efectivo identificado
debe quedar dentro del 2 %, y la correlación después de corregir la rigidez R² > 0.99.
Caso de control: si la diferencia no es de rigidez (giro del empotramiento, apoyo flexible) la
corrección de E no basta: R² después < 0.9 o error máximo > 15 % → se avisa que se revisen las
condiciones de contorno en vez de "calibrar" un E falso.

  Nota: datos sintéticos con valores verdaderos conocidos (para medir el error); no hay ensayos
  reales en el repo.

Uso:  python validate_validation.py
"""
import sys

import numpy as np

from app.design.services.fem.mesh import FEMMesh
from app.design.services.material.parametric import CURVE_MODELS, parse_curve_csv
from app.design.services.validation.recalibrator import ModelRecalibrator
from app.design.services.validation.sensors import MeshProbe, simulate_sensors

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

E_TRUE, SY_TRUE = 205000.0, 360.0          # MPa (S355-like, Ludwik)


class Material:                             # library material stand-in (no DB needed)
    def __init__(self, parameters, calibration=None):
        self.parameters = parameters
        self.calibration = calibration or {}


def tensile_csv(seed: int) -> str:
    rng = np.random.default_rng(seed)
    e = np.concatenate([np.linspace(0, 0.004, 400, endpoint=False), np.linspace(0.004, 0.20, 1600)])
    s = CURVE_MODELS['ludwik'].predict(e, np.array([E_TRUE, SY_TRUE, 520.0, 0.42]))
    neck = e > 0.16
    s[neck] *= 1 - 3 * (e[neck] - 0.16) ** 1.4
    s = s + rng.normal(0, 0.004 * s.max(), len(s))
    em = e + 0.0003                                                   # slack / toe
    return 'Deformación (%);Esfuerzo (MPa)\n' + '\n'.join(
        f'{a * 100:.5f};{b:.3f}'.replace('.', ',') for a, b in zip(em, s))


def part1() -> bool:
    print('── Parte 1: recalibración con un ensayo de tracción nuevo ───────────────')
    catalog = {'E': {'value': 180e9, 'std': 0.0, 'unit': 'Pa'}, 'nu': {'value': 0.3, 'std': 0.0, 'unit': ''},
               'rho': {'value': 7850, 'std': 0.0, 'unit': 'kg/m3'}, 'sigma_y': {'value': 300e6, 'std': 0.0, 'unit': 'Pa'}}
    rc = ModelRecalibrator()
    p = parse_curve_csv(tensile_csv(1))
    r = rc.tensile(Material(dict(catalog)), p['strain'], p['stress'], 'replace')
    E = r['new_parameters']['E']['value']
    eE = abs(E / (E_TRUE * 1e6) - 1)
    ok1 = eE < 0.02 and r['after']['r2'] > 0.99 and r['after']['r2'] > r['before']['r2']
    print(f"replace: {r['model_before']} → {r['fit']['label']}")
    print(f"   R² antes {r['before']['r2']:.4f} → después {r['after']['r2']:.5f}   "
          f"E 180.0 → {E / 1e9:.1f} ± {r['new_parameters']['E']['std'] / 1e9:.1f} GPa (verdadero {E_TRUE / 1e3:.0f}, "
          f"error {100 * eE:.2f} %)   δE = {100 * r['delta']['E']['rel_change']:+.1f} %   "
          f"σy 300 → {r['new_parameters']['sigma_y']['value'] / 1e6:.0f} MPa   {'OK' if ok1 else 'FALLA'}")

    mat = Material(dict(catalog))
    stds = []
    for seed in (11, 12, 13):
        p = parse_curve_csv(tensile_csv(seed))
        r = rc.tensile(mat, p['strain'], p['stress'], 'bayes')
        mat = Material(r['new_parameters'], {})                       # previous result is the next prior
        stds.append(r['new_parameters']['E']['std'])
    E = mat.parameters['E']['value']
    eE = abs(E / (E_TRUE * 1e6) - 1)
    ok2 = eE < 0.02 and stds[-1] < stds[0]
    print(f"bayes (3 probetas): E = {E / 1e9:.1f} GPa (error {100 * eE:.2f} %), "
          f"std {' → '.join(f'{s / 1e9:.2f}' for s in stds)} GPa   {'OK' if ok2 else 'FALLA'}")
    return ok1 and ok2


def part2() -> bool:
    from app.design.services.rom.pod import PODROMBuilder
    print('── Parte 2: ensayo estructural de la pieza (sensores) ───────────────────')
    spec = {'material': {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7850},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
            'loads': [{'face_set': 'tip', 'force': [0, -1000, 0]}]}
    mesh = FEMMesh.generate_cantilever(0.5, 0.025, 0.025, n_along_length=20, order=2)
    b = PODROMBuilder(mesh, spec, {'E': [1e11, 3e11]}, {'n_snapshots': 2})
    b._setup()

    def field(E):
        u = np.zeros(mesh.n_dof_structural)
        u[b.free] = b.full_solve({'E': E})
        return u.reshape(-1, 3)

    sensors = ([{'label': f'LVDT@{x}', 'x': x, 'y': 0.0, 'z': 12.5, 'quantity': 'uy'} for x in (125, 250, 375, 500)] +
               [{'label': f'G@{x}', 'x': x, 'y': 25.0, 'z': 12.5, 'quantity': 'strain', 'direction': [1, 0, 0]}
                for x in (60, 180, 300)])
    probe = MeshProbe(mesh.nodes, mesh.elements)
    rng = np.random.default_rng(8)
    sim = simulate_sensors(probe, field(210e9), sensors)['simulated']

    true = simulate_sensors(probe, field(195e9), sensors)['simulated']
    measured = true * (1 + rng.normal(0, 0.01, len(true)))
    r = ModelRecalibrator.structural_stiffness(sim, measured, 210e9, groups=[s['quantity'] for s in sensors])
    eE = abs(r['E_new'] / 195e9 - 1)
    ok1 = eE < 0.02 and r['after']['r2'] > 0.99
    print(f"rigidez: R² antes {r['before']['r2']:.4f} (error máx {100 * r['before']['max_rel_error']:.1f} %) → "
          f"después {r['after']['r2']:.5f}   E efectivo {r['E_new'] / 1e9:.1f} ± {r['E_std'] / 1e9:.1f} GPa "
          f"(verdadero 195, error {100 * eE:.2f} %)   {'OK' if ok1 else 'FALLA'}")

    # control: flexible clamp → rigid rotation θ of the beam about the root (LVDTs see θ·x, gauges nothing)
    theta = 0.6 * abs(true[3]) / 500.0
    wrong = true.copy()
    for i, s in enumerate(sensors):
        if s['quantity'] == 'uy':
            wrong[i] -= theta * s['x']
    wrong *= 1 + rng.normal(0, 0.01, len(wrong))
    r2 = ModelRecalibrator.structural_stiffness(sim, wrong, 210e9, groups=[s['quantity'] for s in sensors])
    flagged = r2['after']['r2'] < 0.9 or r2['after']['max_rel_error'] > 0.15
    print(f"control (empotramiento flexible): después R² {r2['after']['r2']:.3f}, error máx "
          f"{100 * r2['after']['max_rel_error']:.0f} % → {'se avisa: no es un problema de E' if flagged else 'NO detectado'}"
          f"   {'OK' if flagged else 'FALLA'}")
    return ok1 and flagged


if __name__ == '__main__':
    ok = part1()
    ok = part2() and ok
    print('\nHITO FASE 8:', 'CUMPLIDO' if ok else 'NO CUMPLIDO')
    sys.exit(0 if ok else 1)
