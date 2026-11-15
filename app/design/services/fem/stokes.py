"""Steady incompressible flow of a Newtonian fluid: Stokes (creeping, Re ≪ 1) or Navier–Stokes (laminar).

    ρ(v·∇)v − μ∇²v + ∇p = ρb,   ∇·v = 0          (the convective term only with ``inertia``)

Taylor–Hood P2–P1 on T10 meshes (inf-sup stable): velocity at every node (3 DOF), pressure at the corner
nodes only (linear). Laplacian form μ∫∇w:∇v dV, so the natural condition on a face without velocity BCs is
the pseudo-traction μ ∂v/∂n − p n = −p_face n ("do nothing": an outlet at p = 0, or a ``pressure`` load).

Spec entries reuse the structural ones: ``dofs``/``values`` BCs prescribe velocities [m/s] (no-slip wall =
all three = 0, slip wall = normal component = 0, inlet = velocity profile value), ``pressure`` loads [Pa] are
the face pressure (positive pushes into the fluid), ``gravity`` uses ρ. The system
[[A, Bᵀ], [B, 0]] is solved directly; when every boundary node has its normal velocity prescribed
(enclosed flow) the pressure is only defined up to a constant and one corner pressure is pinned to 0.

Navier–Stokes (``solve_ns``, material ``inertia: true``): Galerkin convection ∫w·ρ(v·∇)v dV (14-point degree-5
rule: exact for P2·P2·∇P2 on straight elements), started from the Stokes solution; Picard (Oseen) steps until the
update is small, then Newton (adds ∫w·ρ(v·∇v_k) dV) with a backtracking line search. If that fails, ρ is ramped
(continuation in Reynolds number). No stabilisation (SUPG/PSPG): the element Reynolds number ρ|v|h/μ should stay
moderate (the kernel warns), and the flow must be laminar and steady.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb

KEYS = ('mu',)


class FluidMaterial:
    def __init__(self, spec: dict):
        self.inertia = bool(spec.get('inertia'))       # Navier–Stokes (convective term) instead of Stokes
        mu = spec.get('mu')
        if mu in (None, ''):
            raise ValueError('Fluido newtoniano: falta la viscosidad dinámica μ [Pa·s].')
        self.mu = float(mu)
        self.rho = float(spec.get('rho') or 0.0)
        if not self.mu > 0:
            raise ValueError('Fluido newtoniano: la viscosidad μ debe ser > 0.')
        if self.rho < 0:
            raise ValueError('Fluido newtoniano: la densidad no puede ser negativa.')
        if self.inertia and not self.rho > 0:
            raise ValueError('Navier-Stokes: la inercia necesita la densidad ρ > 0.')
        self.stabilization = spec.get('stabilization') or None     # 'supg' (Navier–Stokes only)
        if self.stabilization not in (None, 'supg'):
            raise ValueError(f'Fluido: estabilización desconocida {self.stabilization!r} (supg).')
        if self.stabilization and not self.inertia:
            raise ValueError('La estabilización SUPG solo se aplica a Navier-Stokes (inercia activada).')


def pressure_index(mesh):
    """Corner nodes carry pressure: (corner node ids, map node → pressure index or −1)."""
    corners = np.unique(mesh.elements[:, :4])
    pidx = np.full(mesh.n_nodes, -1, np.int64)
    pidx[corners] = np.arange(len(corners))
    return corners, pidx


def assemble(mesh, mu: float = 1.0):
    """A (3N×3N, Laplacian form ×μ) and B (Np×3N, −∫q ∇·v dV) as CSR."""
    if mesh.element_type != 'T10':
        raise ValueError('Stokes necesita elementos cuadráticos T10 (Taylor-Hood P2-P1); T4 no es estable.')
    n = mesh.n_nodes
    corners, pidx = pressure_index(mesh)
    rows_a, cols_a, vals_a, rows_b, cols_b, vals_b = [], [], [], [], [], []
    for a in range(0, mesh.n_elements, 20_000):
        el = mesh.elements[a:a + 20_000]
        X = mesh.nodes[el]
        m = len(el)
        Kl = np.zeros((m, 10, 10))
        Be = np.zeros((m, 4, 30))
        for p, wg in zip(tb.GAUSS_TET4, tb.W_TET4):     # degree 2: exact for straight T10
            det, dN = tb._jac(X, tb.dshape('T10', p))  # (m,3,10)
            w = (wg * det)[:, None, None]
            Kl += w * np.einsum('man,mak->mnk', dN, dN, optimize=True)
            L = tb._L(p)                                # linear pressure shape functions (corners)
            div = dN.transpose(0, 2, 1).reshape(m, 30)  # ∂N_j/∂x_c at column 3j + c
            Be -= w * L[None, :, None] * div[:, None, :]
        rows_a.append(np.repeat(el, 10, axis=1).ravel())
        cols_a.append(np.tile(el, (1, 10)).ravel())
        vals_a.append(Kl.reshape(m, -1).ravel())
        pr = pidx[el[:, :4]]
        rows_b.append(np.repeat(pr, 30, axis=1).ravel())
        cols_b.append(np.tile(tb.element_dofs(el), (1, 4)).ravel())
        vals_b.append(Be.reshape(m, -1).ravel())
    Kl = sp.csr_matrix((np.concatenate(vals_a), (np.concatenate(rows_a), np.concatenate(cols_a))), shape=(n, n))
    A = (mu * sp.kron(Kl, sp.identity(3), format='csr')).tocsr()
    B = sp.csr_matrix((np.concatenate(vals_b), (np.concatenate(rows_b), np.concatenate(cols_b))),
                      shape=(len(corners), 3 * n))
    return A, B, corners, pidx


def is_enclosed(mesh, dofs: np.ndarray) -> bool:
    """True when no boundary face lets fluid in/out freely: the normal-direction velocity DOF (dominant axis
    of the face normal) is prescribed at every node of every boundary face → pressure level undetermined."""
    presc = np.zeros(3 * mesh.n_nodes, bool)
    presc[dofs] = True
    tris = tb.boundary_faces(mesh.elements)
    X = mesh.nodes[tris[:, :3]]
    nrm = np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0])
    ax = np.argmax(np.abs(nrm), axis=1)
    return bool(presc[3 * tris + ax[:, None]].all())


def solve(mesh, mat: FluidMaterial, F: np.ndarray, dofs: np.ndarray, vals: np.ndarray):
    """Velocity (N,3) [m/s], nodal pressure (N,) [Pa] (mid nodes = mean of the edge ends), info."""
    from scipy.sparse.linalg import spsolve
    A, B, corners, pidx = assemble(mesh, 1.0)           # μ-normalised: unknowns v and p/μ
    n3, n_p = 3 * mesh.n_nodes, len(corners)
    K = sp.bmat([[A, B.T], [B, None]], format='csr')
    rhs = np.concatenate([F / mat.mu, np.zeros(n_p)])
    pin = is_enclosed(mesh, dofs)
    cdofs = np.concatenate([dofs, [n3]]) if pin else dofs      # pin the first corner pressure
    cvals = np.concatenate([vals, [0.0]]) if pin else vals
    x = np.zeros(n3 + n_p)
    x[cdofs] = cvals
    mask = np.ones(len(x), bool)
    mask[cdofs] = False
    free = np.flatnonzero(mask)
    Kf = K[free][:, free].tocsc()
    x[free] = spsolve(Kf, rhs[free] - K[free][:, cdofs] @ cvals)
    resid = float(np.linalg.norm(K[free] @ x - rhs[free]) / max(np.linalg.norm(rhs[free]),
                                                                 np.linalg.norm(K[free][:, cdofs] @ cvals), 1e-30))
    v = x[:n3].reshape(-1, 3)
    pc = x[n3:] * mat.mu
    p = np.zeros(mesh.n_nodes)
    p[corners] = pc
    el = mesh.elements
    for k, (i, j) in enumerate(tb.T10_EDGES):
        p[el[:, 4 + k]] = 0.5 * (pc[pidx[el[:, i]]] + pc[pidx[el[:, j]]])
    # reaction of the prescribed velocities = force of the fluid on walls/inlets (sign: on the fluid)
    R = (K[:n3] @ x - rhs[:n3]) * mat.mu
    return v, p, {'n_dof': int(len(x)), 'n_pressure': int(n_p), 'pressure_pinned': pin, 'residual': resid,
                  'reaction': R}


def flow_rate(mesh, v: np.ndarray, face_set) -> tuple[float, float]:
    """Outward volume flow ∫v·n dA [m³/s] and area [m²] of a face set (or of whole boundary for '@all')."""
    from app.design.services.fem.assembler import _face_tris
    tris = tb.boundary_faces(mesh.elements) if face_set == '@all' else _face_tris(mesh, face_set)
    _, NndA, area = tb.surface_integrals(mesh.nodes, tris)
    sgn = tb.outward_sign(mesh.nodes, mesh.elements, tris)
    q = np.einsum('k,knj,knj->', sgn, NndA, v[tris])
    return float(q), float(area.sum())


def velocity_gradient_max(mesh, v: np.ndarray) -> float:
    """Max |∇v| (Frobenius) at the Gauss points [1/s] — for the wall shear-rate estimate."""
    X = mesh.nodes[mesh.elements]
    ve = v[mesh.elements]                               # (m,10,3)
    g = 0.0
    for p in tb.GAUSS_TET4:
        _, dN = tb._jac(X, tb.dshape('T10', p))
        G = np.einsum('man,mnc->mca', dN, ve)
        g = max(g, float(np.sqrt((G ** 2).sum(axis=(1, 2))).max()))
    return g


# ── Navier–Stokes ─────────────────────────────────────────────────────────────

def _rule5():
    from app.design.services.fem.error_estimator import QUAD_PTS, QUAD_W
    return QUAD_PTS, QUAD_W


def _geometry(mesh):
    """Shape functions and (weight·det J, physical ∇N) at the degree-5 points, cached on the mesh (the
    geometry does not change between Navier–Stokes iterations)."""
    key = (id(mesh.nodes), id(mesh.elements), mesh.n_elements)
    cache = getattr(mesh, '_ns_geometry', None)
    if cache is not None and cache[0] == key:
        return cache[1], cache[2]
    pts, wts = _rule5()
    X = mesh.nodes[mesh.elements]
    Ns, geo = [], []
    for p, wg in zip(pts, wts):
        det, dN = tb._jac(X, tb.dshape('T10', p))
        Ns.append(tb.shape('T10', p))
        geo.append((wg * det, dN))
    mesh._ns_geometry = (key, Ns, geo)
    return Ns, geo


def convection(mesh, v: np.ndarray, newton: bool = True):
    """Convection operators at the velocity field v (N,3), per unit density, as 3N×3N CSR:
    C(v) u = ∫ w·(v·∇)u dV  (Picard / Oseen);  J(v) u = ∫ w·(u·∇)v dV  (Newton term; None if newton=False).
    C(v) v is the convective force."""
    n = mesh.n_nodes
    Ns, geo = _geometry(mesh)
    rc, cc, vc, vj = [], [], [], []
    eye = np.eye(3)
    for a in range(0, mesh.n_elements, 5000):
        el = mesh.elements[a:a + 5000]
        ve = v[el]                                        # (m,10,3)
        m = len(el)
        Ce = np.zeros((m, 10, 10))
        Je = np.zeros((m, 10, 3, 10, 3)) if newton else None
        for N, (wdet, dNall) in zip(Ns, geo):
            w, dN = wdet[a:a + 5000], dNall[a:a + 5000]  # weight·det (m,), physical dN (m,3,10)
            vq = np.einsum('n,mnc->mc', N, ve)            # velocity at the point
            adv = np.einsum('mc,mcj->mj', vq, dN)         # v·∇N_j
            Ce += w[:, None, None] * N[None, :, None] * adv[:, None, :]
            if newton:
                G = np.einsum('mnc,mdn->mcd', ve, dN)     # ∂v_c/∂x_d
                NN = np.outer(N, N)
                Je += w[:, None, None, None, None] * NN[None, :, None, :, None] * G[:, None, :, None, :]
        dofs = tb.element_dofs(el)                       # (m,30), dof 3j+c
        Cb = np.einsum('mij,cd->micjd', Ce, eye).reshape(m, 30, 30)
        rc.append(np.repeat(dofs, 30, axis=1).ravel())
        cc.append(np.tile(dofs, (1, 30)).ravel())
        vc.append(Cb.ravel())
        if newton:
            vj.append(Je.reshape(m, 30, 30).ravel())
    shape = (3 * n, 3 * n)
    rows, cols = np.concatenate(rc), np.concatenate(cc)
    C = sp.csr_matrix((np.concatenate(vc), (rows, cols)), shape=shape)
    J = sp.csr_matrix((np.concatenate(vj), (rows, cols)), shape=shape) if newton else None
    return C, J


def solve_ns(mesh, mat: FluidMaterial, F: np.ndarray, dofs: np.ndarray, vals: np.ndarray, *,
             tol: float = 1e-9, max_iter: int = 30, picard_switch: float = 2e-2, max_picard: int = 8,
             progress=None, stabilization: str | None = None, body=None):
    """Steady Navier–Stokes. Returns (v, p, info) like ``solve`` plus info['navier_stokes'] with the iteration
    history. ``progress(iteration, message)`` is called once per iteration. ``stabilization='supg'`` adds
    ``supg`` (``body`` = uniform body force density [N/m³] for its residual, e.g. ρg)."""
    from scipy.sparse.linalg import splu
    A, B, corners, pidx = assemble(mesh, 1.0)            # μ-normalised: unknowns v and p/μ
    n3, n_p = 3 * mesh.n_nodes, len(corners)
    nx = n3 + n_p
    pin = is_enclosed(mesh, dofs)
    cdofs = np.concatenate([dofs, [n3]]) if pin else dofs
    cvals = np.concatenate([vals, [0.0]]) if pin else vals
    mask = np.ones(nx, bool)
    mask[cdofs] = False
    free = np.flatnonzero(mask)
    f = np.concatenate([F / mat.mu, np.zeros(n_p)])
    S = sp.bmat([[A, B.T], [B, None]], format='csr')     # Stokes operator
    zero_p = sp.csr_matrix((n_p, n_p))
    k_rho = mat.rho / mat.mu

    stab = stabilization == 'supg'
    fhat = None if body is None else np.asarray(body, float) / mat.mu

    def residual(x, lam):
        C, _ = convection(mesh, x[:n3].reshape(-1, 3), newton=False)
        r = S @ x + np.concatenate([(lam * k_rho) * (C @ x[:n3]), np.zeros(n_p)]) - f
        if stab:
            r[:n3] += supg(mesh, x[:n3].reshape(-1, 3), x[n3:], lam * k_rho, fhat, 'residual')[0]
        return r

    x0 = np.zeros(nx)                                    # Stokes start
    x0[cdofs] = cvals
    x0[free] = splu(S[free][:, free].tocsc()).solve((f - S @ x0)[free])
    # force scale: viscous + pressure force of the Stokes solution (and the applied loads)
    ref = max(float(np.linalg.norm(f[free])), float(np.linalg.norm((S @ x0 - f)[:n3])),
              float(np.linalg.norm((A @ x0[:n3]))), 1e-30)

    def run(lams):
        x = x0.copy()
        hist, n_pic, n_newt = [], 0, 0
        for lam in lams:
            r = residual(x, lam)
            r0 = float(np.linalg.norm(r[free]))
            mode, it, conv = 'picard', 0, False
            while it < max_iter:
                newton = mode == 'newton'
                C, J = convection(mesh, x[:n3].reshape(-1, 3), newton=newton)
                Kc = (C + J) if newton else C
                Kt = S + sp.bmat([[(lam * k_rho) * Kc, None], [None, zero_p]], format='csr')
                if stab:
                    _, Jvv, Jvp = supg(mesh, x[:n3].reshape(-1, 3), x[n3:], lam * k_rho, fhat,
                                       'newton' if newton else 'picard')
                    Kt = Kt + sp.bmat([[Jvv, Jvp], [None, zero_p]], format='csr')
                d = np.zeros(nx)
                d[free] = splu(Kt[free][:, free].tocsc()).solve(-r[free])
                rn0, alpha = float(np.linalg.norm(r[free])), 1.0
                for _ in range(6):                       # backtracking line search on the residual norm
                    xt = x + alpha * d
                    rt = residual(xt, lam)
                    if float(np.linalg.norm(rt[free])) < (1 - 1e-4 * alpha) * rn0 or rn0 < tol * ref:
                        break
                    alpha *= 0.5
                x, r = xt, rt
                it += 1
                n_pic += not newton
                n_newt += newton
                rn = float(np.linalg.norm(r[free])) / ref
                step = float(np.abs(alpha * d[:n3]).max() / max(np.abs(x[:n3]).max(), 1e-30))
                hist.append({'lambda': lam, 'mode': mode, 'residual': rn, 'step': step, 'alpha': alpha})
                if progress:
                    progress(len(hist), f'Navier-Stokes ({mode}) ρ×{lam:g}: residuo {rn:.2e}')
                if not np.isfinite(rn) or rn * ref > 1e6 * max(r0, ref):
                    return None, hist, n_pic, n_newt
                if rn < tol and step < max(1e3 * tol, 1e-8):
                    conv = True
                    break
                if mode == 'picard' and (step < picard_switch or it >= max_picard):
                    mode = 'newton'
            if not conv:
                return None, hist, n_pic, n_newt
        return x, hist, n_pic, n_newt

    ramp, history, cont = [1.0], [], 0
    while True:
        x, hist, n_pic, n_newt = run(ramp)
        history += hist
        if x is not None:
            break
        cont += 1
        if cont > 4:                                     # 1 → 2 → 4 → 8 → 16 ρ steps
            raise ValueError('Navier-Stokes no converge (ni con continuación en Reynolds hasta 16 pasos): el flujo '
                             'puede ser inestable o turbulento a este Reynolds, o la malla demasiado gruesa '
                             '(Reynolds de elemento alto). Refine la malla o reduzca la velocidad.')
        ramp = [i / 2 ** cont for i in range(1, 2 ** cont + 1)]
    v = x[:n3].reshape(-1, 3)
    pc = x[n3:] * mat.mu
    p = np.zeros(mesh.n_nodes)
    p[corners] = pc
    el = mesh.elements
    for k, (i, j) in enumerate(tb.T10_EDGES):
        p[el[:, 4 + k]] = 0.5 * (pc[pidx[el[:, i]]] + pc[pidx[el[:, j]]])
    r = residual(x, 1.0)
    R = r[:n3] * mat.mu                                  # = force on the fluid at prescribed-velocity DOFs
    final = [h for h in history if h['lambda'] == 1.0]
    return v, p, {'n_dof': int(nx), 'n_pressure': int(n_p), 'pressure_pinned': pin,
                  'residual': float(np.linalg.norm(r[free]) / ref), 'reaction': R,
                  'navier_stokes': {'converged': True, 'iterations': len(history), 'picard_iterations': n_pic,
                                    'stabilization': 'supg' if stab else None,
                                    'newton_iterations': n_newt, 'continuation_steps': len(ramp),
                                    'history': history,
                                    'newton_residuals': [h['residual'] for h in final if h['mode'] == 'newton']}}


def element_reynolds_max(mesh, v: np.ndarray, mat: FluidMaterial) -> float:
    """max over elements of ρ|v|h/μ (h = longest corner edge, |v| = max nodal speed in the element)."""
    X = mesh.nodes[mesh.elements[:, :4]]
    h = np.max([np.linalg.norm(X[:, i] - X[:, j], axis=1) for i in range(4) for j in range(i + 1, 4)], axis=0)
    vm = np.linalg.norm(v[mesh.elements], axis=2).max(axis=1)
    return float((mat.rho * vm * h / mat.mu).max())


# ── SUPG stabilisation (Navier–Stokes, advection-dominated) ─────────────────

def supg(mesh, v: np.ndarray, ph: np.ndarray, k: float, fhat=None, mode: str = 'newton'):
    """Residual-based SUPG for Taylor-Hood P2-P1 in the μ-normalised form (unknowns v and p̂ = p/μ):

        R_S = Σ_e ∫ τ (v·∇w) · r dV,   r = k (v·∇)v + ∇p̂ − Δv − f̂,   k = ρ/μ,
        τ = ((2|v|/h̃)² + (12/(k h̃²))²)^(-1/2)   [s],   h̃ = h/2 (h = longest corner edge, P2)

    Consistent (r = 0 for the exact solution); no PSPG (Taylor-Hood is inf-sup stable). Δv and ∇p̂ use the
    straight (corner) geometry: exact on straight T10, an approximation on curved ones.
    mode: 'residual' → R only; 'picard' → + Oseen-linearised operator (τ and the advecting velocity frozen);
    'newton' → + exact Jacobian (including ∂τ/∂v). Returns (R (3N,), Jvv (3N×3N) | None, Jvp (3N×Np) | None)."""
    n = mesh.n_nodes
    corners, pidx = pressure_index(mesh)
    Ns, geo = _geometry(mesh)
    fhat = np.zeros(3) if fhat is None else np.asarray(fhat, float)
    R = np.zeros(3 * n)
    jac = mode in ('picard', 'newton')
    rv, cv, vv, rp, cp, vp = [], [], [], [], [], []
    eye = np.eye(3)
    edges = tb.T10_EDGES
    for a in range(0, mesh.n_elements, 4000):
        el = mesh.elements[a:a + 4000]
        m = len(el)
        Xc = mesh.nodes[el[:, :4]]
        _, gL = tb._jac(Xc, tb.dshape('T4', (0.25, 0.25, 0.25)))                 # ∇L_i (m,3,4), constant
        lap = np.zeros((m, 10))
        for i in range(4):
            lap[:, i] = 4.0 * np.einsum('ma,ma->m', gL[:, :, i], gL[:, :, i])
        for e_, (i, j) in enumerate(edges):
            lap[:, 4 + e_] = 8.0 * np.einsum('ma,ma->m', gL[:, :, i], gL[:, :, j])
        h = np.max([np.linalg.norm(Xc[:, i] - Xc[:, j], axis=1) for i in range(4) for j in range(i + 1, 4)], axis=0)
        ht = 0.5 * h
        ve = v[el]                                                                # (m,10,3)
        gp = np.einsum('mci,mi->mc', gL, ph[pidx[el[:, :4]]])                     # ∇p̂ (m,3)
        dv = np.einsum('mj,mjc->mc', lap, ve)                                     # Δv (m,3)
        Re_ = np.zeros((m, 10, 3))
        Jv = np.zeros((m, 10, 3, 10, 3)) if jac else None
        Jp = np.zeros((m, 10, 3, 4)) if jac else None
        for N, (wdet, dNall) in zip(Ns, geo):
            w, dN = wdet[a:a + 4000], dNall[a:a + 4000]
            vq = np.einsum('n,mnc->mc', N, ve)
            G = np.einsum('mjc,mdj->mcd', ve, dN)                                 # ∂v_c/∂x_d
            r = k * np.einsum('mcd,md->mc', G, vq) + gp - dv - fhat[None, :]
            adv = np.einsum('md,mdj->mj', vq, dN)                                 # v·∇N_j
            tau = 1.0 / np.sqrt((2 * np.linalg.norm(vq, axis=1) / ht) ** 2 + (12.0 / (k * ht ** 2)) ** 2)
            wt = w * tau
            Re_ += wt[:, None, None] * adv[:, :, None] * r[:, None, :]
            if not jac:
                continue
            Jp += wt[:, None, None, None] * adv[:, :, None, None] * gL[:, None, :, :]
            # δr_c/δv_jd (frozen advection part) = δ_cd (k adv_j − lap_j)
            base = k * adv - lap
            Jv += (wt[:, None, None, None, None] * adv[:, :, None, None, None]
                   * eye[None, None, :, None, :] * base[:, None, None, :, None])
            if mode == 'newton':
                # + τ adv_i k N_j G_cd   (δ of the convected gradient's velocity factor)
                Jv += (wt * k)[:, None, None, None, None] * adv[:, :, None, None, None] \
                    * N[None, None, None, :, None] * G[:, None, :, None, :]
                # + τ N_j ∂_d N_i r_c    (δ of the streamline test function)
                Jv += wt[:, None, None, None, None] * dN.transpose(0, 2, 1)[:, :, None, None, :] \
                    * r[:, None, :, None, None] * N[None, None, None, :, None]
                # + ∂τ/∂v_jd adv_i r_c,  ∂τ/∂v_jd = −4 τ³ vq_d N_j / h̃²
                dtau = (-4.0 * w * tau ** 3 / ht ** 2)[:, None, None] * vq[:, None, :] * N[None, :, None]   # (m,j,d)
                Jv += adv[:, :, None, None, None] * r[:, None, :, None, None] * dtau[:, None, None, :, :]
        dofs = tb.element_dofs(el)                                                # (m,30)
        np.add.at(R, dofs, Re_.reshape(m, 30))
        if jac:
            rv.append(np.repeat(dofs, 30, axis=1).ravel())
            cv.append(np.tile(dofs, (1, 30)).ravel())
            vv.append(Jv.reshape(m, 30, 30).ravel())
            pc = pidx[el[:, :4]]
            rp.append(np.repeat(dofs, 4, axis=1).ravel())
            cp.append(np.tile(pc, (1, 30)).ravel())
            vp.append(Jp.reshape(m, 30, 4).ravel())
    if not jac:
        return R, None, None
    Jvv = sp.csr_matrix((np.concatenate(vv), (np.concatenate(rv), np.concatenate(cv))), shape=(3 * n, 3 * n))
    Jvp = sp.csr_matrix((np.concatenate(vp), (np.concatenate(rp), np.concatenate(cp))), shape=(3 * n, len(corners)))
    return R, Jvv, Jvp
