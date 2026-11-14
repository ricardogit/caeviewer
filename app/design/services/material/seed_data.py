"""Seed material catalog: typical engineering values (mechanical + thermal), upserted by ``seed_key``.

    flask materials seed [--prune]

Values are *typical / nominal* literature values (EN and ASTM minimum-specification tables for structural and
stainless steels, MatWeb / ASM Handbook / manufacturer datasheets for the rest). They are a starting point, not
certified data: replace them with the supplier certificate or your own tensile tests (Material editor → fit) for
anything that matters. Every entry states where its numbers come from (``ref``) and the condition (temper,
heat treatment, dry / conditioned …).

Table units (converted to SI on seeding): E GPa, ρ kg/m³, σy / σu / σc MPa, elongation %, k W/(m·K),
α µm/(m·K), cp J/(kg·K). ``None`` = not applicable (no yield for brittle materials).
The ± std written with each value is a coefficient of variation per category (``CV``): a scatter estimate for
uncertainty studies, not a measured one.

Seeding never overwrites a row the user changed (parameters edited, tensile fit stored) or deleted
(is_active = False): those are reported as ``kept`` / ``skipped``.
"""
from __future__ import annotations

import hashlib
import json

SEED_VERSION = 1

# category → coefficient of variation per property group
CV = {
    'metal':     {'E': 0.03, 'nu': 0.03, 'rho': 0.01, 'strength': 0.07, 'elong': 0.15, 'thermal': 0.05},
    'polymer':   {'E': 0.10, 'nu': 0.05, 'rho': 0.02, 'strength': 0.10, 'elong': 0.30, 'thermal': 0.10},
    'elastomer': {'E': 0.20, 'nu': 0.01, 'rho': 0.03, 'strength': 0.15, 'elong': 0.20, 'thermal': 0.15},
    'brittle':   {'E': 0.05, 'nu': 0.05, 'rho': 0.02, 'strength': 0.15, 'elong': 0.30, 'thermal': 0.10},
}

EN_MIN = 'EN 10025-2 (valores mínimos de norma, espesor ≤ 16 mm); térmicas típicas'
ASTM_SS = 'ASTM A240 (mínimos de norma, recocido); térmicas típicas (ASM)'
MATWEB = 'Valores típicos de literatura (ASM Handbook / MatWeb)'
PLAST = 'Valores típicos de fichas técnicas (inyectado, 23 °C); dependen del grado y del proceso'

