"""Hito FASE 10.4 — transient Navier–Stokes (BDF2, Taylor–Hood P2-P1) and URANS.

    python validate_ns_transient.py [--server http://127.0.0.1:8080] [--no-cylinder] [--no-step]

Local checks:
 1. Start-up of plane Poiseuille flow (Stokes' first problem in a channel, series solution): temporal order of BDF2
    (2) and implicit Euler (1) against a fine-step reference, error vs the series.
 2. Taylor–Green vortex at Re 100 (exact Navier–Stokes solution, convection balanced by pressure; exact velocity on
    the boundary in time): spatial order ≈ 3 (P2 velocity).
 3. Schäfer & Turek (1996) benchmark 2D-2: laminar vortex shedding behind a cylinder at Re 100 (one element thick
    slab, slip side faces). Reference ranges of the DFG benchmark: c_D,max 3.22–3.24, c_L,max 0.99–1.01,
    St 0.295–0.305. Forces from the consistent reactions on the cylinder. Measured on the default coarse mesh
    (15.8K nodes, Δt 0.01, t = 8 s): c_D,max 3.2456, c_L,max 1.0203, St 0.3065 → checked within 3 % (~43 min;
    at t = 6 s the lift amplitude is still growing, 0.90 of the final one).
 4. Backward-facing step (Driver & Seegmiller), URANS started from the steady pseudo-time iteration (which
    2-cycles, validate_rans.py, x_r/H 5.45): the BDF2 march moves the reattachment to 6.23 within ~40 steps
    (experiment 6.26) and keeps it there (time mean 0.01–0.02 s, 0.02–0.06 s and the instantaneous field at 0.1 s
    agree); a change of ~1e-3 per step remains for good, wandering along the lower wall downstream of the
    reattachment and at the outlet (not shedding: σ(v_x) in the shear layer 0.01 % of U). Strict steady
    convergence is still not reached; the result is the time mean.

``--server``: a study (Gmsh duct, water, transient Navier–Stokes, start-up ramp on the inlet) through the job queue:
series fields in the surface pack, probe curve, wall force history.
"""
import argparse
import sys
import time

import numpy as np

OK = True


def check(cond, msg):
    global OK
    OK &= bool(cond)
    print(f"   {'OK  ' if cond else 'FALLO'}  {msg}")


def info(msg):
    print(f'   info  {msg}')


# ── 1. Start-up Poiseuille ───────────────────────────────────────────────────

def startup(check):
    from app.design.services.fem import ns_transient as nt
    from app.design.services.fem import stokes as st
    from app.design.services.fem.mesh import FEMMesh
    H, MU, RHO, F = 1e-3, 1e-3, 1000.0, 100.0
    m = FEMMesh.generate_cantilever(2e-3, 1e-3, H, 8, order=2)
    walls = [{'face_set': 'z0', 'dofs': [0, 1, 2]}, {'face_set': 'z1', 'dofs': [0, 1, 2]},
             {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'y1', 'dofs': [1]}]
    T = 0.05 * H * H * RHO / MU
    mat = st.FluidMaterial({'mu': MU, 'rho': RHO, 'inertia': True})

    def ux(n, scheme):
        snaps, _ = nt.solve_transient(m, mat, walls, [{'body_force': [F, 0, 0]}],
                                      {'t_end': T, 'n_steps': n, 'scheme': scheme, 'n_output': 1})
        return snaps[-1][1][:, 0]
    ref = ux(640, 'bdf2')
    for scheme, order in (('bdf2', 2.0), ('be', 1.0)):
        e = [np.abs(ux(n, scheme) - ref).max() / ref.max() for n in (10, 20, 40, 80)]
        rates = np.log2(np.array(e[:-1]) / np.array(e[1:]))
        check(np.all(np.abs(rates - order) < 0.1), f'{scheme.upper()}: errores {", ".join(f"{x:.1e}" for x in e)}'
              f' (Δt/2 cada vez), orden {", ".join(f"{r:.2f}" for r in rates)}')
    z = m.nodes[:, 2]
    nu = MU / RHO
    ue = sum(4 * F * H * H / (MU * np.pi ** 3) / k ** 3 * np.sin(k * np.pi * z / H)
             * (1 - np.exp(-(k * np.pi / H) ** 2 * nu * T)) for k in range(1, 400, 2))
    err = np.abs(ux(80, 'bdf2') - ue).max() / ue.max()
    check(err < 0.02, f'perfil vs serie de Stokes a t = 0.05 H²/ν: {100 * err:.2f} % (4 elementos P2 en el hueco)')


