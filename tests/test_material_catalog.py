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
