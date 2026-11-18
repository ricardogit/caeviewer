"""Import the CAPP material catalog (CAPP database, table ``materials``) — read only.

    flask materials import-capp [--url postgresql://…/cappdb | --csv materials.csv] [--prune]

CAPP is never written to: the connection is a read-only session and the only statement is a SELECT on
``materials`` (a CSV made with ``COPY (SELECT * FROM materials) TO STDOUT CSV HEADER`` works the same).

CAPP units (its model): modulus_elasticity GPa, density g/cm³, tensile/yield MPa, elongation %, thermal_conductivity
W/(m·K), specific_heat J/(kg·K), thermal_expansion µm/(m·K). CAPP is a machining catalog and usually lacks the
elastic / thermal constants a simulation needs: E, ν, k, α, cp missing in CAPP are **completed from the equivalent
seed-catalog material** (matched by alloy / grade in the code and name, ``match_seed``); what came from where is
stored (``calibration.capp.filled_from_catalog``) and shown in the reference. Rows still without E or ν are
reported and not imported. Rows become ``source = 'capp'``, ``seed_key = 'capp:<code>'``: read-only in CAE Viewer
(edit them in CAPP and import again; the import is an idempotent upsert).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re

from app.design.services.material.seed_data import CV, MATERIALS, entry_parameters

CAPP_COLUMNS = ('code', 'name', 'description', 'category', 'grade', 'standard', 'standard_number',
                'tensile_strength', 'yield_strength', 'elongation', 'modulus_elasticity', 'poissons_ratio',
                'thermal_conductivity', 'specific_heat', 'thermal_expansion', 'density', 'is_active')
# CAPP column → (library key, factor to SI)
CAPP_PROPS = {'modulus_elasticity': ('E', 1e9), 'poissons_ratio': ('nu', 1), 'density': ('rho', 1e3),
              'yield_strength': ('sigma_y', 1e6), 'tensile_strength': ('sigma_u', 1e6),
              'elongation': ('elongation', 1e-2), 'thermal_conductivity': ('k', 1),
              'thermal_expansion': ('alpha', 1e-6), 'specific_heat': ('cp', 1)}
# completed from the catalog when CAPP has no value
FILL_FROM_CATALOG = ('E', 'nu', 'k', 'alpha', 'cp', 'rho', 'sigma_y', 'sigma_u', 'elongation')
CATEGORY_ES = {'aluminum': 'Aluminio', 'aluminium': 'Aluminio', 'steel': 'Acero', 'carbon steel': 'Acero',
               'alloy steel': 'Acero', 'stainless': 'Acero inoxidable', 'stainless steel': 'Acero inoxidable',
               'titanium': 'Titanio', 'copper': 'Cobre', 'brass': 'Cobre', 'bronze': 'Cobre',
               'magnesium': 'Magnesio', 'nickel': 'Níquel', 'superalloy': 'Níquel', 'cast iron': 'Fundición',
               'plastic': 'Polímero', 'polymer': 'Polímero', 'plastics': 'Polímero'}

_D = r'(?<![0-9])'
_DE = r'(?![0-9])'
_L = r'(?<![a-z])'
_LE = r'(?![a-z])'
# (regex on "code name grade standard_number" lower-case, seed key); first match wins (specific before generic)
SEED_RULES = [
    (_D + r'17-?4\s*ph', 'ss_17_4ph_h1025'),
    (_D + r'316l?' + _LE, 'aisi_316l'), (_D + r'304l?' + _LE, 'aisi_304'), (_D + '410' + _DE, 'aisi_410'),
    (_D + '6061' + _DE, 'al_6061_t6'), (_D + '6063' + _DE, 'al_6063_t5'), (_D + '7075' + _DE, 'al_7075_t6'),
    (_D + '2024' + _DE, 'al_2024_t3'), (_D + '5083' + _DE, 'al_5083_o'), (_L + r'a?356' + _DE, 'al_a356_t6'),
    (_D + '1018' + _DE, 'aisi_1018'), (_D + '1045' + _DE, 'aisi_1045'), (_D + '4140' + _DE, 'aisi_4140'),
    (_D + '4340' + _DE, 'aisi_4340'), (_L + r'a36' + _DE, 'astm_a36'), (_L + r's235', 's235jr'),
    (_L + r's355', 's355jr'),
    (r'ti-?64' + _DE + '|' + _D + r'6al-?4v', 'ti_6al_4v'), (r'(grade|gr\.?)\s*2' + _DE, 'ti_cp_gr2'),
    (_D + '718' + _DE, 'inconel_718'), (_L + r'c?11000' + _DE, 'cu_c11000'), (_L + r'c?360(00)?' + _DE, 'cu_c36000'),
    (_L + r'az31', 'mg_az31b_h24'),
    (_L + r'(gr[ae]y (cast )?iron|cast iron \(gr[ae]y\)|ci-gr[ae]y|gjl|fundici[oó]n gris)', 'en_gjl_250'),
    (_L + r'(ductile|nodular|gjs)', 'en_gjs_400_15'),
    (_L + 'peek' + _LE, 'peek'), (_L + 'petg' + _LE, 'petg'), (_L + 'pla' + _LE, 'pla'), (_L + 'abs' + _LE, 'abs'),
    (_L + r'(pom|acetal|delrin)' + _LE, 'pom_h'), (_L + r'(pa6|pa 6|nylon 6)' + _DE, 'pa6_dry'),
    (_L + 'hdpe' + _LE, 'hdpe'), (_L + r'(polycarbonate|policarbonato)' + _LE, 'pc'),
    (_L + r'(polypropylene|polipropileno)' + _LE, 'pp_h'),
]
_SEED = {m[0]: m for m in MATERIALS}


class CappImportError(ValueError):
    pass


def match_seed(row: dict) -> str | None:
    """Seed key of the equivalent catalog material: by code / name / grade first, else by the standard number
    (CAPP's 1020 declares ASTM A36 → A36, whose E, ν, k, α, cp are those of a plain carbon steel)."""
    for cols in (('code', 'name', 'grade'), ('standard_number',)):
        text = ' '.join(str(row.get(k) or '') for k in cols).lower()
        for pattern, key in SEED_RULES:
            if re.search(pattern, text):
                return key
    return None


def _num(v):
    if v in (None, ''):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def read_capp(url: str | None = None, csv_path: str | None = None) -> list[dict]:
    """CAPP ``materials`` rows (only the columns used here). Read-only session; CAPP is never modified."""
    if csv_path:
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        if rows and 'code' not in rows[0]:
            raise CappImportError('El CSV no parece la tabla materials de CAPP (falta la columna code).')
        return [{k: r.get(k) for k in CAPP_COLUMNS} for r in rows]
    if not url:
        raise CappImportError('Indique --url de la base de CAPP (o CAPP_DATABASE_URL) o --csv.')
    import psycopg2
    conn = psycopg2.connect(url.replace('postgresql+psycopg2://', 'postgresql://'), connect_timeout=10)
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute('SELECT ' + ', '.join(CAPP_COLUMNS) + ' FROM materials ORDER BY code')
            out = [dict(zip(CAPP_COLUMNS, r)) for r in cur.fetchall()]
        conn.rollback()
    finally:
        conn.close()
    return out


def _active(v) -> bool:
    return v is None or v is True or str(v).strip().lower() in ('t', 'true', '1', 'yes', '')


def capp_entry(row: dict) -> dict:
    """Library entry for one CAPP row: {seed_key, name, category, source_ref, description, parameters, info,
    errors}."""
    code = str(row.get('code') or '').strip()
    params, from_capp = {}, []
    for col, (key, f) in CAPP_PROPS.items():
        x = _num(row.get(col))
        if x is not None and x > 0:
            params[key] = float(f'{x * f:.12g}')
            from_capp.append(key)
    seed_key = match_seed(row)
    seed = _SEED.get(seed_key)
    filled = []
    cv = CV['metal']
    if seed:
        sp = entry_parameters(seed)
        cv = CV[seed[3]]
        for k in FILL_FROM_CATALOG:
            if k not in params and k in sp:
                params[k] = sp[k]['value']
                filled.append(k)
    group = {'E': 'E', 'nu': 'nu', 'rho': 'rho', 'sigma_y': 'strength', 'sigma_u': 'strength',
             'elongation': 'elong', 'k': 'thermal', 'alpha': 'thermal', 'cp': 'thermal'}
    parameters = {k: {'value': v, 'std': float(f'{abs(v) * cv[group[k]]:.4g}')} for k, v in params.items()}
    errors = []
    if not code:
        errors.append('Sin código.')
    for k, lbl in (('E', 'E'), ('nu', 'ν')):
        if k not in parameters:
            errors.append(f'Sin {lbl} en CAPP' + ('' if seed else ' y sin material equivalente en el catálogo') + '.')
    std = ' '.join(str(row.get(k) or '').strip() for k in ('standard', 'standard_number')).strip()
    ref = f'CAPP {code}' + (f' ({std})' if std else '')
    if filled:
        ref += f' · {", ".join(filled)} del catálogo: {seed[1]}'
    cat_raw = str(row.get('category') or '').strip().replace('_', ' ')
    desc = str(row.get('description') or '').strip()
    note = ('Importado de CAPP (solo lectura: edítelo en CAPP y vuelva a importar).'
            + (f' Completado con valores típicos de «{seed[1]}»: {", ".join(filled)}.' if filled else ''))
    return {'seed_key': f'capp:{code}', 'name': str(row.get('name') or code).strip(),
            'category': CATEGORY_ES.get(cat_raw.lower(), cat_raw or None), 'source_ref': ref,
            'description': (desc + ' — ' if desc else '') + note, 'parameters': parameters,
            'info': {'code': code, 'catalog_key': seed_key, 'from_capp': from_capp, 'filled_from_catalog': filled},
            'errors': errors}


def _hash(e: dict) -> str:
    keep = {k: e[k] for k in ('name', 'category', 'source_ref', 'description', 'parameters')}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:16]