# ── 2. Taylor–Green ──────────────────────────────────────────────────────────

def taylor_green(n, n_steps=40):
    from app.design.services.fem import ns_transient as nt
    from app.design.services.fem import stokes as st
    from app.design.services.fem import tet_batch as tb
    from app.design.services.fem.mesh import FEMMesh
    L = np.pi
    xs = np.linspace(0, L, n + 1)
    m = FEMMesh.generate_grid(xs, xs, np.linspace(0, L / n, 2), order=2)
    mu, rho, T = 0.01, 1.0, 2.0
    X = m.nodes
    u0 = np.column_stack([-np.cos(X[:, 0]) * np.sin(X[:, 1]), np.sin(X[:, 0]) * np.cos(X[:, 1]), 0 * X[:, 0]])
    ts = np.linspace(0, T, 4001)
    hist = np.column_stack([ts, np.exp(-2 * mu / rho * ts)]).tolist()
    bnd = np.unique(tb.boundary_faces(m.elements))
    side = bnd[(np.minimum(X[bnd, 0], L - X[bnd, 0]) < 1e-12) | (np.minimum(X[bnd, 1], L - X[bnd, 1]) < 1e-12)]
    bcs = [{'face_set': 'z0', 'dofs': [2]}, {'face_set': 'z1', 'dofs': [2]}]
    for i in side:
        m.node_sets[f'n{i}'] = np.array([i])
        bcs.append({'node_set': f'n{i}', 'dofs': [0, 1], 'values': u0[i, :2].tolist(), 'history': hist})
    mat = st.FluidMaterial({'mu': mu, 'rho': rho, 'inertia': True})
    snaps, _ = nt.solve_transient(m, mat, bcs, [], {'t_end': T, 'n_steps': n_steps, 'n_output': 1}, initial=u0)
    ue = u0 * np.exp(-2 * mu / rho * T)
    return np.abs(snaps[-1][1] - ue).max() / np.abs(ue).max(), m.n_nodes


# ── 3. Cylinder (Schäfer–Turek 2D-2) ─────────────────────────────────────────

