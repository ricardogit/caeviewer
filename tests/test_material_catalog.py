"""Seed material catalog: idempotent upsert, SI values, read-only catalog rows, duplicate to edit, node props.

Needs a local PostgreSQL (same scratch DB fixture as test_step_files_api); skipped otherwise.
"""
import pytest

from app.design.services.material.seed_data import MATERIALS, catalog_entries, entry_parameters
from test_step_files_api import app  # noqa: F401  (module-scoped scratch-DB fixture)


def test_table_units_to_si():
    s355 = entry_parameters(next(m for m in MATERIALS if m[0] == 's355jr'))
    assert s355['E']['value'] == 210e9 and s355['sigma_y']['value'] == 355e6
    assert s355['alpha']['value'] == pytest.approx(12e-6) and s355['elongation']['value'] == pytest.approx(0.22)
    assert s355['E']['std'] == pytest.approx(0.03 * 210e9)
    concrete = entry_parameters(next(m for m in MATERIALS if m[0] == 'concrete_c30_37'))
    assert 'sigma_y' not in concrete and concrete['sigma_c']['value'] == 30e6
    keys = [m[0] for m in MATERIALS]
    assert len(keys) == len(set(keys)) == len(catalog_entries())
    for e in catalog_entries():                                   # sanity of every entry
        p = e['parameters']
        assert 0 < p['nu']['value'] < 0.5 and p['E']['value'] > 1e6 and 800 < p['rho']['value'] < 9000
        assert 'sigma_u' in p and 'k' in p and 'alpha' in p and e['source_ref']


def test_seed_is_idempotent_and_catalog_is_read_only(app):  # noqa: F811
    from app.extensions import db
    from app.design.models.material import MaterialModel
    from app.design.services.material.seed_data import seed_materials
    with app.app_context():
        r1 = seed_materials(db)
        assert r1['created'] == len(MATERIALS)
        r2 = seed_materials(db)
        assert r2['created'] == 0 and r2['unchanged'] == len(MATERIALS)
        sid = str(MaterialModel.query.filter_by(seed_key='al_6061_t6').one().id)
    c = app.test_client()
    lst = c.get('/api/design/material/').get_json()['materials']
    al = next(m for m in lst if m['id'] == sid)
    assert al['source'] == 'seed' and al['category'] == 'Aluminio'
    # read-only: edit, fit and delete refused
    assert c.put(f'/api/design/material/{sid}', json={'name': 'x'}).status_code == 409
    assert c.delete(f'/api/design/material/{sid}').status_code == 409
    assert c.post(f'/api/design/material/{sid}/fit', json={'datasets': []}).status_code == 409
    # duplicate → editable user copy, fully CRUD
    cp = c.post(f'/api/design/material/{sid}/duplicate', json={}).get_json()
    assert cp['source'] == 'user' and cp['name'] == 'Aluminio 6061-T6 (copia)' and cp['seed_key'] is None
    assert cp['parameters']['E']['value'] == pytest.approx(68.9e9)
    r = c.put(f"/api/design/material/{cp['id']}", json={'parameters': {**cp['parameters'], 'E': {'value': 70e9}}})
    assert r.status_code == 200 and r.get_json()['parameters']['E']['value'] == 70e9
    assert c.delete(f"/api/design/material/{cp['id']}").status_code == 200
    # the catalog row is untouched and the seed still sees it unchanged
    with app.app_context():
        assert seed_materials(db)['unchanged'] == len(MATERIALS)


def test_node_props_carry_thermal_and_drop_stale_yield(app):  # noqa: F811
    from app.design.models.material import MaterialModel
    from app.design.api.material_routes import node_props_from_material
    from app.design.services.material.seed_data import seed_materials
    from app.extensions import db
    with app.app_context():
        seed_materials(db)
        steel = MaterialModel.query.filter_by(seed_key='s235jr').one()
        props = node_props_from_material(steel, {'model_type': 'thermoelastic'})
        assert props['model_type'] == 'thermoelastic' and props['k'] == 50 and props['alpha'] == pytest.approx(12e-6)
        assert props['yield_strength'] == 235e6
        glass = MaterialModel.query.filter_by(seed_key='glass_soda_lime').one()
        props = node_props_from_material(glass, props)
        assert 'yield_strength' not in props and props['E'] == 70e9


