"""Hito: orthotropic materials (linear elasticity + conduction + thermal expansion along material axes).

  1. an orthotropic material with isotropic constants and rotated axes reproduces the isotropic solution
  2. off-axis tension of a CFRP bar (fibres at θ in the xy plane): apparent modulus σ/εx = Ex(θ) (classical
     laminate formula) and the shear coupling γxy = S̄16 σ — exact (uniform stress state, statically determinate
     supports)
  3. CFRP cantilever (L/h = 40), fibres along the beam and across it: tip deflection vs Timoshenko with the
     modulus along the beam and the transverse shear modulus of the bending plane
  4. conduction patch test with a rotated conductivity tensor: linear T, flux q = −K∇T exact (off-axis
     component included)
  5. free thermal expansion with rotated α: stress-free, strain = Rᵀ diag(α) R ΔT

Usage: python validate_orthotropic.py [--server http://127.0.0.1:8080]
  --server: an orthotropic study through the graph and the job queue (fibres rotated 90° → deflection ratio).
"""
import argparse
import sys
import time

import numpy as np

CFRP = dict(E1=140e9, E2=10e9, E3=10e9, G12=5e9, G13=5e9, G23=3.5e9, nu12=0.3, nu13=0.3, nu23=0.45)


def axes_xy(deg):
    t = np.radians(deg)
    return {'axis_1': [float(np.cos(t)), float(np.sin(t)), 0.0], 'axis_2': [float(-np.sin(t)), float(np.cos(t)), 0.0]}


def ortho(**kw):
    return {'type': 'linear_elastic_orthotropic', 'rho': 1600.0, **CFRP, **kw}


def bar_mesh(L=0.05, W=0.01, H=0.01, n=6, order=2):
    """Box with point supports p0 = (0,0,0) and p1 = (0,H,0) for statically determinate BCs."""
    from app.design.services.fem.mesh import FEMMesh
    m = FEMMesh.generate_cantilever(L, W, H, n, order=order)
    d = np.linalg.norm(m.nodes - [0, 0, 0], axis=1)
    m.node_sets['p0'] = np.array([int(np.argmin(d))])
    d = np.linalg.norm(m.nodes - [0, H / 2, 0] - [0, H / 2, 0], axis=1)
    m.node_sets['p1'] = np.array([int(np.argmin(d))])
    return m


def bar_bcs():
    return [{'face_set': 'fixed', 'dofs': [0]}, {'node_set': 'p0', 'dofs': [1, 2]}, {'node_set': 'p1', 'dofs': [2]}]