def cylinder_mesh(h_cyl=0.008, h_far=0.035, dz=0.02):
    """Channel 2.2 × 0.41 minus the cylinder (0.2, 0.2) r 0.05: Gmsh triangles extruded one layer (each prism → 3
    conforming tets, diagonals from the lowest vertex index) → T10, mid nodes on the cylinder projected on the
    circle. Faces: inlet, outlet, walls, cylinder, z0, z1."""
    import gmsh
    from app.design.services.fem import tet_batch as tb
    from app.design.services.fem.mesh import FEMMesh
    L, H, xc, yc, r = 2.2, 0.41, 0.2, 0.2, 0.05
    gmsh.initialize(['-noenv'])
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setNumber('General.NumThreads', 1)
        gmsh.model.add('cyl')
        rect = gmsh.model.occ.addRectangle(0, 0, 0, L, H)
        disk = gmsh.model.occ.addDisk(xc, yc, 0, r, r)
        gmsh.model.occ.cut([(2, rect)], [(2, disk)])
        gmsh.model.occ.synchronize()
        circ = [c for _, c in gmsh.model.getBoundary(gmsh.model.getEntities(2), oriented=False)
                if np.allclose(gmsh.model.occ.getCenterOfMass(1, c)[:2], [xc, yc], atol=1e-6)]
        f1 = gmsh.model.mesh.field.add('Distance')
        gmsh.model.mesh.field.setNumbers(f1, 'CurvesList', circ)
        f2 = gmsh.model.mesh.field.add('MathEval')
        gmsh.model.mesh.field.setString(f2, 'F', f'min({h_far}, {h_cyl} + 0.25 * F{f1})')
        f3 = gmsh.model.mesh.field.add('Box')                    # wake refinement
        for k, val in (('VIn', 1.6 * h_cyl), ('VOut', h_far), ('XMin', 0.15), ('XMax', 1.2), ('YMin', 0.1),
                       ('YMax', 0.3), ('Thickness', 0.1)):
            gmsh.model.mesh.field.setNumber(f3, k, val)
        f4 = gmsh.model.mesh.field.add('Min')
        gmsh.model.mesh.field.setNumbers(f4, 'FieldsList', [f2, f3])
        gmsh.model.mesh.field.setAsBackgroundMesh(f4)
        for k in ('MeshSizeExtendFromBoundary', 'MeshSizeFromPoints', 'MeshSizeFromCurvature'):
            gmsh.option.setNumber(f'Mesh.{k}', 0)
        gmsh.option.setNumber('Mesh.Algorithm', 6)
        gmsh.model.mesh.generate(2)
        tags, xyz, _ = gmsh.model.mesh.getNodes()
        _, _, tri = gmsh.model.mesh.getElements(2)
    finally:
        gmsh.finalize()
    pos = {int(t): i for i, t in enumerate(tags)}
    P2 = xyz.reshape(-1, 3)[:, :2]
    T = np.vectorize(pos.get)(tri[0].reshape(-1, 3).astype(np.int64))
    n2 = len(P2)
    X = np.vstack([np.column_stack([P2, np.zeros(n2)]), np.column_stack([P2, np.full(n2, dz)])])
    T = np.sort(T, axis=1)                                          # v0 < v1 < v2 (global index)
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    A, B, C = a + n2, b + n2, c + n2
    el = np.vstack([np.column_stack([a, b, c, C]), np.column_stack([a, b, B, C]), np.column_stack([a, A, B, C])])
    pairs = np.sort(el[:, tb.T10_EDGES].reshape(-1, 2), axis=1)
    uniq, inv = np.unique(pairs, axis=0, return_inverse=True)
    mid = 0.5 * (X[uniq[:, 0]] + X[uniq[:, 1]])
    d = lambda Q: np.hypot(Q[:, 0] - xc, Q[:, 1] - yc)              # noqa: E731
    on_c = (np.abs(d(X[uniq[:, 0]]) - r) < 1e-6) & (np.abs(d(X[uniq[:, 1]]) - r) < 1e-6)
    rad = d(mid[on_c])
    mid[on_c, 0] = xc + (mid[on_c, 0] - xc) * r / rad
    mid[on_c, 1] = yc + (mid[on_c, 1] - yc) * r / rad
    X = np.vstack([X, mid])
    el = np.hstack([el, n2 * 2 + inv.reshape(len(el), 6)])
    el = tb.canonicalize(X, el, reorder_mids=False)
    bf = tb.boundary_faces(el)
    Xc = X[bf[:, :3]]
    tol = 1e-9
    faces = {'z0': bf[np.all(np.abs(Xc[:, :, 2]) < tol, axis=1)],
             'z1': bf[np.all(np.abs(Xc[:, :, 2] - dz) < tol, axis=1)],
             'inlet': bf[np.all(np.abs(Xc[:, :, 0]) < tol, axis=1)],
             'outlet': bf[np.all(np.abs(Xc[:, :, 0] - L) < tol, axis=1)],
             'walls': bf[np.all(np.abs(Xc[:, :, 1]) < tol, axis=1) | np.all(np.abs(Xc[:, :, 1] - H) < tol, axis=1)],
             'cylinder': bf[np.all(np.abs(d(Xc.reshape(-1, 3)).reshape(-1, 3) - r) < 1e-6, axis=1)]}
    return FEMMesh(X, el, face_sets=faces, canonical=True), dz