# key, name, category, cv group, condition/notes, ref,
#   E, nu, rho, sigma_y, sigma_u, elongation, k, alpha, cp, [extra: sigma_c]
MATERIALS = [
    # ── Aceros al carbono y aleados ──────────────────────────────────────────
    ('s235jr', 'Acero S235JR', 'Acero', 'metal', 'Acero estructural laminado en caliente', EN_MIN,
     210, 0.30, 7850, 235, 360, 26, 50, 12.0, 460),
    ('s355jr', 'Acero S355JR', 'Acero', 'metal', 'Acero estructural laminado en caliente', EN_MIN,
     210, 0.30, 7850, 355, 470, 22, 50, 12.0, 460),
    ('astm_a36', 'Acero ASTM A36', 'Acero', 'metal', 'Acero estructural (perfiles y placa)',
     'ASTM A36 (mínimos de norma; alargamiento en 50 mm); térmicas típicas',
     200, 0.26, 7850, 250, 400, 23, 51.9, 11.7, 486),
    ('aisi_1018', 'Acero AISI 1018 (estirado en frío)', 'Acero', 'metal', 'Estirado en frío', MATWEB,
     205, 0.29, 7870, 370, 440, 15, 51.9, 12.0, 486),
    ('aisi_1045', 'Acero AISI 1045 (estirado en frío)', 'Acero', 'metal', 'Estirado en frío', MATWEB,
     205, 0.29, 7850, 530, 625, 12, 49.8, 11.2, 486),
    ('aisi_4140', 'Acero AISI 4140 (recocido)', 'Acero', 'metal',
     'Recocido; templado y revenido alcanza σy 650–1600 MPa según el revenido', MATWEB,
     205, 0.29, 7850, 415, 655, 25.7, 42.6, 12.2, 473),
    ('aisi_4340', 'Acero AISI 4340 (recocido)', 'Acero', 'metal',
     'Recocido; templado y revenido alcanza σy 700–1600 MPa según el revenido', MATWEB,
     205, 0.29, 7850, 470, 745, 22, 44.5, 12.3, 475),
    # ── Aceros inoxidables ───────────────────────────────────────────────────
    ('aisi_304', 'Acero inoxidable AISI 304', 'Acero inoxidable', 'metal', 'Austenítico, recocido', ASTM_SS,
     193, 0.29, 8000, 205, 515, 40, 16.2, 17.3, 500),
    ('aisi_316l', 'Acero inoxidable AISI 316L', 'Acero inoxidable', 'metal', 'Austenítico, recocido', ASTM_SS,
     193, 0.29, 8000, 170, 485, 40, 16.3, 16.0, 500),
    ('aisi_410', 'Acero inoxidable AISI 410', 'Acero inoxidable', 'metal', 'Martensítico, recocido', ASTM_SS,
     200, 0.28, 7750, 205, 450, 20, 24.9, 9.9, 460),
    ('ss_17_4ph_h1025', 'Acero inoxidable 17-4PH H1025', 'Acero inoxidable', 'metal',
     'Endurecido por precipitación, condición H1025', 'ASTM A564 (mínimos, H1025); térmicas típicas',
     196, 0.27, 7800, 1000, 1070, 12, 18.3, 10.8, 460),
    # ── Fundiciones ──────────────────────────────────────────────────────────
    ('en_gjl_250', 'Fundición gris EN-GJL-250', 'Fundición', 'brittle',
     'Fundición laminar: frágil, sin límite elástico; E depende de la tensión (valor secante)',
     'EN 1561 (resistencia mínima, valores típicos del anexo)',
     110, 0.26, 7200, None, 250, 0.5, 48.5, 11.7, 460),
    ('en_gjs_400_15', 'Fundición nodular EN-GJS-400-15', 'Fundición', 'metal', 'Fundición dúctil ferrítica',
     'EN 1563 (mínimos de norma, valores típicos del anexo)',
     169, 0.275, 7100, 250, 400, 15, 36.2, 12.5, 515),
    # ── Aluminio ─────────────────────────────────────────────────────────────
    ('al_6061_t6', 'Aluminio 6061-T6', 'Aluminio', 'metal', 'Forja, tratado T6', MATWEB,
     68.9, 0.33, 2700, 276, 310, 12, 167, 23.6, 896),
    ('al_6063_t5', 'Aluminio 6063-T5', 'Aluminio', 'metal', 'Perfiles extruidos, T5', MATWEB,
     68.9, 0.33, 2690, 145, 186, 12, 209, 23.4, 900),
    ('al_7075_t6', 'Aluminio 7075-T6', 'Aluminio', 'metal', 'Forja, tratado T6', MATWEB,
     71.7, 0.33, 2810, 503, 572, 11, 130, 23.6, 960),
    ('al_2024_t3', 'Aluminio 2024-T3', 'Aluminio', 'metal', 'Chapa, tratado T3', MATWEB,
     73.1, 0.33, 2780, 345, 483, 18, 121, 23.2, 875),
    ('al_5083_o', 'Aluminio 5083-O', 'Aluminio', 'metal', 'Chapa recocida (naval)', MATWEB,
     70.3, 0.33, 2660, 145, 290, 22, 117, 23.8, 900),
    ('al_a356_t6', 'Aluminio A356.0-T6 (fundido)', 'Aluminio', 'metal', 'Fundición en arena, T6', MATWEB,
     72.4, 0.33, 2685, 165, 228, 3.5, 151, 21.4, 963),
    # ── Titanio, níquel, cobre, magnesio ─────────────────────────────────────
    ('ti_6al_4v', 'Titanio Ti-6Al-4V (grado 5)', 'Titanio', 'metal', 'Recocido', MATWEB,
     113.8, 0.342, 4430, 880, 950, 14, 6.7, 8.6, 526),
    ('ti_cp_gr2', 'Titanio CP grado 2', 'Titanio', 'metal', 'Comercialmente puro, recocido', MATWEB,
     105, 0.37, 4510, 275, 345, 20, 16.4, 8.6, 523),
    ('inconel_718', 'Inconel 718 (envejecido)', 'Níquel', 'metal', 'Solubilizado y envejecido',
     'Valores típicos de fichas técnicas (Special Metals) / ASM',
     200, 0.29, 8190, 1034, 1241, 12, 11.4, 13.0, 435),
    ('cu_c11000', 'Cobre C11000 (ETP, recocido)', 'Cobre', 'metal', 'Cobre electrolítico, recocido', MATWEB,
     115, 0.31, 8890, 69, 220, 50, 388, 17.0, 385),
    ('cu_c36000', 'Latón C36000 (H02)', 'Cobre', 'metal', 'Latón de fácil mecanizado, semiduro', MATWEB,
     97, 0.31, 8500, 310, 385, 25, 115, 20.5, 380),
    ('mg_az31b_h24', 'Magnesio AZ31B-H24', 'Magnesio', 'metal', 'Chapa, H24', MATWEB,
     45, 0.35, 1770, 220, 290, 15, 96, 26.0, 1000),
    # ── Polímeros (σy = fluencia en tracción) ────────────────────────────────
    ('abs', 'ABS', 'Polímero', 'polymer', 'Grado de inyección genérico', PLAST,
     2.3, 0.35, 1050, 40, 44, 25, 0.17, 90, 1400),
    ('pla', 'PLA', 'Polímero', 'polymer',
     'Inyectado; las piezas impresas en 3D son anisótropas y más débiles (30–70 % según orientación y relleno)',
     PLAST, 3.5, 0.36, 1240, 55, 60, 6, 0.13, 68, 1800),
    ('petg', 'PETG', 'Polímero', 'polymer', 'Grado genérico', PLAST,
     2.1, 0.38, 1270, 50, 53, 100, 0.20, 68, 1100),
    ('pa6_dry', 'Poliamida PA6 (seco)', 'Polímero', 'polymer',
     'Seco tal como se moldea; acondicionado (50 % HR) E y σy bajan ~1/3', PLAST,
     3.0, 0.39, 1130, 80, 80, 30, 0.25, 85, 1700),
    ('pom_h', 'POM homopolímero (acetal)', 'Polímero', 'polymer', 'Grado de inyección genérico', PLAST,
     3.1, 0.35, 1420, 70, 70, 30, 0.31, 110, 1470),
    ('peek', 'PEEK', 'Polímero', 'polymer', 'Sin carga', PLAST,
     3.6, 0.40, 1300, 100, 100, 45, 0.25, 47, 1340),
    ('pc', 'Policarbonato (PC)', 'Polímero', 'polymer', 'Grado genérico', PLAST,
     2.35, 0.37, 1200, 62, 65, 110, 0.20, 68, 1200),
    ('hdpe', 'Polietileno HDPE', 'Polímero', 'polymer', 'Grado genérico', PLAST,
     1.0, 0.42, 955, 26, 30, 500, 0.48, 120, 1900),
    ('pp_h', 'Polipropileno PP homopolímero', 'Polímero', 'polymer', 'Grado genérico', PLAST,
     1.5, 0.42, 905, 33, 33, 150, 0.22, 100, 1920),
    ('epoxy', 'Resina epoxi (curada)', 'Polímero', 'polymer', 'Sin carga; frágil, sin fluencia', PLAST,
     3.0, 0.35, 1200, None, 70, 4, 0.20, 60, 1100),
    # ── Elastómeros (E de pequeña deformación; use el modelo Neo-Hookeano) ───
    ('nr_60a', 'Caucho natural (60 Shore A)', 'Elastómero', 'elastomer',
     'E inicial ≈ 3G; casi incompresible (ν 0.49); para grandes deformaciones use Neo-Hookeano', PLAST,
     0.003, 0.49, 1100, None, 20, 500, 0.15, 220, 1900),
    ('silicone_50a', 'Silicona (50 Shore A)', 'Elastómero', 'elastomer',
     'E inicial ≈ 3G; casi incompresible (ν 0.49); para grandes deformaciones use Neo-Hookeano', PLAST,
     0.002, 0.49, 1150, None, 7, 400, 0.20, 300, 1300),
    # ── Cerámicos, vidrio, hormigón (frágiles: σu = tracción / flexión, σc = compresión) ───
    ('concrete_c30_37', 'Hormigón C30/37', 'Hormigón', 'brittle',
     'Ecm y fctm de EN 1992-1-1; σc = fck (característica); térmicas de EN 1992-1-2',
     'EN 1992-1-1 / EN 1992-1-2',
     33, 0.20, 2400, None, 2.9, None, 1.6, 10.0, 900, {'sigma_c': 30}),
    ('glass_soda_lime', 'Vidrio sodocálcico', 'Vidrio', 'brittle',
     'Recocido; σu = resistencia característica a flexión (EN 572)', 'EN 572-1 / valores típicos',
     70, 0.22, 2500, None, 45, None, 1.0, 9.0, 840),
    ('alumina_995', 'Alúmina 99.5 %', 'Cerámico', 'brittle', 'Sinterizada; σu = resistencia a flexión',
     'Valores típicos de fichas técnicas',
     370, 0.22, 3890, None, 380, None, 30, 8.0, 880, {'sigma_c': 2600}),
]

