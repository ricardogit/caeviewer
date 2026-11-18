"""Hito: turbulent flow with RANS k-ε / k-ω SST and wall functions (FASE 10.4, `fem/rans.py`).

  1. fully developed channel, Re_τ = 2000 (body-force driven, one column of T10, symmetry at the centre): global
     equilibrium wall shear + convective outflow = body force, u_τ, mean profile vs Reichardt's law of the wall,
     wall k⁺ = 1/√C_μ, skin friction vs Dean's correlation c_f = 0.073 Re_b^-¼
  2. wall-distance independence: bulk velocity U_b⁺ for δ⁺ = 30 … 200 (the wall law takes over below the mesh)
  3. backward-facing step (Driver & Seegmiller 1985, expansion 9/8, Re_H 37 500), informative: reattachment length
     x_r/H. The experiment gives 6.26 ± 0.10; standard k-ε with wall functions underpredicts it (≈ 5–5.5, e.g.
     Thangam & Speziale 1992): the check is the k-ε band. The segregated steady solver does not converge strictly
     here (a 2-cycle on the step face leaves the residual at 1e-4…1e-3 on this mesh, 0.2 on finer ones) while x_r/H
     stays at 5.44–5.45 on both: reported, not required. ~8 min.
  4. k-ω SST channel (same checks + ω = u_τ/(√β* κ_ω y) in the log layer; c_f −1.4 % vs Dean) and δ⁺ 30–200.
  5. k-ω SST backward step (0.4 mesh): converges strictly (181 it, the CFL cap drops to 8 automatically);
     x_r/H 7.50 here, 6.93 on the 0.6 mesh (9.4K nodes: the steady iteration does not converge there, value from
     URANS, mean = final field) — SST + wall functions overpredicts on coarse meshes and converges towards the
     experiment with refinement: band 6.3–8.0 on this mesh. ~6 min.
  Server: Gmsh-free parametric duct with both models through the queue.

Usage: python validate_rans.py [--server http://127.0.0.1:8080] [--no-step] [--sst-only]
"""
import argparse
import sys
import time

import numpy as np

STEP_EXP = 6.26
STEP_SST = (6.3, 8.0)        # SST band on the 0.4 mesh (see docstring)


def channel(Re_tau=2000.0, dplus=50.0, ny=16, model='k_epsilon'):
    from app.design.services.fem import rans
    from app.design.services.fem import stokes as st
    from app.design.services.fem.assembler import assemble_F
    from app.design.services.fem.mesh import FEMMesh
    h, rho, ut = 1.0, 1.0, 1.0
    nu = ut * h / Re_tau
    delta = dplus * nu / ut
    w = 1.15 ** np.arange(ny)
    ys = delta + (h - delta) * np.concatenate([[0], np.cumsum(w) / w.sum()])
    mesh = FEMMesh.generate_grid([0, 0.05], ys, [0, 0.05], order=2)
    f = rho * ut ** 2 / (h - delta)
    mat = st.FluidMaterial({'mu': rho * nu, 'rho': rho, 'inertia': True, 'turbulence': {'model': model}})
    F = assemble_F(mesh, [{'body_force': [f, 0, 0]}], [])
    bcs = [{'dofs': [0, 1, 2], 'values': [0, 0, 0], 'face_set': 'y0'},
           {'dofs': [1], 'values': [0], 'face_set': 'y1'},
           {'dofs': [1, 2], 'values': [0, 0], 'face_set': 'x0'},
           {'dofs': [1, 2], 'values': [0, 0], 'face_set': 'x1'},
           {'dofs': [2], 'values': [0], 'face_set': 'z0'},
           {'dofs': [2], 'values': [0], 'face_set': 'z1'}]
    v, p, info = rans.solve_rans(mesh, mat, F, bcs, rans.TurbulenceSettings({'model': model, 'wall_distance': delta}),
                                 body=[f, 0, 0])
    return mesh, v, info, nu, delta, f


def bulk(mesh, v, nu, delta):
    """U_b⁺ over the half channel: mesh profile + Reichardt inside the wall distance."""
    from scipy.integrate import quad
    from app.design.services.fem import rans
    y = mesh.nodes[:, 1]
    yy, ii = np.unique(np.round(y, 12), return_index=True)
    uu = v[ii, 0]
    return np.trapz(uu, yy) + quad(lambda s: rans.reichardt(s / nu), 0, delta)[0]


