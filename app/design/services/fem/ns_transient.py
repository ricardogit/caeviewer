"""Transient incompressible Navier–Stokes (FASE 10.4): laminar flow in time on Taylor–Hood P2-P1 (T10).

    ρ ∂v/∂t + ρ(v·∇)v − μ∇²v + ∇p = f(t),   ∇·v = 0

Time discretisation: BDF2 with a backward-Euler first step (or BE throughout), fixed Δt. The convection is
linearised about the extrapolated velocity v* = 2vⁿ − vⁿ⁻¹ (vⁿ in the BE step): one linear saddle-point solve per
step and second order in time (semi-implicit BDF2). ``iterations`` > 1 adds Picard sweeps with v* = latest iterate
(the fully implicit scheme when they converge). Consistent P2 mass; the same μ-normalised operators as ``stokes``.

Boundary conditions as in ``stokes`` (``dofs``/``values`` velocities, ``pressure`` / ``body_force`` / ``gravity``
loads), each optionally scaled in time by ``history`` [[t, factor], …] (linear interpolation, constant outside).
Initial state: rest, a uniform velocity (3,), a nodal field (N, 3), or ``'steady'`` (the steady Navier–Stokes
solution with the t = 0 data). Linear solves: GMRES preconditioned with the LU of an earlier step (refactorised
when it needs more than ``REUSE_MAX_IT`` iterations).

Outputs: snapshots (t, v, p) at ``n_output`` evenly spaced steps, probe curves (v, p at points, every step), the
force of the fluid on every BC face set with all three velocity components prescribed (walls, bodies: drag / lift
history from the consistent reactions, which include the inertial part), kinetic energy and the Courant number.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

from app.design.services.fem import stokes as st
from app.design.services.fem import tet_batch as tb
from app.design.services.fem.assembler import assemble_F, dirichlet, _face_tris

SCHEMES = ('bdf2', 'be')
REUSE_MAX_IT = 25          # GMRES iterations with the previous step's LU before refactorising


class _Solver:
    """Free-DOF saddle solves of a slowly changing matrix: GMRES preconditioned with the LU of an earlier step,
    refactorised when it takes more than ``REUSE_MAX_IT`` iterations (the convection changes a little per step)."""

    def __init__(self):
        self.lu, self.n_lu, self.n_gmres = None, 0, 0

    def solve(self, K, rhs):
        from scipy.sparse.linalg import LinearOperator, gmres
        if self.lu is not None:
            P = LinearOperator(K.shape, matvec=self.lu.solve, dtype=float)
            its = [0]

            def cb(_):
                its[0] += 1
            tol = 1e-11
            try:
                x, info = gmres(K, rhs, M=P, rtol=tol, atol=0.0, restart=REUSE_MAX_IT, maxiter=1, callback=cb,
                                callback_type='pr_norm')
            except TypeError:                                   # SciPy < 1.12
                x, info = gmres(K, rhs, M=P, tol=tol, atol=0.0, restart=REUSE_MAX_IT, maxiter=1, callback=cb,
                                callback_type='pr_norm')
            if info == 0 and np.all(np.isfinite(x)):
                self.n_gmres += 1
                return x
        self.lu = splu(K.tocsc())
        self.n_lu += 1
        return self.lu.solve(rhs)


class TimeSettings:
    def __init__(self, spec: dict):
        if not spec:
            raise ValueError('Fluido transitorio: falta la definición temporal (t_end, n_steps).')
        self.t_end = float(spec.get('t_end') or 0.0)
        if not self.t_end > 0:
            raise ValueError('Fluido transitorio: t_end debe ser > 0 s.')
        if spec.get('dt'):
            self.n_steps = max(1, int(round(self.t_end / float(spec['dt']))))
        else:
            self.n_steps = int(spec.get('n_steps') or 0)
        if self.n_steps < 1:
            raise ValueError('Fluido transitorio: hace falta n_steps ≥ 1 (o dt).')
        self.dt = self.t_end / self.n_steps
        self.scheme = (spec.get('scheme') or 'bdf2').lower()
        if self.scheme not in SCHEMES:
            raise ValueError(f'Fluido transitorio: esquema {self.scheme!r} desconocido (bdf2, be).')
        self.n_output = max(1, min(int(spec.get('n_output') or 50), self.n_steps))
        self.iterations = max(1, int(spec.get('iterations') or 1))
        self.tol = float(spec.get('tol') or 1e-8)

    def to_dict(self):
        return {'t_end': self.t_end, 'n_steps': self.n_steps, 'dt': self.dt, 'scheme': self.scheme,
                'n_output': self.n_output, 'iterations': self.iterations}


def output_steps(n_steps: int, n_output: int) -> set:
    """Steps (1..n_steps) stored as snapshots: evenly spaced, the last one always (step 0 = initial state)."""
    return {int(round(i * n_steps / n_output)) for i in range(1, n_output + 1)}


def _series(hist):
    """[[t, factor], …] → (t, f) arrays (checked once), None without a history."""
    if not hist:
        return None
    h = np.asarray(hist, float)
    if h.ndim != 2 or h.shape[1] != 2 or np.any(np.diff(h[:, 0]) < 0):
        raise ValueError('Serie temporal: [[t, factor], …] con t creciente.')
    return h[:, 0].copy(), h[:, 1].copy()


def _factor(h, t):
    return 1.0 if h is None else float(np.interp(t, h[0], h[1]))


class _Bcs:
    """Dirichlet data at time t (later entries win, each scaled by its own ``history``)."""

    def __init__(self, mesh, bcs):
        self.parts = []
        for bc in bcs:
            d, v = dirichlet(mesh, [bc])
            self.parts.append((d, v, _series(bc.get('history'))))
        alld = np.concatenate([p[0] for p in self.parts]) if self.parts else np.zeros(0, np.int64)
        # owner of each dof = the last entry that prescribes it
        self.dofs, last = np.unique(alld[::-1], return_index=True)
        self.src = len(alld) - 1 - last                       # index into the concatenation
        self.timed = any(p[2] is not None for p in self.parts)

    def values(self, t):
        vals = np.concatenate([v * _factor(h, t) for _, v, h in self.parts]) if self.parts else np.zeros(0)
        return vals[self.src]


class _Loads:
    """F(t) = Σ F_i · history_i(t)."""

    def __init__(self, mesh, loads):
        self.info: list = []
        steady = [ld for ld in loads if not ld.get('history')]
        self.F0 = assemble_F(mesh, steady, self.info) if steady else np.zeros(mesh.n_dof_structural)
        self.timed = [(assemble_F(mesh, [ld], self.info), _series(ld['history'])) for ld in loads
                      if ld.get('history')]

    def at(self, t):
        F = self.F0.copy()
        for Fi, h in self.timed:
            F += Fi * _factor(h, t)
        return F


def nodal_pressure(mesh, pc, corners, pidx):
    p = np.zeros(mesh.n_nodes)
    p[corners] = pc
    el = mesh.elements
    for k, (i, j) in enumerate(tb.T10_EDGES):
        p[el[:, 4 + k]] = 0.5 * (pc[pidx[el[:, i]]] + pc[pidx[el[:, j]]])
    return p


def force_sets(mesh, bcs):
    """Face sets of BCs prescribing all three velocity components (walls, bodies, inlets): label → node ids."""
    out = []
    for bc in bcs:
        d = sorted({int(x) for x in bc.get('dofs', [0, 1, 2])})
        if d != [0, 1, 2] or 'face_set' not in bc:
            continue
        fs = bc['face_set']
        nodes = np.unique(_face_tris(mesh, fs))
        name = bc.get('label') or (fs if isinstance(fs, str) else f'{len(fs)} caras')
        out.append((name, fs if isinstance(fs, str) else f'{len(fs)} caras', nodes))
    return out


def element_size(mesh):
    """Equal-volume regular-tet edge per element (for the Courant number)."""
    X = mesh.nodes[mesh.elements[:, :4]]
    V = np.abs(np.einsum('ij,ij->i', X[:, 1] - X[:, 0], np.cross(X[:, 2] - X[:, 0], X[:, 3] - X[:, 0]))) / 6
    return np.cbrt(6.0 * np.sqrt(2.0) * V)


def solve_transient(mesh, mat: st.FluidMaterial, bcs: list, loads: list, time: dict, *, initial=None,
                    probes: list | None = None, progress=None):
    """Returns (snaps [(t, v (N,3), p (N,))], info)."""
    from app.design.services.fem.rans import mass
    from app.design.services.fem.transport import interpolate, locate
    if not mat.inertia or not mat.rho > 0:
        raise ValueError('Fluido transitorio: hace falta Navier-Stokes (inercia) con densidad ρ > 0.')
    ts = TimeSettings(time)
    n = mesh.n_nodes
    A, B, corners, pidx = st.assemble(mesh, 1.0)          # μ-normalised: unknowns v and p/μ
    n3, n_p = 3 * n, len(corners)
    nx = n3 + n_p
    M = mass(mesh)
    S = sp.bmat([[A, B.T], [B, None]], format='csr')
    zero_p = sp.csr_matrix((n_p, n_p))
    k_rho = mat.rho / mat.mu
    bc = _Bcs(mesh, bcs)
    if not len(bc.dofs):
        raise ValueError('Fluido: faltan condiciones de velocidad (paredes sin deslizamiento, entrada …).')
    ld = _Loads(mesh, loads)
    pin = st.is_enclosed(mesh, bc.dofs)
    cdofs = np.concatenate([bc.dofs, [n3]]) if pin else bc.dofs
    mask = np.ones(nx, bool)
    mask[cdofs] = False
    free = np.flatnonzero(mask)

    def cvals(t):
        v = bc.values(t)
        return np.concatenate([v, [0.0]]) if pin else v

    # initial state
    x = np.zeros(nx)
    if isinstance(initial, str) and initial == 'steady':
        v0, p0, _ = st.solve_ns(mesh, mat, ld.at(0.0), bc.dofs, bc.values(0.0))
        x[:n3] = v0.ravel()
        x[n3:] = p0[corners] / mat.mu
    elif initial is not None:
        x0 = np.asarray(initial, float)
        x[:n3] = (x0 if x0.ndim == 2 else np.tile(x0, (n, 1))).ravel()      # nodal field (N,3) or uniform (3,)
    x[cdofs] = cvals(0.0)
    v_prev = x[:n3].copy()                               # vⁿ⁻¹
    locs = locate(mesh, [p['point'] for p in probes]) if probes else []
    fsets = force_sets(mesh, bcs)
    h_el = element_size(mesh)
    out_steps = output_steps(ts.n_steps, ts.n_output)
    snaps = [(0.0, x[:n3].reshape(-1, 3).copy(), nodal_pressure(mesh, x[n3:] * mat.mu, corners, pidx))]
    curves, forces, energy, cfl_hist = [], [], [], []

    def record(t, x, R):
        v = x[:n3].reshape(-1, 3)
        p = nodal_pressure(mesh, x[n3:] * mat.mu, corners, pidx)
        if locs:
            row = [t]
            for loc in locs:
                row.append([interpolate(mesh, v[:, c], loc) for c in range(3)] + [interpolate(mesh, p, loc)])
            curves.append(row)
        if fsets:
            forces.append([t] + [[float(-R[3 * nd + c].sum()) for c in range(3)] for _, _, nd in fsets])
        energy.append([t, 0.5 * mat.rho * float(x[:n3] @ (M @ x[:n3]))])
        return v, p

    record(0.0, x, np.zeros(n3))
    dt = ts.dt
    n_inner = 0
    lin = _Solver()
    for step in range(1, ts.n_steps + 1):
        t = step * dt
        v_n = x[:n3].copy()
        bdf2 = ts.scheme == 'bdf2' and step > 1
        if bdf2:
            a0, hist = 1.5, 2.0 * v_n - 0.5 * v_prev        # (3v − 4vⁿ + vⁿ⁻¹)/(2Δt) = (1.5 v − hist)/Δt
            v_star = 2.0 * v_n - v_prev
        else:
            a0, hist = 1.0, v_n
            v_star = v_n
        f = np.concatenate([ld.at(t) / mat.mu, np.zeros(n_p)])
        f[:n3] += (k_rho / dt) * (M @ hist)
        xn = x.copy()
        xn[cdofs] = cvals(t)
        for it in range(ts.iterations):
            C, _ = st.convection(mesh, v_star.reshape(-1, 3), newton=False)
            K = S + sp.bmat([[k_rho * (a0 / dt * M + C), None], [None, zero_p]], format='csr')
            x_old = xn.copy()
            xn[free] = lin.solve(K[free][:, free], (f - K[:, cdofs] @ xn[cdofs])[free])
            n_inner += 1
            if not np.all(np.isfinite(xn)):
                raise ValueError(f'Navier-Stokes transitorio diverge en t = {t:.4g} s: reduzca el paso de tiempo Δt.')
            chg = float(np.abs(xn[:n3] - x_old[:n3]).max() / max(np.abs(xn[:n3]).max(), 1e-300))
            if it + 1 < ts.iterations:
                if chg < ts.tol:
                    break
                v_star = xn[:n3].copy()
        R = (K @ xn - f)[:n3] * mat.mu                      # force on the fluid at the prescribed DOFs
        v_prev, x = v_n, xn
        v, p = record(t, x, R)
        vm = np.linalg.norm(v, axis=1)
        cfl_hist.append(float((vm[mesh.elements[:, :4]].max(1) * dt / h_el).max()))
        if step in out_steps:
            snaps.append((t, v.copy(), p))
        if progress:
            progress(step, ts.n_steps, t)
    info = {'n_dof': int(nx), 'n_pressure': int(n_p), 'pressure_pinned': bool(pin), 'time': ts.to_dict(),
            'reaction': R, 'curves': curves, 'probe_locations': locs, 'energy': energy,
            'forces': {'sets': [{'label': lab, 'face_set': fs} for lab, fs, _ in fsets], 'history': forces},
            'courant_max': float(max(cfl_hist)) if cfl_hist else 0.0, 'solves': n_inner,
            'factorizations': lin.n_lu,
            'load_info': ld.info}
    return snaps, info
