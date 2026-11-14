"""STEP file list: files sitting in the upload folder without a Part row get registered (real UUID),
and the viewer routes answer 404 — not a Postgres 500 — to ids that are not UUIDs.

Needs a local PostgreSQL (TEST_DATABASE_URL, default caedb_test, created if missing); skipped otherwise.
"""
import uuid

import pytest

STEP = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('test'),'2;1');
FILE_NAME('tiny.stp','2026-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));
ENDSEC;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=DIRECTION('',(0.,0.,1.));
#3=AXIS2_PLACEMENT_3D('',#1,#2,$);
ENDSEC;
END-ISO-10303-21;
"""


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    psycopg2 = pytest.importorskip('psycopg2')
    from config.config import TestingConfig
    url = str(TestingConfig.SQLALCHEMY_DATABASE_URI)
    base, name = url.replace('postgresql+psycopg2://', 'postgresql://').rsplit('/', 1)
    try:
        conn = psycopg2.connect(base + '/postgres', connect_timeout=3)
    except Exception as e:                                       # no local Postgres
        pytest.skip(f'PostgreSQL not available: {e}')
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{name}"')
    conn.close()

    from app import create_app
    from app.extensions import db
    app = create_app('testing')
    app.config['UPLOAD_FOLDER'] = str(tmp_path_factory.mktemp('uploads'))
    with app.app_context():
        _reset_schema(db)
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        _reset_schema(db)


def _reset_schema(db):
    # drop_all cannot order the step_file_headers <-> step_view_files foreign-key cycle
    from sqlalchemy import text
    db.session.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public'))
    db.session.commit()


def test_disk_files_are_registered_with_real_ids(app):
    import os
    folder = app.config['UPLOAD_FOLDER']
    with open(os.path.join(folder, 'tiny_part.stp'), 'w') as f:
        f.write(STEP)
    with open(os.path.join(folder, 'notes.txt'), 'w') as f:
        f.write('not a STEP file')
    c = app.test_client()
    files = c.get('/api/step-view/files').get_json()['files']
    assert [f['filename'] for f in files] == ['tiny_part.stp']
    uuid.UUID(files[0]['id'])                                    # a real id, not 'tiny_part_stp'
    assert files[0]['source'] == 'upload'
    again = c.get('/api/step-view/files').get_json()['files']   # adopted once, not duplicated
    assert [f['id'] for f in again] == [files[0]['id']]
    meta = c.get(f"/api/step-view/model/{files[0]['id']}/metadata")
    assert meta.status_code == 200


def test_non_uuid_model_id_is_404_not_500(app):
    c = app.test_client()
    for route in ('glb', 'metadata'):
        r = c.get(f'/api/step-view/model/ENSAMBLAJE_COMPLETO_stp/{route}')
        assert r.status_code == 404, (route, r.get_json())


def test_entity_graph_routes_are_gone(app):
    # graph / features / pmi / analysis were removed (the entity-graph storage lives in CAPP)
    c = app.test_client()
    hid = str(uuid.uuid4())
    for method, url in [('GET', f'/api/step-view/graph/{hid}/tree'), ('POST', f'/api/step-view/pmi/{hid}/extract'),
                        ('GET', f'/api/step-view/features/{hid}/list'),
                        ('POST', f'/api/step-view/analysis/{hid}/validate')]:
        r = c.open(url, method=method, json={})
        assert r.status_code in (404, 405), (url, r.status_code)
