"""Import user materials from a CSV or Excel table (one material per row).

Columns are recognised by header (Spanish or English, case/accents ignored); the unit may be given in the header
(``E [GPa]``, ``Densidad (g/cm3)``, ``alpha ppm/K``). Without a unit the value range decides (and a note says so):
E < 2000 → GPa, < 2e6 → MPa, else Pa; strengths < 2e5 → MPa; ρ < 30 → g/cm³; α > 1e-3 → µm/(m·K);
elongation > 1 → %. A ``<prop> std`` / ``± <prop>`` / ``desv <prop>`` column gives the standard deviation (same
unit as the value). Required per row: name, E and ν. Everything is converted to SI (the library's units).

    parse_material_table(data: bytes, filename) -> {'columns', 'rows', 'notes'}
    TEMPLATE_HEADERS / template_csv()
"""
from __future__ import annotations

import csv
import io
import math
import re
import unicodedata

MAX_ROWS = 2000

# property → (header aliases, unit kind)
PROPS = {
    'E':          (('e', 'young', 'modulo de young', 'modulo elastico', 'modulo de elasticidad', 'elastic modulus',
                    'youngs modulus', 'modulus'), 'modulus'),
    'nu':         (('nu', 'poisson', 'coeficiente de poisson', 'poisson ratio', 'v'), 'none'),
    'rho':        (('rho', 'densidad', 'density'), 'density'),
    'sigma_y':    (('sigma_y', 'sy', 'fy', 'rp02', 'rp0.2', 'limite elastico', 'yield', 'yield strength',
                    'fluencia', 'limite de fluencia', 're'), 'stress'),
    'sigma_u':    (('sigma_u', 'su', 'fu', 'rm', 'uts', 'resistencia a traccion', 'resistencia ultima',
                    'tensile strength', 'ultimate tensile strength', 'ultimate strength', 'resistencia'), 'stress'),
    'sigma_c':    (('sigma_c', 'fc', 'resistencia a compresion', 'compressive strength'), 'stress'),
    'elongation': (('elongation', 'alargamiento', 'elongacion', 'a%', 'a', 'deformacion a rotura',
                    'elongation at break'), 'fraction'),
    'k':          (('k', 'lambda', 'conductividad', 'conductividad termica', 'thermal conductivity', 'conductivity'),
                   'conductivity'),
    'alpha':      (('alpha', 'cte', 'dilatacion', 'coeficiente de dilatacion', 'dilatacion termica',
                    'thermal expansion', 'coefficient of thermal expansion', 'expansion'), 'expansion'),
    'cp':         (('cp', 'c', 'calor especifico', 'specific heat', 'capacidad calorifica'), 'specific_heat'),
}
TEXT = {
    'name':        ('nombre', 'name', 'material', 'designacion', 'designation'),
    'category':    ('categoria', 'category', 'familia', 'family', 'tipo', 'type', 'grupo', 'group'),
    'description': ('descripcion', 'description', 'notas', 'notes', 'comentario', 'comentarios', 'condicion',
                    'condition', 'estado'),
    'source_ref':  ('fuente', 'source', 'referencia', 'reference', 'norma', 'standard', 'ref'),
}
STD_WORDS = ('std', 'desv', 'desviacion', 'sd', 'sigma std', '±', '+-', 'stdev', 'incertidumbre', 'uncertainty')

