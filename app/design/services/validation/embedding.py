"""Study embedding for similar-case search (plan 8.2, "embedding semántico" of the material).

A study (solver spec) becomes a fixed set of named vector blocks; the similarity of two studies is the
weighted mean of the per-block cosine similarities. No language model: the semantic part is the material
*family*, recognised from the material name (library name, MATERIAL node label) with a keyword taxonomy, and
the constitutive model; continuous quantities (log E, ν, log ρ, σy, size, slenderness, DOF) are encoded with
radial-basis soft bins so that the cosine of two encodings decays smoothly with their distance.

    geometry        same CAD/mesh identity → 1; otherwise shape (sorted bbox extents: size, aspect ratios),
                    capped at 0.8 (another part is never "the same geometry")
    material        constitutive model group, family (steel, aluminium, polymer…), log E, ν, log ρ, log σy
    physics         structural / thermal / piezoelectric / fluid / magnetic (+ non-linear material)
    loading         load kinds + support kinds (multi-hot)
    discretization  element order, log DOF

Blocks missing in either study (unknown family, no DOF yet…) drop out and the weights are renormalised.
Deterministic and cheap (pure numpy, a few hundred numbers per study): the history is scored on the fly.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata

import numpy as np

EMBEDDING_VERSION = 1

WEIGHTS = {'geometry': 0.30, 'material': 0.35, 'physics': 0.10, 'loading': 0.15, 'discretization': 0.10}

MODEL_GROUPS = {
    'linear_elastic_isotropic': 'elastic', 'thermoelastic': 'elastic', 'fourier_isotropic': 'thermal_only',
    'fourier_orthotropic': 'thermal_only', 'linear_elastic_orthotropic': 'orthotropic',
    'elastoplastic_vonmises': 'plastic', 'hyperelastic_neohookean': 'hyperelastic',
    'viscoelastic_maxwell': 'viscoelastic', 'piezoelectric': 'piezoelectric', 'thermopiezoelectric': 'piezoelectric',
    'newtonian_fluid': 'fluid', 'linear_magnetic': 'magnetic', 'scalar_transport': 'transport',
}
GROUPS = sorted(set(MODEL_GROUPS.values()))
# groups that share most of the mechanics (a plastic steel study is closer to an elastic one than to a fluid)
GROUP_KIN = {('elastic', 'plastic'): 0.6, ('elastic', 'orthotropic'): 0.5, ('elastic', 'viscoelastic'): 0.4,
             ('elastic', 'hyperelastic'): 0.4, ('hyperelastic', 'viscoelastic'): 0.5, ('elastic', 'thermal_only'): 0.2}

# keyword taxonomy (accents folded, lower case, word-start match)
FAMILIES = {
    'stainless': ['inox', 'stainless', 'aisi 3', 'aisi3', '304', '316', '17-4'],
    'steel': ['acero', 'steel', 'aisi', 'sae 1', 'sae1', 's235', 's275', 's355', 'a36', '1045', '4140', 'f-1'],
    'cast_iron': ['fundicion', 'cast iron', 'gg', 'ggg', 'nodular'],
    'aluminium': ['alumin', 'al ', 'al-', '6061', '6063', '7075', '2024', '5083'],
    'titanium': ['titan', 'ti-6', 'ti6', 'ti '],
    'copper': ['cobre', 'copper', 'laton', 'brass', 'bronce', 'bronze'],
    'magnesium': ['magnesio', 'magnesium', 'az31', 'az91'],
    'polymer': ['abs', 'pla', 'petg', 'nylon', 'poliamida', 'pa6', 'pa12', 'polipropileno', 'polypropylene', 'pp ',
                'polietileno', 'polyethylene', 'hdpe', 'peek', 'pom', 'acetal', 'policarbonato', 'polycarbonate',
                'pvc', 'polimero', 'polymer', 'resina', 'resin', 'epoxi', 'epoxy'],
    'composite': ['cfrp', 'gfrp', 'fibra', 'fiber', 'fibre', 'carbono', 'carbon', 'compuesto', 'composite',
                  'laminado', 'laminate', 'kevlar'],
    'elastomer': ['caucho', 'rubber', 'silicona', 'silicone', 'elastomer', 'epdm', 'nbr', 'neopreno', 'neoprene',
                  'poliuretano', 'polyurethane', 'tpu'],
    'ceramic': ['ceramic', 'ceramica', 'alumina', 'zirconia', 'sic', 'nitruro', 'vidrio', 'glass'],
    'wood': ['madera', 'wood', 'pino', 'pine', 'roble', 'oak'],
    'concrete': ['hormigon', 'concreto', 'concrete', 'cemento', 'cement'],
    'piezoceramic': ['pzt', 'piezo', 'titanato'],
    'liquid': ['agua', 'water', 'glicerina', 'glycerin', 'aceite', 'oil', 'sae 30', 'fluido', 'fluid'],
    'magnet': ['ndfeb', 'neodimio', 'neodymium', 'ferrita', 'ferrite', 'smco', 'alnico', 'iman', 'magnet',
               'acero electrico', 'electrical steel', 'silicio', 'silicon steel'],
}
FAMILY_NAMES = sorted(FAMILIES)
# families that behave alike (both metals, both soft polymers…): partial credit
FAMILY_KIN = {('steel', 'stainless'): 0.7, ('steel', 'cast_iron'): 0.6, ('aluminium', 'magnesium'): 0.6,
              ('steel', 'titanium'): 0.3, ('aluminium', 'titanium'): 0.4, ('aluminium', 'steel'): 0.3,
              ('copper', 'aluminium'): 0.3, ('polymer', 'elastomer'): 0.4, ('polymer', 'composite'): 0.3,
              ('ceramic', 'piezoceramic'): 0.4, ('magnet', 'steel'): 0.2}

LOAD_KINDS = ('force', 'pressure', 'gravity', 'force_per_node', 'heat_flux', 'convection', 'heat_source',
              'surface_charge', 'magnetic_flux', 'species_flux', 'exchange', 'species_source', 'point_source')
BC_KINDS = ('fixed', 'partial', 'symmetry', 'prescribed', 'temperature', 'voltage', 'velocity', 'magnetic_potential',
            'concentration')
PHYSICS = ('structural', 'thermal', 'piezoelectric', 'fluid', 'magnetic', 'nonlinear', 'transport')


# ── encoders ──────────────────────────────────────────────────────────────────

def _fold(text: str) -> str:
    t = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    return ' ' + re.sub(r'[_/,;()]+', ' ', t) + ' '


def material_family(name: str | None) -> str | None:
    """Family of a material from its name ('Acero AISI 1045' → steel, 'PLA impreso' → polymer), or None.
    Most specific first: stainless before steel, electrical steel → magnet."""
    t = _fold(name)
    if not t.strip():
        return None
    order = ['magnet', 'stainless', 'piezoceramic', 'liquid', 'composite', 'cast_iron', 'steel', 'aluminium',
             'titanium', 'copper', 'magnesium', 'elastomer', 'polymer', 'ceramic', 'wood', 'concrete']
    for fam in order:
        for kw in FAMILIES[fam]:
            k = kw.strip()
            if re.search(r'(?<![a-z0-9])' + re.escape(k), t):
                return fam
    return None


def _rbf(value: float | None, lo: float, hi: float, n: int = 12, width: float | None = None) -> np.ndarray:
    """Soft one-hot of a scalar on n centres in [lo, hi]: cos(enc(a), enc(b)) = exp(−(a−b)²/(4σ²))."""
    if value is None or not np.isfinite(value):
        return np.zeros(n)
    c = np.linspace(lo, hi, n)
    s = width or (hi - lo) / (n - 1)
    return np.exp(-0.5 * ((float(np.clip(value, lo - 2 * s, hi + 2 * s)) - c) / s) ** 2)


def _onehot(key, keys) -> np.ndarray:
    v = np.zeros(len(keys))
    if key in keys:
        v[list(keys).index(key)] = 1.0
    return v


def _kin_vector(key, keys, kin) -> np.ndarray:
    """One-hot with partial credit to related categories (keeps cosine = kin for a related pair)."""
    v = _onehot(key, keys)
    if key is None or key not in keys:
        return v
    for (a, b), w in kin.items():
        other = b if a == key else a if b == key else None
        if other in keys:
            v[list(keys).index(other)] = w
    return v


def _log10(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return math.log10(x) if x > 0 else None


# ── study → blocks ────────────────────────────────────────────────────────────

def geometry_dims(spec: dict) -> list | None:
    """Sorted bbox extents [m] of the study geometry: parametric meshes from their parameters, CAD from the
    stored bbox (DB lookup by geometry_id or STEP sha256; None outside an app context)."""
    src, p = spec.get('mesh_source'), spec.get('mesh_params') or {}
    try:
        if src == 'cantilever' or (not src and p.get('length')):
            d = [p.get('length', 0.05), p.get('width', 0.01), p.get('height', 0.01)]
        elif src == 'plate':
            d = [p.get('length', 0.2), p.get('height', 0.1), p.get('thickness', 0.01)]
        elif src == 'ring':
            b = float(p.get('outer_radius', 0.02))
            d = [b, b, p.get('thickness', 0.002)]
        else:
            geo = spec.get('geometry') if isinstance(spec.get('geometry'), dict) else {}
            gid, sha = spec.get('geometry_id') or geo.get('geometry_id'), geo.get('step_sha256')
            if not (gid or sha):
                return None
            from app.geometry.models import Geometry
            g = Geometry.query.get(gid) if gid else Geometry.query.filter_by(sha256=sha).first()
            if g is None or not g.bbox:
                return None
            bb = g.bbox
            d = [(bb[3] - bb[0]) * 1e-3, (bb[4] - bb[1]) * 1e-3, (bb[5] - bb[2]) * 1e-3]
        d = sorted((float(x) for x in d), reverse=True)
        return d if d[0] > 0 else None
    except Exception:
        return None


def _geometry_identity(spec: dict):
    geo = spec.get('geometry') if isinstance(spec.get('geometry'), dict) else None
    if geo:
        return geo.get('step_sha256') or geo.get('geometry_id')
    if spec.get('geometry_id'):
        return str(spec['geometry_id'])
    if isinstance(spec.get('cae_mesh'), dict):
        return spec['cae_mesh'].get('mesh_file_sha256') or spec['cae_mesh'].get('mesh_id')
    if spec.get('inline_mesh_sha256'):
        return spec['inline_mesh_sha256']
    return json.dumps([spec.get('mesh_source'), spec.get('mesh_params')], sort_keys=True, default=str)


def _bc_kinds(bcs: list) -> set:
    out = set()
    for b in bcs or []:
        for k in ('temperature', 'voltage', 'magnetic_potential', 'concentration'):
            if k in b:
                out.add(k)
                break
        else:
            dofs, vals = b.get('dofs') or [0, 1, 2], b.get('values') or []
            if b.get('symmetry'):
                out.add('symmetry')
            elif any(float(v or 0) != 0 for v in vals):
                out.add('velocity' if len(dofs) == 3 and len(vals) == 3 else 'prescribed')
            else:
                out.add('fixed' if len(dofs) == 3 else 'partial')
    return out


def embed_study(spec: dict, material_name: str | None = None, material_id: str | None = None,
                n_dof: int | None = None) -> dict:
    """Blocks {name: vector} + exact keys (geometry identity, material id) of a study."""
    mat = spec.get('material') or {}
    mtype = mat.get('type') or 'linear_elastic_isotropic'
    group = MODEL_GROUPS.get(mtype, 'elastic')
    fam = material_family(material_name)
    E = mat.get('E') or mat.get('E1') or mat.get('c33')
    nu = mat.get('nu', mat.get('nu12'))
    blocks = {}

    dims = geometry_dims(spec)
    if dims:
        size = _log10(dims[0])
        a1, a2 = dims[0] / max(dims[1], 1e-12), dims[1] / max(dims[2], 1e-12)
        blocks['geometry'] = np.concatenate([_rbf(size, -4, 1, 11, 0.25),            # 0.1 mm … 10 m
                                             _rbf(math.log10(a1), 0, 2.5, 11, 0.15),  # slenderness
                                             _rbf(math.log10(a2), 0, 2.5, 11, 0.15)])

    mparts = [_kin_vector(group, GROUPS, GROUP_KIN) * 0.8]
    if fam:                                          # compared only when both studies know their family
        blocks['family'] = _kin_vector(fam, FAMILY_NAMES, FAMILY_KIN) * 1.5
    if group == 'fluid':
        mparts += [_rbf(_log10(mat.get('mu')), -4, 3, 15, 0.25), np.zeros(12)]
    elif group == 'magnetic':
        mparts += [_rbf(_log10(mat.get('mu_r')), 0, 5, 15, 0.25),
                   _rbf(float(np.linalg.norm(mat.get('Br') or [0, 0, 0])), 0, 1.5, 12, 0.15)]
    else:
        mparts += [1.5 * _rbf(_log10(E), 5, 12, 15, 0.12),
                   _rbf(None if nu is None else float(nu), 0, 0.5, 12, 0.03)]
    mparts.append(_rbf(_log10(mat.get('rho')), 2.5, 4.5, 9, 0.15))
    sy = mat.get('sigma_y') or mat.get('yield_strength')
    mparts.append(_rbf(_log10(sy), 6, 9.5, 8, 0.15))
    blocks['material'] = np.concatenate(mparts)

    phys = set(spec.get('physics') or ['structural'])
    nonlinear = group in ('plastic', 'hyperelastic', 'viscoelastic')
    pv = np.array([float(p in phys) for p in PHYSICS[:-1]] + [float(nonlinear)])
    blocks['physics'] = pv

    loads = {k for ld in spec.get('loads') or [] for k in LOAD_KINDS if k in ld}
    bcs = _bc_kinds(spec.get('bcs'))
    lv = np.concatenate([[float(k in loads) for k in LOAD_KINDS], [0.7 * float(k in bcs) for k in BC_KINDS]])
    if lv.any():
        blocks['loading'] = lv

    mp = spec.get('mesh_params') or {}
    order = int(mp.get('order', spec.get('element_order', 1)) or 1)
    dv = [_onehot(order, (1, 2)) * 0.7]
    if n_dof:
        dv.append(_rbf(_log10(n_dof), 2, 7, 11, 0.3))
    blocks['discretization'] = np.concatenate(dv)
    return {'blocks': blocks, 'geometry_id': _geometry_identity(spec), 'material_id': material_id,
            'material_family': fam, 'model_group': group, 'version': EMBEDDING_VERSION}


def _cos(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.shape != b.shape:
        n = max(len(a), len(b))
        a, b = np.pad(a, (0, n - len(a))), np.pad(b, (0, n - len(b)))
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return None
    return float(max(0.0, a @ b / (na * nb)))


def block_similarity(a: dict, b: dict) -> dict:
    """Per-block similarity in [0, 1] (blocks missing in either study are omitted)."""
    out = {}
    if a.get('geometry_id') and a.get('geometry_id') == b.get('geometry_id'):
        out['geometry'] = 1.0
    else:
        ga, gb = a['blocks'].get('geometry'), b['blocks'].get('geometry')
        g = _cos(ga, gb) if ga is not None and gb is not None else None
        out['geometry'] = 0.8 * g if g is not None else 0.0
    if a.get('material_id') and a.get('material_id') == b.get('material_id'):
        out['material'] = 1.0
    for k in ('material', 'physics', 'loading', 'discretization'):
        if k in out:
            continue
        va, vb = a['blocks'].get(k), b['blocks'].get(k)
        both_family = 'family' in a['blocks'] and 'family' in b['blocks']
        if k == 'material' and va is not None and vb is not None and both_family:
            va, vb = np.concatenate([va, a['blocks']['family']]), np.concatenate([vb, b['blocks']['family']])
        if va is None or vb is None:
            continue
        c = _cos(va, vb)
        if c is not None:
            out[k] = c
    return out


def study_similarity(a: dict, b: dict) -> tuple[float, dict]:
    """Weighted mean of the block similarities and the breakdown."""
    parts = block_similarity(a, b)
    w = sum(WEIGHTS[k] for k in parts)
    s = sum(WEIGHTS[k] * v for k, v in parts.items()) / w if w else 0.0
    if parts.get('physics', 1.0) < 0.6:           # different physics (solid vs fluid, thermal…): never close
        s = min(s, 0.45)
    return s, {k: round(v, 3) for k, v in parts.items()}