def cylinder(check, t_end=8.0, dt=0.01, h_cyl=0.012, h_far=0.05):
    from app.design.services.fem import ns_transient as nt
    from app.design.services.fem import stokes as st
    m, dz = cylinder_mesh(h_cyl, h_far)
    H, Um, D = 0.41, 1.5, 0.1
    y_in = np.unique(m.face_sets['inlet'])
    bcs = [{'face_set': 'walls', 'dofs': [0, 1, 2], 'label': 'paredes'},
           {'face_set': 'cylinder', 'dofs': [0, 1, 2], 'label': 'cilindro'},
           {'face_set': 'z0', 'dofs': [2]}, {'face_set': 'z1', 'dofs': [2]}]
    for i in y_in:                                                   # parabolic inflow, mean velocity 1
        y = m.nodes[i, 1]
        m.node_sets[f'in{i}'] = np.array([i])
        bcs.append({'node_set': f'in{i}', 'dofs': [0, 1, 2], 'values': [4 * Um * y * (H - y) / H ** 2, 0, 0]})
    mat = st.FluidMaterial({'mu': 1e-3, 'rho': 1.0, 'inertia': True})
    n = int(round(t_end / dt))
    t0 = time.perf_counter()

    def prog(k, total, t):
        if k % 200 == 0:
            info(f'paso {k}/{total} (t = {t:.2f} s, {time.perf_counter() - t0:.0f} s)')
    snaps, inf = nt.solve_transient(m, mat, bcs, [], {'t_end': t_end, 'n_steps': n, 'n_output': 1},
                                    progress=prog)
    info(f'{m.n_nodes} nodos, {inf["n_dof"]} incógnitas, {n} pasos Δt = {dt} s, {inf["factorizations"]} '
         f'factorizaciones LU, {time.perf_counter() - t0:.0f} s, Courant máx. {inf["courant_max"]:.2f}')
    k = [s['label'] for s in inf['forces']['sets']].index('cilindro')
    hist = np.array([[row[0]] + row[1 + k][:2] for row in inf['forces']['history']])
    t, Fd, Fl = hist[:, 0], hist[:, 1], hist[:, 2]
    cd, cl = 2 * Fd / (D * dz), 2 * Fl / (D * dz)                   # ρ Ū² = 1
    last = t > t_end - 2.0
    cl_l = cl[last] - cl[last].mean()
    zc = np.flatnonzero((cl_l[:-1] < 0) & (cl_l[1:] >= 0))
    tz = t[last][zc] - cl_l[zc] * dt / (cl_l[zc + 1] - cl_l[zc])
    St = D / np.mean(np.diff(tz)) if len(tz) > 2 else 0.0
    amp_growth = np.ptp(cl[(t > t_end - 4) & (t < t_end - 3)]) / max(np.ptp(cl[last]), 1e-30)
    info(f'c_L de pico a pico en [t−4, t−3] / último tramo: {amp_growth:.3f} (≈ 1: régimen periódico)')
    # coarse mesh (24 P2 edges on the cylinder, ~16K nodes) and Δt = 0.01: within 3 % of the DFG values
    for name, val, ref, rng in (('c_D máx.', cd[last].max(), 3.23, '3.22–3.24'),
                                ('c_L máx.', cl[last].max(), 1.00, '0.99–1.01'),
                                ('Strouhal', St, 0.300, '0.295–0.305')):
        check(abs(val / ref - 1) < 0.03, f'{name} {val:.4f} (referencia {rng}; {100 * (val / ref - 1):+.1f} %)')


# ── 4. URANS backward step ───────────────────────────────────────────────────

