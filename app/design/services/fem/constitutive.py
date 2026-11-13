"""Constitutive model registry.

FASE 2 full implementations: LinearElasticIsotropic, FourierIsotropic.
All others: stubs with correct interface.
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


# ── Linear Elastic Orthotropic (3D) ───────────────────────────────────────────

class LinearElasticOrthotropic:
    """Orthotropic elastic material.  Implemented: FASE 2."""

    def __init__(self, E1, E2, E3, G12, G13, G23, nu12, nu13, nu23, rho=0.0):
        self.E1, self.E2, self.E3 = E1, E2, E3
        self.G12, self.G13, self.G23 = G12, G13, G23
        self.nu12, self.nu13, self.nu23 = nu12, nu13, nu23
        self.rho = rho

    def get_D_matrix(self, state=None) -> np.ndarray:
        E1, E2, E3 = self.E1, self.E2, self.E3
        G12, G13, G23 = self.G12, self.G13, self.G23
        nu12, nu13, nu23 = self.nu12, self.nu13, self.nu23
        nu21 = nu12 * E2 / E1
        nu31 = nu13 * E3 / E1
        nu32 = nu23 * E3 / E2
        denom = 1 - nu12*nu21 - nu23*nu32 - nu13*nu31 - 2*nu21*nu32*nu13
        S = np.zeros((6, 6))
        S[0, 0] = (1 - nu23*nu32) / (E2*E3*denom)
        S[1, 1] = (1 - nu13*nu31) / (E1*E3*denom)
        S[2, 2] = (1 - nu12*nu21) / (E1*E2*denom)
        S[0, 1] = S[1, 0] = (nu21 + nu31*nu23) / (E2*E3*denom)
        S[0, 2] = S[2, 0] = (nu31 + nu21*nu32) / (E2*E3*denom)
        S[1, 2] = S[2, 1] = (nu32 + nu12*nu31) / (E1*E3*denom)
        S[3, 3] = 1.0 / G12
        S[4, 4] = 1.0 / G23
        S[5, 5] = 1.0 / G13
        return np.linalg.inv(S)

    def is_linear(self): return True
    def get_coupling_terms(self, pl): return {}
    def update_internal_variables(self, si): return {}


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


class HyperelasticNeoHookean(_Stub):
    def is_linear(self): return False


class ViscoelasticMaxwell(_Stub):
    def is_linear(self): return False


class FourierOrthotropic(_Stub): pass
class Thermoelastic(_Stub): pass
class Piezoelectric(_Stub): pass
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