def local(check):
    from app.design.services.fem.kernel import FEMKernel
    from app.design.services.fem.mesh import FEMMesh
    from app.design.services.fem.constitutive import build_material, rotate_tensor, material_axes
    from app.design.services.fem import thermal as th
    k = FEMKernel()

    print('── 1. Ortótropo con constantes isótropas y ejes girados = isótropo ─────────')
    E, nu = 70e9, 0.33
    G = E / (2 * (1 + nu))
    base = {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 1,
            'mesh_params': {'length': 0.1, 'width': 0.01, 'height': 0.01, 'n_along_length': 10, 'order': 2},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}], 'loads': [{'face_set': 'tip', 'force': [0, -100, 30]}]}
    r_iso = k._solve(None, {**base, 'material': {'type': 'linear_elastic_isotropic', 'E': E, 'nu': nu}}, None)
    r_ort = k._solve(None, {**base, 'material': {'type': 'linear_elastic_orthotropic', 'E1': E, 'E2': E, 'E3': E,
                                                 'G12': G, 'G13': G, 'G23': G, 'nu12': nu, 'nu13': nu, 'nu23': nu,
                                                 'axis_1': [1, 2, 3], 'axis_2': [0, 1, -1]}}, None)
    ui, uo = np.asarray(r_iso['displacement']), np.asarray(r_ort['displacement'])
    d = float(np.abs(ui - uo).max() / np.abs(ui).max())
    check(d < 1e-9, f'desplazamientos idénticos (diferencia relativa {d:.1e})')

    print('── 2. Tracción fuera de eje (CFRP, fibra a θ en el plano xy) ───────────────')
    L, A, F = 0.05, 1e-4, 1000.0
    sigma = F / A
    worst = 0.0
    for deg in (0, 15, 30, 45, 60, 90):
        mat = ortho(**axes_xy(deg))
        m = bar_mesh()
        r = k._solve(None, {'physics': ['structural'], 'tier': 1, 'material': mat, 'bcs': bar_bcs(),
                            'loads': [{'face_set': 'tip', 'force': [F, 0, 0]}]}, None, mesh=m)
        u = np.asarray(r['displacement']).reshape(-1, 3)
        tip = m.node_sets['tip']
        eps_x = float(u[tip, 0].mean() / L)
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
        Ex = 1 / (c ** 4 / CFRP['E1'] + s ** 4 / CFRP['E2'] + (1 / CFRP['G12'] - 2 * CFRP['nu12'] / CFRP['E1']) * s * s * c * c)
        S = np.linalg.inv(build_material(mat).get_D_matrix())
        far = int(np.argmin(np.linalg.norm(m.nodes - [L, 0, 0], axis=1)))
        gxy = float(u[far, 1] / L)                    # u_y = γxy x along y = 0 (u_y(p0) = 0)
        e1 = abs(sigma / eps_x / Ex - 1)
        e2 = abs(gxy - S[3, 0] * sigma) / max(abs(S[0, 0] * sigma), 1e-30)
        worst = max(worst, e1, e2)
        print(f'   θ = {deg:>2}°: σ/εx = {sigma / eps_x / 1e9:7.3f} GPa  (teoría {Ex / 1e9:7.3f})   '
              f'γxy = {gxy:+.4e}  (teoría {S[3, 0] * sigma:+.4e})')
    check(worst < 1e-8, f'módulo aparente y acoplamiento de cortante exactos (error máx {worst:.1e})')

    print('── 3. Voladizo CFRP L/h = 40 vs Timoshenko ────────────────────────────────')
    L, h, P = 0.4, 0.01, 50.0
    I, A = h ** 4 / 12, h * h
    spec = {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 1,
            'mesh_params': {'length': L, 'width': h, 'height': h, 'n_along_length': 40, 'order': 2},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}], 'loads': [{'face_set': 'tip', 'force': [0, -P, 0]}]}
    out = {}
    for name, ax, Eb, Gs in (('fibra a lo largo (eje 1 = x)', axes_xy(0), CFRP['E1'], CFRP['G12']),
                             ('fibra transversal (eje 1 = z)', {'axis_1': [0, 0, 1], 'axis_2': [1, 0, 0]},
                              CFRP['E2'], CFRP['G23'])):
        r = k._solve(None, {**spec, 'material': ortho(**ax)}, None)
        m = r['mesh']
        u = np.asarray(r['displacement']).reshape(-1, 3)
        tip = -float(u[m.node_sets['tip'], 1].mean())
        theo = P * L ** 3 / (3 * Eb * I) + P * L / (5 / 6 * Gs * A)
        out[name] = (tip, theo)
        print(f'   {name}: δ = {tip * 1e3:.4f} mm  Timoshenko {theo * 1e3:.4f} mm  ({100 * (tip / theo - 1):+.2f} %)')
    errs = [abs(t / th_ - 1) for t, th_ in out.values()]
    check(max(errs) < 0.02, f'flecha dentro de ±2 % de Timoshenko (máx {100 * max(errs):.2f} %)')

    print('── 4. Conducción con tensor girado (patch test) ───────────────────────────')
    kmat = {'k': [200.0, 5.0, 1.0], **axes_xy(30)}
    from app.design.services.fem.constitutive import conductivity
    K = conductivity(kmat)
    m = FEMMesh.generate_cantilever(0.02, 0.01, 0.01, 4, order=2)
    g = np.array([1000.0, -400.0, 250.0])
    T_exact = 50 + m.nodes @ g
    Kt = th.assemble_Kt(m, K)
    bnd = np.unique(__import__('app.design.services.fem.tet_batch', fromlist=['x']).boundary_faces(m.elements))
    free = np.setdiff1d(np.arange(m.n_nodes), bnd)
    import scipy.sparse.linalg as sla
    T = T_exact.copy()
    T[free] = sla.spsolve(Kt[free][:, free].tocsc(), -Kt[free][:, bnd] @ T_exact[bnd])
    _, qn = th.heat_flux(m.nodes, m.elements, T, K)
    q_exact = -K @ g
    eT = float(np.abs(T - T_exact).max() / np.abs(T_exact).max())
    eq = float(np.abs(qn - q_exact).max() / np.linalg.norm(q_exact))
    print(f'   q = {qn[0].round(2)} W/m²  exacto {q_exact.round(2)}  (k_xy ≠ 0: {K[0, 1]:.2f} W/m·K)')
    check(eT < 1e-10 and eq < 1e-10, f'T lineal y flujo −K∇T exactos (errores {eT:.1e}, {eq:.1e})')

    print('── 5. Dilatación libre con α ortótropo girado ─────────────────────────────')
    alpha = [-0.5e-6, 30e-6, 30e-6]
    mat = ortho(**axes_xy(30), alpha=alpha, T_ref=20.0, k=1.0)
    m = bar_mesh(order=2)
    dT = 100.0
    r = k._solve(None, {'physics': ['structural', 'thermal'], 'tier': 1, 'material': mat,
                        'bcs': bar_bcs() + [{'face_set': '@all', 'temperature': 20.0 + dT}], 'loads': []}, None, mesh=m)
    u = np.asarray(r['displacement']).reshape(-1, 3)
    A_g = rotate_tensor(alpha, material_axes(mat)) * dT       # expected strain tensor
    # least-squares fit of the (affine) displacement field: u = a + G x
    X = np.hstack([np.ones((m.n_nodes, 1)), m.nodes])
    coef, *_ = np.linalg.lstsq(X, u, rcond=None)
    Gm = coef[1:].T
    eps = 0.5 * (Gm + Gm.T)
    e_eps = float(np.abs(eps - A_g).max() / np.abs(A_g).max())
    resid = float(np.abs(X @ coef - u).max() / np.abs(u).max())
    vm = float(r['summary']['max_von_mises_mpa'])
    ref = CFRP['E1'] * max(abs(a) for a in alpha) * dT / 1e6
    print(f'   εxy esperado {A_g[0, 1]:.3e}, obtenido {eps[0, 1]:.3e};  σvM máx {vm:.2e} MPa (escala EαΔT {ref:.0f} MPa)')
    check(e_eps < 1e-9 and resid < 1e-9 and vm < 1e-6 * ref,
          f'deformación = α_g ΔT y sin tensión (errores {e_eps:.1e}, {resid:.1e}; σvM/escala {vm / ref:.1e})')