# ── CSV / Excel import ────────────────────────────────────────────────────────

CSV_ES = """Material;Familia;Módulo de Young (MPa);Poisson;Densidad g/cm3;Límite elástico;UTS [ksi];Dilatación;desv E
Mi aluminio;Aluminio;69000;0,33;2,70;270;45;23,6;1500
Sin E;;;0,3;7,8;;;;
Malo;Acero;210000;0,6;7,85;abc;;;
"""


def test_parse_units_aliases_and_row_errors():
    from app.design.services.material.importer import parse_material_table
    r = parse_material_table(CSV_ES.encode('cp1252'), 'm.csv')
    al, no_e, bad = r['rows']
    p = al['parameters']
    assert p['E']['value'] == 69e9 and p['E']['std'] == 1.5e9          # std column takes the value's unit
    assert p['nu']['value'] == 0.33 and p['rho']['value'] == 2700       # decimal comma, g/cm³
    assert p['sigma_y']['value'] == 270e6 and p['sigma_u']['value'] == pytest.approx(45 * 6.894757e6)
    assert p['alpha']['value'] == pytest.approx(23.6e-6) and al['category'] == 'Aluminio' and not al['errors']
    assert any('sin unidad' in n for n in r['notes'])
    assert 'Falta E (obligatorio).' in no_e['errors']
    assert any('ν' in e for e in bad['errors']) and any('abc' in e for e in bad['errors'])


def test_parse_template_csv_and_xlsx():
    from app.design.services.material.importer import parse_material_table, template_csv, template_xlsx
    for data, name in ((template_csv().encode(), 't.csv'), (template_xlsx(), 't.xlsx')):
        (row,) = parse_material_table(data, name)['rows']
        assert not row['errors'] and row['parameters']['E']['value'] == 205e9
        assert row['parameters']['alpha']['value'] == pytest.approx(11.7e-6)
        assert row['parameters']['elongation']['value'] == pytest.approx(0.15) and row['source_ref']


def test_parse_rejects_files_without_header():
    from app.design.services.material.importer import MaterialImportError, parse_material_table
    with pytest.raises(MaterialImportError):
        parse_material_table(b'1;2;3\n4;5;6\n', 'x.csv')
    with pytest.raises(MaterialImportError):
        parse_material_table(b'Nombre;E [Mbar]\nA;1\n', 'x.csv')        # unknown unit


def test_import_api_preview_create_skip_update(app):  # noqa: F811
    import io
    c = app.test_client()

    def post(url, text, mode='skip'):
        return c.post(url, data={'file': (io.BytesIO(text.encode('utf-8')), 'mats.csv'), 'on_duplicate': mode},
                      content_type='multipart/form-data')
    pre = post('/api/design/material/import/preview', CSV_ES).get_json()
    assert pre['counts'] == {'create': 1, 'update': 0, 'skip': 0, 'error': 2}
    n0 = len(c.get('/api/design/material/').get_json()['materials'])
    res = post('/api/design/material/import', CSV_ES).get_json()
    assert len(res['material_ids']) == 1
    mats = c.get('/api/design/material/').get_json()['materials']
    assert len(mats) == n0 + 1
    m = next(x for x in mats if x['name'] == 'Mi aluminio')
    assert m['source'] == 'import' and m['source_ref'] == 'Importado de mats.csv' and m['category'] == 'Aluminio'
    again = post('/api/design/material/import', CSV_ES).get_json()        # skip existing
    assert again['counts']['skip'] == 1 and again['material_ids'] == []
    upd = post('/api/design/material/import', CSV_ES.replace('69000', '70000'), 'update').get_json()
    assert upd['counts']['update'] == 1
    assert c.get(f"/api/design/material/{m['id']}").get_json()['parameters']['E']['value'] == 70e9
    # a catalog name in the file creates a user copy, the catalog row is never touched
    cat = post('/api/design/material/import', 'Nombre;E [GPa];nu\nAcero S355JR;1;0.3\n', 'update').get_json()
    assert cat['counts']['create'] == 1
    t = c.get('/api/design/material/import/template?format=xlsx')
    assert t.status_code == 200 and t.data[:2] == b'PK'
