"""Constitutive model registry.

Implemented: linear elastic isotropic / orthotropic (material axes), J2 plasticity (FASE 2.5, wrapper),
Fourier isotropic / orthotropic, thermoelastic (isotropic + α; the kernel does the coupling).
The remaining entries are stubs with the planned interface.
"""
from __future__ import annotations
import numpy as np


# ── Linear Elastic Isotropic (3D) ─────────────────────────────────────────────

class LinearElasticIsotropic:
    """3D linear elastic isotropic material — Hooke's law.

    Constitutive matrix D (Voigt notation):
        σ = D ε,  where ε = [εxx, εyy, εzz, γxy, γyz, γxz]
    """

    def __init__(self, E: float, nu: float, rho: float = 0.0):
        if E <= 0:
            raise ValueError(f"E must be positive, got {E}")
        if not (-1.0 < nu < 0.5):
            raise ValueError(f"Poisson ratio nu must be in (-1, 0.5), got {nu}")
        self.E = float(E)
        self.nu = float(nu)
        self.rho = float(rho)

    def get_D_matrix(self, state: dict = None) -> np.ndarray:
        """Return 6×6 isotropic elastic constitutive matrix."""
        E, nu = self.E, self.nu
        lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
        mu  = E / (2.0 * (1.0 + nu))

        D = np.zeros((6, 6), dtype=np.float64)
        D[0, 0] = D[1, 1] = D[2, 2] = lam + 2.0 * mu
        D[0, 1] = D[0, 2] = D[1, 0] = D[1, 2] = D[2, 0] = D[2, 1] = lam
        D[3, 3] = D[4, 4] = D[5, 5] = mu
        return D

    def get_coupling_terms(self, physics_list: list) -> dict:
        return {}   # no coupling for pure linear elastic

    def update_internal_variables(self, strain_inc) -> dict:
        return {}   # no internal variables (elastic, path-independent)

    def is_linear(self) -> bool:
        return True

    def to_dict(self) -> dict:
        return {'type': 'linear_elastic_isotropic', 'E': self.E, 'nu': self.nu, 'rho': self.rho}

    @classmethod
    def from_dict(cls, d: dict) -> LinearElasticIsotropic:
        return cls(E=d['E'], nu=d['nu'], rho=d.get('rho', 0.0))


# ── Material axes (anisotropic models) ────────────────────────────────────────

def material_axes(spec: dict | None) -> np.ndarray:
    """R (3×3): rows = material axes 1, 2, 3 in the global (CAD) frame, from ``axis_1`` and ``axis_2``
    (any length; axis 2 is re-orthogonalised against axis 1, axis 3 = 1 × 2). Default: the global axes."""
    spec = spec or {}
    a1 = np.asarray(spec.get('axis_1') or (1.0, 0.0, 0.0), dtype=np.float64)
    a2 = np.asarray(spec.get('axis_2') or (0.0, 1.0, 0.0), dtype=np.float64)
    if a1.shape != (3,) or a2.shape != (3,) or not np.linalg.norm(a1) > 0:
        raise ValueError('axis_1 / axis_2 deben ser vectores 3D no nulos')
    e1 = a1 / np.linalg.norm(a1)
    r2 = a2 - (a2 @ e1) * e1
    if not np.linalg.norm(r2) > 1e-9 * np.linalg.norm(a2):
        raise ValueError('axis_2 no puede ser nulo ni paralelo a axis_1')
    e2 = r2 / np.linalg.norm(r2)
    return np.stack([e1, e2, np.cross(e1, e2)])