def import_capp(db, rows: list[dict], prune: bool = False) -> dict:
    """Upsert CAPP rows by seed_key 'capp:<code>'. Returns counts + per-row report."""
    from app.design.models.material import MaterialModel
    existing = {r.seed_key: r for r in MaterialModel.query.filter(MaterialModel.seed_key.like('capp:%')).all()}
    res = {'read': len(rows), 'created': 0, 'updated': 0, 'unchanged': 0, 'disabled': 0, 'rejected': [], 'rows': []}
    keys = set()
    for row in rows:
        if not _active(row.get('is_active')):
            continue
        e = capp_entry(row)
        if e['errors']:
            res['rejected'].append({'code': e['info']['code'], 'name': e['name'], 'errors': e['errors']})
            continue
        keys.add(e['seed_key'])
        h = _hash(e)
        cal = {'capp': {**e['info'], 'hash': h}}
        m = existing.get(e['seed_key'])
        fields = {k: e[k] for k in ('name', 'category', 'source_ref', 'description', 'parameters')}
        if m is None:
            m = MaterialModel(model_type='linear_elastic_isotropic', source='capp', seed_key=e['seed_key'],
                              is_active=True, calibration=cal, **fields)
            db.session.add(m)
            res['created'] += 1
        elif (m.calibration or {}).get('capp', {}).get('hash') == h and m.is_active:
            res['unchanged'] += 1
        else:
            for k, v in fields.items():
                setattr(m, k, v)
            m.calibration, m.is_active, m.source = cal, True, 'capp'
            res['updated'] += 1
        res['rows'].append({'code': e['info']['code'], 'name': e['name'], 'catalog': e['info']['catalog_key'],
                            'filled': e['info']['filled_from_catalog']})
    if prune:
        for key, m in existing.items():
            if key not in keys and m.is_active:
                m.is_active = False
                res['disabled'] += 1
    db.session.commit()
    return res