def step_mesh(fac):
    """2-D (one element thick) backward-facing step, H = 12.7 mm: inlet at −4H, outlet at 30H, channel 8H → 9H."""
    from app.design.services.fem import tet_batch as tb
    from app.design.services.fem.mesh import FEMMesh
    H = 0.0127

    def graded(a, b, n, r, both=False):
        if both:
            w = r ** np.arange(n // 2)
            w = np.concatenate([w, w[::-1]])
        else:
            w = r ** np.arange(n)
        return a + (b - a) * np.concatenate([[0], np.cumsum(w) / w.sum()])

    nx1, nx2, ny1, ny2 = (int(round(fac * k)) for k in (10, 50, 10, 28))
    xs = np.concatenate([graded(-4 * H, 0, nx1, 1 / 1.15)[:-1], graded(0, 30 * H, nx2, 1.07)])
    ys = np.concatenate([graded(0, H, ny1, 1.25, both=True)[:-1], graded(H, 9 * H, ny2, 1.2, both=True)])
    g = FEMMesh.generate_grid(xs, ys, [0, H], order=2)
    el = g.elements
    c = g.nodes[el[:, :4]].mean(1)
    el = el[~((c[:, 0] < 0) & (c[:, 1] < H))]
    used = np.unique(el)
    remap = -np.ones(len(g.nodes), int)
    remap[used] = np.arange(len(used))
    X, el = g.nodes[used], remap[el]
    bf = tb.boundary_faces(el)
    Xc = X[bf[:, :3]]
    tol = 1e-6 * H

    def on(ax, val):
        return np.all(np.abs(Xc[:, :, ax] - val) < tol, axis=1)

    walls = (on(1, 9 * H) | (on(1, 0) & (Xc[:, :, 0].min(1) >= -tol))
             | (on(0, 0) & (Xc[:, :, 1].max(1) <= H + tol)) | (on(1, H) & (Xc[:, :, 0].max(1) <= tol)))
    face_sets = {'inlet': bf[on(0, -4 * H)], 'outlet': bf[on(0, 30 * H)], 'walls': bf[walls]}
    node_sets = {k: np.unique(v) for k, v in face_sets.items()}
    node_sets['all'] = np.arange(len(X))
    return H, X, el, face_sets, node_sets


def backward_step(fac, max_iter=300, model='k_epsilon', cfl_max=1000.0):
    from app.design.services.fem import rans
    from app.design.services.fem import stokes as st
    from app.design.services.fem.mesh import FEMMesh
    U, nu, rho = 44.2, 1.5e-5, 1.2
    H, X, el, face_sets, node_sets = step_mesh(fac)
    ni = node_sets['inlet']
    yi = X[ni, 1]
    d = np.minimum(yi - H, 9 * H - yi)
    prof = U * np.clip(d / (1.5 * H), 0, 1) ** (1 / 7)        # 1/7 boundary layers, δ99 = 1.5H (the experiment's)
    bcs = [{'dofs': [0, 1, 2], 'values': [0, 0, 0], 'face_set': 'walls'},
           {'dofs': [2], 'values': [0], 'node_set': 'all'}]      # 2-D: v_z = 0
    for j, yl in enumerate(np.unique(np.round(yi, 12))):
        sel = np.abs(yi - yl) < 1e-12
        if prof[sel][0] > 0:
            node_sets[f'in{j}'] = ni[sel]
            bcs.append({'dofs': [0, 1, 2], 'values': [float(prof[sel][0]), 0, 0], 'node_set': f'in{j}'})
    mesh = FEMMesh(X, el, node_sets=node_sets, face_sets=face_sets, canonical=True)
    mat = st.FluidMaterial({'mu': rho * nu, 'rho': rho, 'inertia': True})
    turb = rans.TurbulenceSettings({'model': model, 'wall_distance': 0.03 * H, 'inlet_intensity': 0.03,
                                    'inlet_length_scale': 0.5 * H,
                                    'max_iter': max_iter, 'cfl_max': cfl_max})
    v, p, info = rans.solve_rans(mesh, mat, np.zeros(3 * mesh.n_nodes), bcs, turb)
    T = info['turbulence']
    w = T['wall']
    xw = mesh.nodes[w['nodes']]
    bot = (np.abs(xw[:, 1]) < 1e-9) & (xw[:, 0] > 0) & (np.abs(xw[:, 2]) < 1e-9)
    order = np.argsort(xw[bot, 0])
    xb, ub = xw[bot, 0][order], v[w['nodes'][bot], 0][order]
    s = np.flatnonzero((ub[:-1] < 0) & (ub[1:] >= 0))
    xr = [(xb[i] - ub[i] * (xb[i + 1] - xb[i]) / (ub[i + 1] - ub[i])) / H for i in s]
    return mesh, T, xr, w['y_plus'][bot]


def local(check, no_step):
    from app.design.services.fem import rans
    from app.design.services.fem import stokes as st

    print('── 1. Canal turbulento desarrollado, Re_τ 2000 ─────────────────────────')
    t0 = time.perf_counter()
    mesh, v, info, nu, delta, f = channel()
    T = info['turbulence']
    check(T['converged'], f"convergido en {T['iterations']} iteraciones ({time.perf_counter() - t0:.1f} s)")
    area = 0.05 * 0.05
    C, _ = st.convection(mesh, v, newton=False)
    conv = (C @ v.ravel())[0::3].sum()
    eq = (T['wall_force'][0] + conv) / (f * (1 - delta) * area) - 1
    check(abs(eq) < 1e-5, f'equilibrio: cortante de pared + flujo convectivo = fuerza de volumen ({eq:.1e})')
    ut_err = np.abs(np.asarray(T['wall']['u_tau']) - 1).max()
    check(ut_err < 2e-3, f'u_τ = 1 en todos los nodos de pared (máx. desviación {ut_err:.1e})')
    y = mesh.nodes[:, 1]
    sel = (y / nu > 50) & (y / nu < 400)
    perr = np.abs(v[sel, 0] / rans.reichardt(y[sel] / nu) - 1).max()
    check(perr < 0.015, f'perfil vs Reichardt en 50 < y⁺ < 400: {100 * perr:.2f} %')
    kw = T['k'][T['wall']['nodes']].mean() * np.sqrt(rans.CMU)
    check(abs(kw - 1) < 2e-3, f'k⁺ en la pared = 1/√C_μ ({kw - 1:+.1e})')
    Ub = bulk(mesh, v, nu, delta)
    Reb = 2 * Ub / nu
    cf_err = 2 / Ub ** 2 / (0.073 * Reb ** -0.25) - 1
    check(abs(cf_err) < 0.05, f'U_b⁺ = {Ub:.2f}, Re_b = {Reb:.0f}, c_f vs Dean {100 * cf_err:+.1f} %')

    print('── 2. Independencia de la distancia de pared δ⁺ ────────────────────────')
    ubs, conv = {}, []
    for dp in (30.0, 100.0, 200.0):
        m2, v2, i2, nu2, d2, _ = channel(dplus=dp)
        ubs[dp] = bulk(m2, v2, nu2, d2)
        conv.append(i2['turbulence']['converged'])
    ubs[50.0] = Ub
    check(all(conv), f'convergido con δ⁺ 30, 100, 200: {conv}')
    spread = (max(ubs.values()) - min(ubs.values())) / Ub
    check(spread < 0.02, 'U_b⁺ ' + ', '.join(f'δ⁺ {k:.0f}: {ubs[k]:.2f}' for k in sorted(ubs))
          + f' (dispersión {100 * spread:.1f} %)')

    if no_step:
        return
    print('── 3. Escalón descendente (Driver & Seegmiller), informativo ───────────')
    t0 = time.perf_counter()
    mesh, T, xr, yp = backward_step(0.4)
    res = T['history'][-1]['residual']
    print(f"   info  {mesh.n_nodes} nodos, {T['iterations']} it ({time.perf_counter() - t0:.0f} s), residuo final "
          f"{res:.1e}{'' if T['converged'] else ' (sin convergencia estricta, ver docstring)'}")
    xr_main = xr[-1] if xr else float('nan')
    check(res < 1e-2, f'residuo estacionado por debajo de 1e-2 ({res:.1e})')
    check(len(xr) >= 1 and 4.6 < xr_main < 6.0,
          f'reincorporación x_r/H = {xr_main:.2f} (experimento {STEP_EXP}; k-ε estándar ≈ 5–5.5)')
    check(10 < np.median(yp) < 100, f'y⁺ en la pared inferior: mediana {np.median(yp):.0f}, máx. {yp.max():.0f}')


def local_sst(check, no_step):
    from app.design.services.fem import rans

    print('── 4. Canal turbulento Re_τ 2000, k-ω SST ──────────────────────────────')
    t0 = time.perf_counter()
    mesh, v, info, nu, delta, f = channel(model='k_omega_sst')
    T = info['turbulence']
    check(T['converged'], f"convergido en {T['iterations']} iteraciones ({time.perf_counter() - t0:.1f} s)")
    ut_err = np.abs(np.asarray(T['wall']['u_tau']) - 1).max()
    check(ut_err < 3e-3, f'u_τ = 1 en todos los nodos de pared (máx. desviación {ut_err:.1e})')
    y = mesh.nodes[:, 1]
    sel = (y / nu > 50) & (y / nu < 400)
    perr = np.abs(v[sel, 0] / rans.reichardt(y[sel] / nu) - 1).max()
    check(perr < 0.015, f'perfil vs Reichardt en 50 < y⁺ < 400: {100 * perr:.2f} %')
    kw = T['k'][T['wall']['nodes']].mean() * np.sqrt(rans.CMU)
    check(abs(kw - 1) < 5e-3, f'k⁺ en la pared = 1/√β* ({kw - 1:+.1e})')
    werr = np.abs(T['omega'][sel] * np.sqrt(rans.CMU) * rans.KAPPA_W * y[sel] - 1).max()
    check(werr < 0.05, f'ω = u_τ/(√β* κ_ω y) en la capa logarítmica (κ_ω = {rans.KAPPA_W:.3f}): {100 * werr:.1f} %')
    Ub = bulk(mesh, v, nu, delta)
    Reb = 2 * Ub / nu
    cf_err = 2 / Ub ** 2 / (0.073 * Reb ** -0.25) - 1
    check(abs(cf_err) < 0.02, f'U_b⁺ = {Ub:.2f}, c_f vs Dean {100 * cf_err:+.1f} % (k-ε: −3.3 %)')
    ubs, conv = {50.0: Ub}, []
    for dp in (30.0, 100.0, 200.0):
        m2, v2, i2, nu2, d2, _ = channel(dplus=dp, model='k_omega_sst')
        ubs[dp] = bulk(m2, v2, nu2, d2)
        conv.append(i2['turbulence']['converged'])
    spread = (max(ubs.values()) - min(ubs.values())) / Ub
    check(all(conv) and spread < 0.02, f'δ⁺ 30–200 convergidos {conv}; U_b⁺ '
          + ', '.join(f'{ubs[k]:.2f}' for k in sorted(ubs)) + f' (dispersión {100 * spread:.1f} %)')

    if no_step:
        return
    print('── 5. Escalón descendente, k-ω SST ─────────────────────────────────────')
    t0 = time.perf_counter()
    mesh, T, xr, yp = backward_step(0.4, 400, 'k_omega_sst')
    res = T['history'][-1]['residual']
    cfl = T['history'][-1]['cfl']
    check(T['converged'], f"convergencia estricta en {T['iterations']} it (residuo {res:.1e}; tope de CFL reducido "
          f"automáticamente a {cfl:.3g}; {mesh.n_nodes} nodos, {time.perf_counter() - t0:.0f} s)")
    xr_main = xr[-1] if xr else float('nan')
    check(STEP_SST[0] < xr_main < STEP_SST[1], f'reincorporación x_r/H = {xr_main:.2f} (experimento {STEP_EXP}; '
          'esta malla gruesa sobrestima, ver docstring)' + (f'; burbuja de esquina {xr[0]:.2f}' if len(xr) > 1
                                                            else ''))


def server(check, S):
    for fm in ('rans_k_epsilon', 'rans_k_omega_sst'):
        print(f'── Servidor: conducto 100×20×20 mm, agua 1 m/s, {fm} ──')
        server_duct(check, S, fm)


def server_duct(check, S, flow_model):
    import json
    import struct
    import requests
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO RANS', 'tier': 1, 'description': 'validate_rans.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    try:
        geo = add('GEOMETRY', 'Conducto 100×20×20', {'shape': 'beam', 'length_mm': 100, 'width_mm': 20,
                                                     'height_mm': 20, 'n_div': 20, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'Agua', {'model_type': 'newtonian_fluid', 'mu': 1.002e-3, 'rho': 998,
                                       'flow_model': flow_model, 'inlet_intensity': 5})
        bcs = [add('BC', f'Pared {f}', {'bc_type': 'fixed', 'face_set': f}) for f in ('y0', 'y1', 'z0', 'z1')]
        bcs.append(add('BC', 'Entrada', {'bc_type': 'velocity', 'vx': 1.0, 'vy': 0, 'vz': 0, 'unit': 'm/s',
                                         'face_set': 'fixed', 'turbulence_intensity': 4}))
        for b in bcs:
            requests.post(f'{G}/{gid}/edges', json={'source_id': b, 'target_id': geo, 'edge_type': 'CONSTRAINS_BC'})
        requests.post(f'{G}/{gid}/edges', json={'source_id': mat, 'target_id': geo, 'edge_type': 'CONSTRAINS_MATERIAL'})
        r = requests.post(f'{Vs}/{gid}/run', json={})
        rid = r.json().get('run_id')
        t0, st = time.perf_counter(), {}
        while rid and time.perf_counter() - t0 < 600:
            st = requests.get(f'{Vs}/{rid}/status').json()
            if st.get('status') in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(st.get('status') == 'done',
              f"run: {st.get('status')} {st.get('error') or ''} {r.text[:300] if not rid else ''}")
        if st.get('status') == 'done':
            surf = requests.get(f'{Vs}/{rid}/surface')
            hl = struct.unpack('<I', surf.content[:4])[0]
            hdr = json.loads(surf.content[4:4 + hl])
            ex = {x['key'] for x in hdr.get('extra_fields', [])}
            need = {'vmag', 'p', 'k', 'eps', 'nut_ratio'} | ({'omega'} if flow_model == 'rans_k_omega_sst' else set())
            check(need <= ex, f'campos extra {sorted(ex)}')
            fl = hdr['summary']['fluid']
            tu = fl.get('turbulence') or {}
            check(fl.get('model') == flow_model and tu.get('converged'),
                  f"modelo {fl.get('model')}, convergido {tu.get('converged')} en {tu.get('iterations')} it")
            q = next(f['flow_m3_s'] for f in fl['flow_rates'] if f['face_set'] == 'fixed')
            check(abs(-q / 4e-4 - 1) < 1e-6 and fl['mass_balance_error'] < 1e-8,
                  f"caudal de entrada {-q:.6e} m³/s (U·A = 4e-4), balance de masa {fl['mass_balance_error']:.1e}")
            check(tu.get('y_plus_mean', 0) > 0 and tu.get('nut_ratio_max', 0) > 1,
                  f"y⁺ medio {tu.get('y_plus_mean', 0):.0f}, ν_t/ν máx. {tu.get('nut_ratio_max', 0):.0f}")
    finally:
        requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    ap.add_argument('--no-step', action='store_true', help='skip the backward-facing steps (~15 min)')
    ap.add_argument('--sst-only', action='store_true', help='only the k-ω SST sections')
    args = ap.parse_args()
    fails = []

    def check(cond, msg):
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}")
        if not cond:
            fails.append(msg)

    if args.server:
        server(check, args.server.rstrip('/'))
        label = 'Hito RANS vía servidor'
    else:
        if not args.sst_only:
            local(check, args.no_step)
        local_sst(check, args.no_step)
        label = 'Hito RANS k-ε / k-ω SST'
    print(f"\n{label}: {'CUMPLIDO' if not fails else 'NO CUMPLIDO'}")
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