# Voigt order of the kernel (tet_batch._B): xx, yy, zz, xy, yz, xz — engineering shear strains.
_VOIGT = ((0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (0, 2))


def strain_rotation(R: np.ndarray) -> np.ndarray:
    """T (6×6) with ε_material = T ε_global (engineering-shear Voigt); R rows = material axes.
    ε'_ij = R_ik R_jl ε_kl; a global shear γ_kl = 2ε_kl appears in both (k,l) and (l,k); a material
    shear is γ'_ij = 2ε'_ij."""
    T = np.zeros((6, 6))
    for I, (i, j) in enumerate(_VOIGT):
        f = 1.0 if i == j else 2.0
        for J, (k, l) in enumerate(_VOIGT):
            if k == l:
                T[I, J] = f * R[i, k] * R[j, l]
            else:
                T[I, J] = f * 0.5 * (R[i, k] * R[j, l] + R[i, l] * R[j, k])
    return T


def rotate_D(D_mat: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Global D from the material-axes D (energy invariance): D_g = Tᵀ D_m T."""
    T = strain_rotation(R)
    return T.T @ D_mat @ T


def rotate_tensor(t_mat_diag, R: np.ndarray) -> np.ndarray:
    """Global second-order tensor (3×3) from its principal values along the material axes: Rᵀ diag R."""
    return R.T @ np.diag(np.asarray(t_mat_diag, dtype=np.float64)) @ R


# ── Linear Elastic Orthotropic (3D) ───────────────────────────────────────────

class LinearElasticOrthotropic:
    """Orthotropic linear elasticity (wood, unidirectional composites, printed parts).

    Moduli along the material axes 1-2-3 (``axis_1``, ``axis_2`` in the global frame, see material_axes);
    νij = −εj/εi under uniaxial stress along i (so νji = νij Ej/Ei). Compliance S → D = S⁻¹ in the
    material axes, rotated to the global frame. Positive definiteness is checked.
    """
    KEYS = ('E1', 'E2', 'E3', 'G12', 'G13', 'G23', 'nu12', 'nu13', 'nu23')

    def __init__(self, E1, E2, E3, G12, G13, G23, nu12, nu13, nu23, rho=0.0, axis_1=None, axis_2=None):
        self.E1, self.E2, self.E3 = float(E1), float(E2), float(E3)
        self.G12, self.G13, self.G23 = float(G12), float(G13), float(G23)
        self.nu12, self.nu13, self.nu23 = float(nu12), float(nu13), float(nu23)
        self.rho = float(rho or 0.0)
        self.R = material_axes({'axis_1': axis_1, 'axis_2': axis_2})
        if min(self.E1, self.E2, self.E3, self.G12, self.G13, self.G23) <= 0:
            raise ValueError('Los módulos E1, E2, E3, G12, G13, G23 deben ser positivos')
        S = self.compliance()
        if np.linalg.eigvalsh(S).min() <= 0:
            raise ValueError('Constantes ortótropas no admisibles (la matriz de rigidez no es definida '
                             'positiva): revisa los coeficientes de Poisson')
        self.D_material = np.linalg.inv(S)
        self._D = rotate_D(self.D_material, self.R)

    def compliance(self) -> np.ndarray:
        """S in the material axes (Voigt 11 22 33 12 23 13)."""
        S = np.zeros((6, 6))
        S[0, 0], S[1, 1], S[2, 2] = 1 / self.E1, 1 / self.E2, 1 / self.E3
        S[0, 1] = S[1, 0] = -self.nu12 / self.E1
        S[0, 2] = S[2, 0] = -self.nu13 / self.E1
        S[1, 2] = S[2, 1] = -self.nu23 / self.E2
        S[3, 3], S[4, 4], S[5, 5] = 1 / self.G12, 1 / self.G23, 1 / self.G13
        return S

    def get_D_matrix(self, state=None) -> np.ndarray:
        return self._D

    def is_linear(self): return True
    def get_coupling_terms(self, pl): return {}
    def update_internal_variables(self, si): return {}

    @classmethod
    def from_dict(cls, d: dict) -> 'LinearElasticOrthotropic':
        missing = [k for k in cls.KEYS if d.get(k) in (None, '')]
        if missing:
            raise ValueError(f"Material ortótropo: faltan {', '.join(missing)}")
        return cls(*(float(d[k]) for k in cls.KEYS), rho=d.get('rho', 0.0),
                   axis_1=d.get('axis_1'), axis_2=d.get('axis_2'))


class Thermoelastic(LinearElasticIsotropic):
    """Isotropic thermoelasticity ε = S:σ + α(T − T_ref)I. The kernel's one-way thermo-mechanical
    coupling (thermal.thermal_load / eps0) is what uses α and T_ref; D is the isotropic one, so
    'thermoelastic' behaves as 'linear_elastic_isotropic' with α."""

    def __init__(self, E: float, nu: float, rho: float = 0.0, alpha: float = 0.0, T_ref: float = 20.0):
        super().__init__(E, nu, rho)
        self.alpha, self.T_ref = float(alpha or 0.0), float(T_ref)

    def get_coupling_terms(self, physics_list: list) -> dict:
        return {'alpha': self.alpha, 'T_ref': self.T_ref} if 'thermal' in (physics_list or []) else {}

    @classmethod
    def from_dict(cls, d: dict) -> 'Thermoelastic':
        return cls(E=d['E'], nu=d['nu'], rho=d.get('rho', 0.0), alpha=d.get('alpha', 0.0),
                   T_ref=d.get('T_ref', 20.0))


# ── Thermal ───────────────────────────────────────────────────────────────────

class FourierIsotropic:
    """q = -k ∇T.  Returns 3×3 conductivity matrix."""

    def __init__(self, k: float, rho: float = 0.0, cp: float = 0.0):
        self.k, self.rho, self.cp = k, rho, cp

    def get_D_matrix(self, state=None) -> np.ndarray:
        return self.k * np.eye(3)

    def is_linear(self): return True
    def get_coupling_terms(self, pl): return {}
    def update_internal_variables(self, si): return {}


class FourierOrthotropic:
    """q = −K ∇T with K = Rᵀ diag(k1, k2, k3) R (principal conductivities along the material axes)."""

    def __init__(self, k1: float, k2: float, k3: float, rho: float = 0.0, cp: float = 0.0,
                 axis_1=None, axis_2=None):
        self.k = (float(k1), float(k2), float(k3))
        if min(self.k) <= 0:
            raise ValueError('Las conductividades k1, k2, k3 deben ser positivas')
        self.rho, self.cp = rho, cp
        self.R = material_axes({'axis_1': axis_1, 'axis_2': axis_2})

    def get_D_matrix(self, state=None) -> np.ndarray:
        return rotate_tensor(self.k, self.R)

    def is_linear(self): return True
    def get_coupling_terms(self, pl): return {}
    def update_internal_variables(self, si): return {}

    @classmethod
    def from_dict(cls, d: dict) -> 'FourierOrthotropic':
        k = d.get('k')
        k1, k2, k3 = (k if isinstance(k, (list, tuple)) else (d['k1'], d['k2'], d['k3']))
        return cls(k1, k2, k3, d.get('rho', 0.0), d.get('cp', 0.0), d.get('axis_1'), d.get('axis_2'))


def conductivity(mat: dict):
    """Thermal conductivity of a material spec: float k (isotropic) or the global 3×3 tensor when ``k`` is
    a list [k1, k2, k3] of principal values along the material axes."""
    k = mat.get('k')
    if isinstance(k, (list, tuple)):
        return FourierOrthotropic.from_dict(mat).get_D_matrix()
    return float(k or 0.0)


def thermal_expansion(mat: dict):
    """α of a material spec: float (isotropic) or the global engineering-Voigt 6-vector when ``alpha`` is
    a list [α1, α2, α3] along the material axes (thermal strain = α ΔT)."""
    a = mat.get('alpha')
    if isinstance(a, (list, tuple)):
        A = rotate_tensor(a, material_axes(mat))
        return np.array([A[0, 0], A[1, 1], A[2, 2], 2 * A[0, 1], 2 * A[1, 2], 2 * A[0, 2]])
    return float(a or 0.0)


# ── Stubs ─────────────────────────────────────────────────────────────────────

class _Stub:
    def get_D_matrix(self, state=None):         raise NotImplementedError(f"{type(self).__name__}: FASE 2+")
    def get_coupling_terms(self, pl):           return {}
    def update_internal_variables(self, si):    return {}
    def is_linear(self):                        return True   # safe default for dispatch


class ElastoplasticVonMises:
    """J2 plasticity with isotropic hardening (FASE 2.5). The return mapping lives in
    ``fem.plasticity.J2Material``; this wrapper gives the kernel the elastic D and is_linear() = False."""

    def __init__(self, E: float, nu: float, sigma_y: float, rho: float = 0.0, hardening: dict | None = None):
        from app.design.services.fem.plasticity import J2Material
        self.rho = rho
        self.j2 = J2Material(E, nu, sigma_y, hardening)

    def get_D_matrix(self, state=None) -> np.ndarray:
        return self.j2.D

    def get_coupling_terms(self, pl): return {}
    def update_internal_variables(self, si): return {}
    def is_linear(self): return False

    @classmethod
    def from_dict(cls, d: dict) -> 'ElastoplasticVonMises':
        return cls(float(d['E']), float(d['nu']), float(d.get('sigma_y') or 0.0), float(d.get('rho', 0.0) or 0.0),
                   d.get('hardening'))


class HyperelasticNeoHookean:
    """Compressible Neo-Hookean (large strains), total Lagrangian: ``fem.hyperelastic``. μ and λ come from
    the small-strain E and ν; get_D_matrix() is the small-strain (λ, μ) D (initial tangent)."""

    def __init__(self, E: float, nu: float, rho: float = 0.0):
        from app.design.services.fem.hyperelastic import NeoHookean
        self.rho = float(rho or 0.0)
        self.nh = NeoHookean(E, nu)

    def get_D_matrix(self, state=None) -> np.ndarray:
        return LinearElasticIsotropic(self.nh.E, self.nh.nu).get_D_matrix()

    def get_coupling_terms(self, pl): return {}
    def update_internal_variables(self, si): return {}
    def is_linear(self): return False

    @classmethod
    def from_dict(cls, d: dict) -> 'HyperelasticNeoHookean':
        return cls(float(d['E']), float(d['nu']), d.get('rho', 0.0))


class ViscoelasticMaxwell:
    """Generalized Maxwell (Prony series) linear viscoelasticity, ν constant: ``fem.viscoelastic``.
    ``E`` is the instantaneous modulus E₀; ``prony`` = [{g, tau [s]}, ...] with Σg < 1. get_D_matrix() is D₀."""

    def __init__(self, E: float, nu: float, prony, rho: float = 0.0):
        from app.design.services.fem.viscoelastic import PronySeries
        self.rho = float(rho or 0.0)
        self.prony = PronySeries(E, nu, prony)

    def get_D_matrix(self, state=None) -> np.ndarray:
        return LinearElasticIsotropic(self.prony.E0, self.prony.nu).get_D_matrix()

    def get_coupling_terms(self, pl): return {}
    def update_internal_variables(self, si): return {}
    def is_linear(self): return False      # history dependent (time stepping)

    @classmethod
    def from_dict(cls, d: dict) -> 'ViscoelasticMaxwell':
        return cls(float(d['E']), float(d['nu']), d.get('prony') or [], d.get('rho', 0.0))


class Piezoelectric:
    """Linear piezoelectricity (stress-charge form, poling along material axis 3): ``fem.piezo``.
    get_D_matrix() is the short-circuit stiffness Cᴱ (global)."""

    def __init__(self, spec: dict):
        from app.design.services.fem.piezo import PiezoMaterial
        self.rho = float(spec.get('rho') or 0.0)
        self.pm = PiezoMaterial(spec)

    def get_D_matrix(self, state=None) -> np.ndarray:
        return self.pm.C

    def get_coupling_terms(self, pl): return {'e': self.pm.e, 'kappa': self.pm.kappa}
    def update_internal_variables(self, si): return {}
    def is_linear(self): return True

    @classmethod
    def from_dict(cls, d: dict) -> 'Piezoelectric':
        return cls(d)
class ThermoPiezoelectric(_Stub): pass
class NewtonianFluid(_Stub): pass
class LinearMagnetic(_Stub): pass


# ── Registry ──────────────────────────────────────────────────────────────────

CONSTITUTIVE_REGISTRY: dict = {
    'linear_elastic_isotropic':   LinearElasticIsotropic,
    'linear_elastic_orthotropic': LinearElasticOrthotropic,
    'elastoplastic_vonmises':     ElastoplasticVonMises,
    'hyperelastic_neohookean':    HyperelasticNeoHookean,
    'viscoelastic_maxwell':       ViscoelasticMaxwell,
    'fourier_isotropic':          FourierIsotropic,
    'fourier_orthotropic':        FourierOrthotropic,
    'thermoelastic':              Thermoelastic,
    'piezoelectric':              Piezoelectric,
    'thermopiezoelectric':        ThermoPiezoelectric,
    'newtonian_fluid':            NewtonianFluid,
    'linear_magnetic':            LinearMagnetic,
}


def build_material(spec: dict):
    """Instantiate a constitutive model from a dict spec.

    spec must contain 'type' (a key in CONSTITUTIVE_REGISTRY) plus
    any model-specific parameters (e.g. E, nu, rho for linear elastic).
    """
    model_type = spec.get('type', 'linear_elastic_isotropic')
    cls = CONSTITUTIVE_REGISTRY.get(model_type)
    if cls is None:
        raise ValueError(f"Unknown constitutive model '{model_type}'. "
                         f"Available: {sorted(CONSTITUTIVE_REGISTRY.keys())}")

    # Build from dict for supported types
    if hasattr(cls, 'from_dict'):
        return cls.from_dict(spec)

    # Generic construction for parameterized models
    init_params = {k: v for k, v in spec.items() if k != 'type'}
    return cls(**init_params) if init_params else cls()