_FIELDS = ('E', 'nu', 'rho', 'sigma_y', 'sigma_u', 'elongation', 'k', 'alpha', 'cp')
# table unit → SI, cv group
_SI = {'E': (1e9, 'E'), 'nu': (1, 'nu'), 'rho': (1, 'rho'), 'sigma_y': (1e6, 'strength'),
       'sigma_u': (1e6, 'strength'), 'sigma_c': (1e6, 'strength'), 'elongation': (1e-2, 'elong'),
       'k': (1, 'thermal'), 'alpha': (1e-6, 'thermal'), 'cp': (1, 'thermal')}


def entry_parameters(entry) -> dict:
    """SI parameters {key: {value, std}} of a MATERIALS row."""
    key, name, cat, group, note, ref, *vals = entry
    extra = vals.pop() if isinstance(vals[-1], dict) else {}
    cv = CV[group]
    out = {}
    for k, v in list(zip(_FIELDS, vals)) + list(extra.items()):
        if v is None:
            continue
        scale, g = _SI[k]
        value = float(v) * scale
        out[k] = {'value': value, 'std': float(f'{abs(value) * cv[g]:.4g}')}
    return out


def _hash(name: str, params: dict) -> str:
    return hashlib.sha256(json.dumps({'name': name, 'parameters': params}, sort_keys=True).encode()).hexdigest()[:16]