def server(check, S):
    import requests
    G, V = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO ortótropo', 'tier': 1, 'description': 'validate_orthotropic.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    try:
        geo = add('GEOMETRY', 'Viga 400×10×10', {'shape': 'beam', 'length_mm': 400, 'width_mm': 10, 'height_mm': 10,
                                                  'n_div': 40, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'CFRP', {'model_type': 'linear_elastic_orthotropic', 'rho': 1600, **CFRP,
                                        'axis_1': [1, 0, 0], 'axis_2': [0, 1, 0]})
        bc = add('BC', 'Empotramiento', {'bc_type': 'fixed'})
        ld = add('LOAD', 'Carga', {'load_type': 'force', 'magnitude': 50, 'unit': 'N', 'dir_x': 0, 'dir_y': -1, 'dir_z': 0})
        for s, t, kind in ((mat, geo, 'CONSTRAINS_MATERIAL'), (bc, geo, 'CONSTRAINS_BC'), (ld, geo, 'APPLIED_TO')):
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': t, 'edge_type': kind})

        def run():
            r = requests.post(f'{V}/{gid}/run', json={})
            rid = r.json().get('run_id')
            t0, st = time.perf_counter(), {}
            while rid and time.perf_counter() - t0 < 300:
                st = requests.get(f'{V}/{rid}/status').json()
                if st.get('status') in ('done', 'failed', 'cancelled'):
                    break
                time.sleep(1)
            return st
        a = run()
        check(a.get('status') == 'done', f"fibra a lo largo: {a.get('status')} {a.get('error') or ''}")
        requests.put(f'{G}/{gid}/nodes/{mat}', json={'properties': {
            'model_type': 'linear_elastic_orthotropic', 'rho': 1600, **CFRP, 'axis_1': [0, 0, 1], 'axis_2': [1, 0, 0]}})
        b = run()
        check(b.get('status') == 'done', f"fibra transversal: {b.get('status')} {b.get('error') or ''}")
        if a.get('status') == b.get('status') == 'done':
            runs = requests.get(f'{V}/runs', params={'graph_id': gid}).json()
            runs = {x['run_id']: x for x in (runs.get('runs') if isinstance(runs, dict) else runs)}
            da = runs[a['run_id']]['max_displacement_mm']
            db = runs[b['run_id']]['max_displacement_mm']
            ratio = db / da
            P, L, h = 50, 0.4, 0.01
            I, A = h ** 4 / 12, h * h
            tA = P * L ** 3 / (3 * CFRP['E1'] * I) + P * L / (5 / 6 * CFRP['G12'] * A)
            tB = P * L ** 3 / (3 * CFRP['E2'] * I) + P * L / (5 / 6 * CFRP['G23'] * A)
            check(abs(ratio / (tB / tA) - 1) < 0.03,
                  f'cociente de flechas {ratio:.2f} (Timoshenko {tB / tA:.2f})')
        rom = requests.post(f'{S}/api/design/rom/{gid}/build', json={})
        check(rom.status_code == 422, f'ROM rechaza el material ortótropo → {rom.status_code}')
        rep = requests.get(f"{V}/{b['run_id']}/report", params={'format': 'markdown'})
        check(rep.ok and 'ortótropo' in rep.text, f'el informe describe el material ortótropo ({rep.status_code}: '
              + next((ln for ln in rep.text.splitlines() if 'Material' in ln), rep.text[:120]) + ')')
    finally:
        requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    ok = True

    def check(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}", flush=True)

    if args.server:
        server(check, args.server.rstrip('/'))
    else:
        import logging
        logging.disable(logging.WARNING)
        local(check)
    print(f"\nHito materiales ortótropos{' vía servidor' if args.server else ''}: {'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