def step_urans(check, fac=0.4, dt=2.5e-4, n_steps=240, inner=8, t_avg=0.02, model='k_epsilon'):
    import validate_rans as V
    from app.design.services.fem import rans
    from app.design.services.fem import stokes as st
    from app.design.services.fem.mesh import FEMMesh
    U, nu, rho = 44.2, 1.5e-5, 1.2
    H, X, el, face_sets, node_sets = V.step_mesh(fac)
    ni = node_sets['inlet']
    yi = X[ni, 1]
    d = np.minimum(yi - H, 9 * H - yi)
    prof = U * np.clip(d / (1.5 * H), 0, 1) ** (1 / 7)
    bcs = [{'dofs': [0, 1, 2], 'values': [0, 0, 0], 'face_set': 'walls'},
           {'dofs': [2], 'values': [0], 'node_set': 'all'}]
    for j, yl in enumerate(np.unique(np.round(yi, 12))):
        sel = np.abs(yi - yl) < 1e-12
        if prof[sel][0] > 0:
            node_sets[f'in{j}'] = ni[sel]
            bcs.append({'dofs': [0, 1, 2], 'values': [float(prof[sel][0]), 0, 0], 'node_set': f'in{j}'})
    mesh = FEMMesh(X, el, node_sets=node_sets, face_sets=face_sets, canonical=True)
    mat = st.FluidMaterial({'mu': rho * nu, 'rho': rho, 'inertia': True})
    turb = rans.TurbulenceSettings({'model': model, 'wall_distance': 0.03 * H, 'inlet_intensity': 0.03,
                                    'inlet_length_scale': 0.5 * H, 'max_iter': 150, 'cfl_max': 1000})
    t0 = time.perf_counter()
    v, p, inf = rans.solve_rans(mesh, mat, np.zeros(3 * mesh.n_nodes), bcs, turb,
                                time={'t_end': dt * n_steps, 'n_steps': n_steps, 'inner_iterations': inner,
                                      'initial': 'steady', 'average_from': t_avg, 'n_output': 2},
                                probes=[{'point': [2 * H, H, 0.5 * H]}])
    T = inf['turbulence']
    tr = T['transient']
    w = T['wall']
    vm = tr['mean']['v']
    xw = mesh.nodes[w['nodes']]
    bot = (np.abs(xw[:, 1]) < 1e-9) & (xw[:, 0] > 0) & (np.abs(xw[:, 2]) < 1e-9)
    o = np.argsort(xw[bot, 0])
    xb, ub = xw[bot, 0][o], vm[w['nodes'][bot], 0][o]
    s = np.flatnonzero((ub[:-1] < 0) & (ub[1:] >= 0))
    xr = [(xb[i] - ub[i] * (xb[i + 1] - xb[i]) / (ub[i + 1] - ub[i])) / H for i in s]
    curve = np.array([[row[0]] + row[1][:2] for row in tr['curves']])
    late = curve[:, 0] > t_avg
    amp = curve[late, 1].std() / U
    sweeps = np.array([s_['sweeps'] for s_ in tr['steps']])
    info(f'{mesh.n_nodes} nodos, {T["transient"]["steady_iterations"]} it. estacionarias + {tr["steps_done"]} pasos '
         f'Δt = {dt} s (U Δt/H = {U * dt / H:.2f}), {time.perf_counter() - t0:.0f} s')
    dv_med = np.median([s_['dv'] for s_ in tr['steps'] if s_['t'] > t_avg])
    info(f'sin convergencia estricta: cambio por paso {dv_med:.1e}'
         f' (mediana); oscilación de v_x en la capa de cortadura (x = 2H, y = H): σ = {100 * amp:.2f} % de U')
    info(f'sub-iteraciones convergidas en el {100 * np.mean(sweeps < inner):.0f} % de los pasos (mediana '
         f'{np.median(sweeps):.0f} por paso)')
    ui = v[w['nodes'][bot], 0][o]
    si = np.flatnonzero((ui[:-1] < 0) & (ui[1:] >= 0))
    xi = [(xb[i] - ui[i] * (xb[i + 1] - xb[i]) / (ui[i + 1] - ui[i])) / H for i in si]
    check(len(xr) == 1 and 5.0 < xr[0] < 6.6, f'reincorporación del campo medio ({tr["mean"]["t0"]:.3f}–'
          f'{tr["mean"]["t1"]:.3f} s, {tr["mean"]["n_steps"]} pasos): x_r/H = {", ".join(f"{x:.2f}" for x in xr)} '
          '(experimento 6.26; iteración estacionaria 5.45)')
    check(len(xi) == 1 and len(xr) == 1 and abs(xi[0] - xr[0]) < 0.05,
          f'estable: campo instantáneo final x_r/H = {", ".join(f"{x:.2f}" for x in xi)}')


def local(check, no_cyl, no_step):
    print('── 1. Arranque del flujo de Poiseuille (orden temporal) ────────────────')
    startup(check)
    print('── 2. Vórtice de Taylor–Green, Re 100 (orden espacial) ─────────────────')
    e8, _ = taylor_green(8)
    e16, n16 = taylor_green(16)
    rate = np.log2(e8 / e16)
    check(e16 < 0.01 and 2.6 < rate < 3.4, f'error 8×8: {100 * e8:.2f} %, 16×16: {100 * e16:.3f} % '
          f'({n16} nodos), orden {rate:.2f} (P2: 3)')
    if not no_cyl:
        print('── 3. Cilindro Schäfer–Turek 2D-2, Re 100 (desprendimiento de vórtices) ──')
        cylinder(check)
    if not no_step:
        print('── 4. Escalón descendente, URANS desde el estacionario (campo medio) ───')
        step_urans(check)