# unit kind → {unit token: factor to SI}
UNITS = {
    'modulus': {'pa': 1, 'kpa': 1e3, 'mpa': 1e6, 'gpa': 1e9, 'n/mm2': 1e6, 'psi': 6894.757, 'ksi': 6.894757e6,
                'msi': 6.894757e9},
    'stress': {'pa': 1, 'kpa': 1e3, 'mpa': 1e6, 'gpa': 1e9, 'n/mm2': 1e6, 'psi': 6894.757, 'ksi': 6.894757e6},
    'density': {'kg/m3': 1, 'g/cm3': 1e3, 'g/cc': 1e3, 'g/ml': 1e3, 'kg/dm3': 1e3, 't/m3': 1e3,
                'lb/in3': 27679.9, 'lb/ft3': 16.0185},
    'fraction': {'%': 1e-2, 'mm/mm': 1, 'm/m': 1, '-': 1},
    'conductivity': {'w/mk': 1, 'w/m-k': 1, 'w/(mk)': 1, 'w/m/k': 1, 'w/m°c': 1, 'w/mc': 1,
                     'btu/hftf': 1.730735},
    'expansion': {'1/k': 1, '1/°c': 1, '1/c': 1, 'k-1': 1, '/k': 1, '/°c': 1, 'um/mk': 1e-6, 'µm/mk': 1e-6,
                  'μm/mk': 1e-6, 'um/m°c': 1e-6, 'µm/m°c': 1e-6, 'ppm/k': 1e-6, 'ppm/°c': 1e-6, 'ppm': 1e-6,
                  '1e-6/k': 1e-6, '10-6/k': 1e-6, 'x10-6/k': 1e-6, 'e-6/k': 1e-6},
    'specific_heat': {'j/kgk': 1, 'j/kg-k': 1, 'j/(kgk)': 1, 'j/kg/k': 1, 'j/kg°c': 1, 'kj/kgk': 1e3,
                      'kj/kg-k': 1e3, 'j/gk': 1e3, 'j/g°c': 1e3, 'cal/g°c': 4184, 'btu/lbf': 4186.8},
    'none': {'-': 1, '': 1},
}
SI_UNIT = {'modulus': 'Pa', 'stress': 'Pa', 'density': 'kg/m³', 'fraction': '-', 'conductivity': 'W/(m·K)',
           'expansion': '1/K', 'specific_heat': 'J/(kg·K)', 'none': '-'}

TEMPLATE_HEADERS = ['Nombre', 'Categoría', 'E [GPa]', 'E std [GPa]', 'nu', 'Densidad [kg/m3]', 'sigma_y [MPa]',
                    'sigma_u [MPa]', 'Alargamiento [%]', 'k [W/mK]', 'alpha [µm/mK]', 'cp [J/kgK]', 'Fuente',
                    'Descripción']
TEMPLATE_EXAMPLE = ['Acero 1020 proveedor X', 'Acero', '205', '4', '0.29', '7870', '350', '420', '15', '51.9',
                    '11.7', '486', 'Certificado lote 1234', 'Barra estirada en frío']


class MaterialImportError(ValueError):
    pass


def _norm(s) -> str:
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode() if s is not None else ''
    return re.sub(r'\s+', ' ', s.strip().lower())


def _unit_key(u: str) -> str:
    u = str(u or '').strip().lower().replace('·', '').replace('*', '').replace(' ', '').replace('³', '3') \
        .replace('²', '2').replace('⁻¹', '-1').replace('⁻⁶', '-6').replace('−', '-').replace('kelvin', 'k')
    return u.replace('mk', 'mk')


def _split_header(raw: str):
    """'E [GPa]' → ('e', 'gpa'); 'alpha (1e-6/K)' → ('alpha', '1e-6/k'); 'Densidad g/cm3' → ('densidad', 'g/cm3')."""
    s = str(raw or '').strip()
    unit = ''
    m = re.search(r'[\[(]([^\])]*)[\])]\s*$', s)
    if m:
        unit, s = m.group(1), s[:m.start()]
    name = _norm(s)
    if not unit:                               # trailing unit word: 'E GPa', 'k W/mK'
        parts = s.rsplit(' ', 1)
        if len(parts) == 2:
            cand = _unit_key(parts[1])
            if any(cand in table for table in UNITS.values() if cand not in ('', '-')):
                unit, name = parts[1], _norm(parts[0])
    return name, _unit_key(unit)


def _match_header(name: str):
    """(kind, key, is_std) for a normalised header name, or None."""
    is_std = False
    for w in STD_WORDS:
        w2 = _norm(w) if w not in ('±', '+-') else w
        if name.startswith(w2 + ' ') or name.endswith(' ' + w2) or name.startswith(w2) and w in ('±', '+-'):
            is_std = True
            name = (name[len(w2):] if name.startswith(w2) else name[:-len(w2)]).strip(' _-')
            break
    m = re.match(r'^(.*?)[ _](std|sd|desv)$', name)
    if m:
        is_std, name = True, m.group(1)
    m = re.match(r'^(desv(?:iacion)?(?: estandar)?|std) (?:de |del )?(.*)$', name)
    if m:
        is_std, name = True, m.group(2)
    name = name.strip(' _-')
    for key, (aliases, _) in PROPS.items():
        if name in aliases or name.replace(' ', '_') in aliases or name.replace('_', ' ') in aliases:
            return 'prop', key, is_std
    if not is_std:
        for key, aliases in TEXT.items():
            if name in aliases:
                return 'text', key, False
    return None


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(float(v)) else None
    s = str(v).strip().replace(' ', '').replace(' ', '')
    if s in ('', '-', '—', 'n/a', 'na', 'nd', 'n.d.'):
        return None
    if ',' in s and '.' not in s:
        s = s.replace(',', '.')
    elif ',' in s and '.' in s:                 # 1.234,5 or 1,234.5
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    s = s.replace('%', '')
    try:
        return float(s)
    except ValueError:
        raise ValueError(f'«{v}» no es un número')