def catalog_entries() -> list[dict]:
    out = []
    for e in MATERIALS:
        key, name, cat, group, note, ref = e[:6]
        out.append({'seed_key': key, 'name': name, 'category': cat, 'source_ref': ref,
                    'description': f'{note}. Valores típicos del catálogo semilla: verifique con el certificado '
                                   'del proveedor o un ensayo propio.',
                    'parameters': entry_parameters(e)})
    return out


def is_seed_modified(row) -> bool:
    """True if a catalog row no longer holds the values it was seeded with (edited, fitted, renamed)."""
    cal = row.calibration or {}
    return bool(cal.get('best_model')) or _hash(row.name, row.parameters or {}) != (cal.get('seed') or {}).get('hash')


def seed_materials(db, prune: bool = False) -> dict:
    """Idempotent upsert by seed_key. Rows edited, fitted or deleted by the user are left alone."""
    from app.design.models.material import MaterialModel

    existing = {r.seed_key: r for r in MaterialModel.query.filter(MaterialModel.seed_key.isnot(None)).all()}
    res = {'created': 0, 'updated': 0, 'unchanged': 0, 'kept_modified': [], 'skipped_deleted': [], 'disabled': 0}

    for e in catalog_entries():
        h = _hash(e['name'], e['parameters'])
        row = existing.get(e['seed_key'])
        if row is None:
            db.session.add(MaterialModel(model_type='linear_elastic_isotropic', source='seed', is_active=True,
                                         calibration={'seed': {'version': SEED_VERSION, 'hash': h}}, **e))
            res['created'] += 1
            continue
        if not row.is_active:
            res['skipped_deleted'].append(e['seed_key'])
            continue
        if row.source != 'seed' or is_seed_modified(row):
            res['kept_modified'].append(e['seed_key'])
            continue
        same = (row.category, row.source_ref, row.description, h) == (
            e['category'], e['source_ref'], e['description'], (row.calibration or {})['seed']['hash'])
        if same:
            res['unchanged'] += 1
            continue
        for k, v in e.items():
            setattr(row, k, v)
        row.calibration = {**(row.calibration or {}), 'seed': {'version': SEED_VERSION, 'hash': h}}
        res['updated'] += 1
    if prune:
        keys = {m[0] for m in MATERIALS}
        for key, row in existing.items():
            if key not in keys and row.is_active and row.source == 'seed' and not is_seed_modified(row):
                row.is_active = False
                res['disabled'] += 1
    db.session.commit()
    return res