def server(check, S):
    import json
    import struct
    import requests
    print('── Servidor: estudio Navier-Stokes transitorio por la cola de trabajos ──')
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO NS transitorio', 'tier': 1,
                                       'description': 'validate_ns_transient.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    try:
        geo = add('GEOMETRY', 'Conducto 40×10×10', {'shape': 'beam', 'length_mm': 40, 'width_mm': 10,
                                                    'height_mm': 10, 'n_div': 8, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'Agua', {'model_type': 'newtonian_fluid', 'mu': 1e-3, 'rho': 1000,
                                       'flow_model': 'navier_stokes', 'transient': True, 't_end': 2,
                                       'time_unit': 's', 'time_steps': 40, 'n_output': 5,
                                       'probes': [{'label': 'centro', 'x': 30, 'y': 5, 'z': 5}]})
        bcs = [add('BC', f'Pared {f}', {'bc_type': 'fixed', 'face_set': f}) for f in ('y0', 'y1', 'z0', 'z1')]
        bcs.append(add('BC', 'Entrada', {'bc_type': 'velocity', 'vx': 10, 'vy': 0, 'vz': 0, 'unit': 'mm/s',
                                         'face_set': 'fixed', 't_ramp': 0.5}))
        for b in bcs:
            requests.post(f'{G}/{gid}/edges', json={'source_id': b, 'target_id': geo, 'edge_type': 'CONSTRAINS_BC'})
        requests.post(f'{G}/{gid}/edges', json={'source_id': mat, 'target_id': geo, 'edge_type': 'CONSTRAINS_MATERIAL'})
        r = requests.post(f'{Vs}/{gid}/run', json={})
        rid = r.json().get('run_id')
        t0, st = time.perf_counter(), {}
        while rid and time.perf_counter() - t0 < 900:
            st = requests.get(f'{Vs}/{rid}/status').json()
            if st.get('status') in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(st.get('status') == 'done',
              f"run: {st.get('status')} {st.get('error') or ''} {r.text[:300] if not rid else ''}")
        if st.get('status') != 'done':
            return

        def pack(step=None):
            surf = requests.get(f'{Vs}/{rid}/surface', params={} if step is None else {'step': step})
            hl = struct.unpack('<I', surf.content[:4])[0]
            return surf.status_code, json.loads(surf.content[4:4 + hl])
        code, hdr = pack()
        fl = hdr['summary']['fluid']
        tr = fl.get('transient') or {}
        check(len(tr.get('times') or []) == 6 and abs(tr['times'][-1] - 2.0) < 1e-12,
              f"instantes guardados {[round(t, 3) for t in tr.get('times') or []]}")
        check(hdr.get('times') and len(hdr['times']) == 6, f"paquete con serie temporal (step {hdr.get('step')})")
        pc = (tr.get('probes') or [{}])[0].get('curve') or []
        ux = [row[1] for row in pc]
        check(len(ux) == 41 and ux[0] == 0.0 and ux[-1] > 0.015 and np.all(np.diff(ux[1:]) >= -1e-12),
              f'sonda centro: v_x de {ux[0] if ux else 0:.2e} a {ux[-1] if ux else 0:.2e} m/s (rampa 0.5 s; '
              'pico del conducto ≈ 2.1 U)')
        q = next(f['flow_m3_s'] for f in fl['flow_rates'] if f['face_set'] == 'fixed')
        check(abs(-q / 1e-6 - 1) < 1e-6 and fl['mass_balance_error'] < 1e-8,
              f"caudal de entrada {-q:.6e} m³/s (U·A = 1e-6), balance de masa {fl['mass_balance_error']:.1e}")
        fw = [f for f in tr.get('forces') or [] if f['label'].startswith('Pared')]
        check(len(fw) == 4 and all(f['final_N'][0] > 0 for f in fw),
              f"fuerzas de las 4 paredes en el tiempo (arrastre total {sum(f['final_N'][0] for f in fw):.2e} N)")
        code2, hdr2 = pack(2)
        check(code2 == 200 and hdr2.get('step') == 2, f'paquete de superficie del instante 2 ({code2})')
    finally:
        requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    t0 = time.perf_counter()
    if args.server:
        server(check, args.server)
    else:
        local(check, args.no_cylinder, args.no_step)
    print(f'\nHito Navier-Stokes transitorio{" vía servidor" if args.server else ""}: '
          f'{"CUMPLIDO" if OK else "NO CUMPLIDO"} ({time.perf_counter() - t0:.0f} s)')
    sys.exit(0 if OK else 1)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--no-cylinder', action='store_true')
    ap.add_argument('--no-step', action='store_true')
    args = ap.parse_args()
    main()