def _read_rows(data: bytes, filename: str) -> list[list]:
    ext = (filename or '').lower().rsplit('.', 1)[-1]
    if ext in ('xlsx', 'xlsm'):
        try:
            import openpyxl
        except ImportError:                                    # pragma: no cover
            raise MaterialImportError('Lectura de Excel no disponible (falta openpyxl): exporte la hoja a CSV.')
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise MaterialImportError(f'No se pudo leer el Excel: {e}')
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    if ext == 'xls':
        raise MaterialImportError('Formato .xls antiguo no soportado: guárdelo como .xlsx o CSV.')
    text = None
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise MaterialImportError('Archivo vacío.')
    sample = '\n'.join(lines[:30])
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
    except csv.Error:
        delim = max(';,\t|', key=sample.count)
    return list(csv.reader(lines, delimiter=delim))


def _auto_factor(kind: str, values: list[float]):
    """(factor, unit label) guessed from the magnitude of a column without unit."""
    vals = [abs(v) for v in values if v is not None and v != 0]
    if not vals:
        return 1.0, SI_UNIT[kind]
    med = sorted(vals)[len(vals) // 2]
    if kind == 'modulus':
        return (1e9, 'GPa') if med < 2000 else (1e6, 'MPa') if med < 2e6 else (1.0, 'Pa')
    if kind == 'stress':
        return (1e6, 'MPa') if med < 2e5 else (1.0, 'Pa')
    if kind == 'density':
        return (1e3, 'g/cm³') if med < 30 else (1.0, 'kg/m³')
    if kind == 'expansion':
        return (1e-6, 'µm/(m·K)') if med > 1e-3 else (1.0, '1/K')
    if kind == 'fraction':
        return (1e-2, '%') if max(vals) > 1 else (1.0, 'fracción')
    if kind == 'specific_heat':
        return (1e3, 'kJ/(kg·K)') if med < 10 else (1.0, 'J/(kg·K)')
    return 1.0, SI_UNIT[kind]


def parse_material_table(data: bytes, filename: str) -> dict:
    rows = [r for r in _read_rows(data, filename) if any(c not in (None, '') and str(c).strip() for c in r)]
    if not rows:
        raise MaterialImportError('Archivo vacío.')
    # header = first row with a recognised name column and at least one property
    hi, mapping = None, None
    for i, r in enumerate(rows[:10]):
        cols = {}
        for j, h in enumerate(r):
            if h is None or str(h).strip() == '':
                continue
            name, unit = _split_header(h)
            m = _match_header(name)
            if m:
                cols[j] = (*m, unit, str(h).strip())
        if any(c[0] == 'text' and c[1] == 'name' for c in cols.values()) and any(c[0] == 'prop' for c in cols.values()):
            hi, mapping = i, cols
            break
    if hi is None:
        raise MaterialImportError('No se encontró la fila de encabezados: necesita una columna «Nombre» y al menos '
                                  'una propiedad (E, nu, densidad …). Descargue la plantilla.')
    body = rows[hi + 1:]
    if len(body) > MAX_ROWS:
        raise MaterialImportError(f'Demasiadas filas ({len(body)}); máximo {MAX_ROWS}.')
    notes, columns = [], []
    factors, parsed, seen = {}, {}, set()
    # value columns first: a std column without unit takes the unit of its value column
    for j, (kind, key, is_std, unit, raw) in sorted(mapping.items(), key=lambda it: (it[1][2], it[0])):
        if (kind, key, is_std) in seen:
            notes.append(f'Columna «{raw}» ignorada (repetida).')
            continue
        seen.add((kind, key, is_std))
        if kind == 'text':
            parsed[j] = ('text', key)
            columns.append({'column': raw, 'property': key})
            continue
        ukind = PROPS[key][1]
        if unit and unit != '-':
            f = UNITS[ukind].get(unit)
            if f is None:
                raise MaterialImportError(f'Unidad «{unit}» de la columna «{raw}» no reconocida.')
            label = unit
        elif is_std and key in factors:
            f, label = factors[key]
        else:
            vals = []
            for r in body:
                try:
                    vals.append(_num(r[j]) if j < len(r) else None)
                except ValueError:
                    pass
            f, label = _auto_factor(ukind, vals)
            if ukind != 'none':
                notes.append(f'«{raw}» sin unidad: se interpreta en {label}.')
        if not is_std:
            factors[key] = (f, label)
        parsed[j] = ('prop', key, is_std, f, raw)
        columns.append({'column': raw, 'property': key + ('_std' if is_std else ''), 'unit': label,
                        'si_unit': SI_UNIT[ukind]})
    out = []
    for n, r in enumerate(body, start=hi + 2):
        rec = {'row': n, 'name': '', 'category': None, 'description': None, 'source_ref': None,
               'parameters': {}, 'errors': [], 'warnings': []}
        stds = {}
        for j, c in parsed.items():
            if j >= len(r):
                continue
            v = r[j]
            if c[0] == 'text':
                if v not in (None, '') and str(v).strip():
                    rec[c[1]] = str(v).strip()
                continue
            kind, key, is_std, f, raw = c
            try:
                x = _num(v)
            except ValueError as e:
                rec['errors'].append(f'{raw}: {e}')
                continue
            if x is None:
                continue
            if is_std:
                stds[key] = float(f'{abs(x * f):.12g}')
            else:
                rec['parameters'][key] = {'value': float(f'{x * f:.12g}'), 'std': 0.0}
        for k, s in stds.items():
            if k in rec['parameters']:
                rec['parameters'][k]['std'] = s
        _validate(rec)
        if not rec['name'] and not rec['parameters'] and not rec['errors']:
            continue                                   # blank line
        out.append(rec)
    if not out:
        raise MaterialImportError('No hay filas de datos bajo los encabezados.')
    return {'columns': columns, 'rows': out, 'notes': notes}


def _validate(rec: dict):
    p, err, warn = rec['parameters'], rec['errors'], rec['warnings']
    if not rec['name']:
        err.append('Falta el nombre.')
    for k in ('E', 'nu'):
        if k not in p:
            err.append(f'Falta {"E" if k == "E" else "ν"} (obligatorio).')

    def val(k):
        return p[k]['value'] if k in p else None
    if val('E') is not None and not (1e4 <= val('E') <= 2e12):
        err.append(f'E = {val("E"):.3g} Pa fuera de rango (revise la unidad).')
    if val('nu') is not None and not (-1 < val('nu') < 0.5):
        err.append(f'ν = {val("nu")} fuera de rango (−1, 0.5).')
    if val('rho') is not None and not (1 <= val('rho') <= 25000):
        err.append(f'ρ = {val("rho"):.4g} kg/m³ fuera de rango (revise la unidad).')
    for k in ('sigma_y', 'sigma_u', 'sigma_c'):
        if val(k) is not None and not (1e3 <= val(k) <= 2e10):
            err.append(f'{k} = {val(k):.3g} Pa fuera de rango (revise la unidad).')
    if val('sigma_y') and val('sigma_u') and val('sigma_y') > val('sigma_u') * 1.001:
        warn.append('σy mayor que σu.')
    if val('alpha') is not None and not (0 < abs(val('alpha')) < 1e-2):
        err.append(f'α = {val("alpha"):.3g} 1/K fuera de rango (revise la unidad).')
    if val('k') is not None and not (0 < val('k') < 5000):
        err.append(f'k = {val("k"):.4g} W/(m·K) fuera de rango.')
    if val('cp') is not None and not (10 < val('cp') < 20000):
        err.append(f'cp = {val("cp"):.4g} J/(kg·K) fuera de rango (revise la unidad).')
    if val('elongation') is not None and not (0 <= val('elongation') <= 20):
        err.append('Alargamiento fuera de rango.')
    if 'rho' not in p:
        warn.append('Sin densidad: no servirá para cargas de gravedad.')


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(TEMPLATE_HEADERS)
    w.writerow(TEMPLATE_EXAMPLE)
    return buf.getvalue()


def template_xlsx() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Materiales'
    ws.append(TEMPLATE_HEADERS)
    ws.append([_num(v) if re.fullmatch(r'[\d.]+', v) else v for v in TEMPLATE_EXAMPLE])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(12, len(str(col[0].value)) + 2)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
