"""STEP files without B-rep topology never reach the DB (viewer: "no transferable shapes")."""
import io

import pytest

from app.geometry.step_check import INVALID_STEP_MESSAGE, step_problem

LOOSE = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Cylindrical shaft with shoulder'),'2;1');
FILE_NAME('cylinder_shaft.stp','2025-12-27T10:00:00',('Engineer'),('CAPP System'),'','','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));
ENDSEC;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=DIRECTION('',(0.,0.,1.));
#3=DIRECTION('',(1.,0.,0.));
#4=AXIS2_PLACEMENT_3D('',#1,#2,#3);
#14=CYLINDRICAL_SURFACE('',#4,25.);
#16=ADVANCED_BREP_SHAPE_REPRESENTATION('Shaft',(#14),#4);
ENDSEC;
END-ISO-10303-21;
"""
SOLID = LOOSE.replace("#16=ADVANCED", "#15=MANIFOLD_SOLID_BREP('',#99);\n#16=ADVANCED")
COMPLEX = LOOSE.replace("#16=ADVANCED", "#15=( GEOMETRIC_REPRESENTATION_ITEM() MANIFOLD_SOLID_BREP('',#99) "
                                        "REPRESENTATION_ITEM('') );\n#16=ADVANCED")
SHELL = LOOSE.replace("#16=ADVANCED", "#15=OPEN_SHELL('',(#20));\n#16=ADVANCED")


@pytest.mark.parametrize('text,ok', [(LOOSE, False), (SOLID, True), (COMPLEX, True), (SHELL, True)])
def test_step_problem(tmp_path, text, ok):
    f = tmp_path / 'a.stp'
    f.write_text(text)
    assert (step_problem(f) is None) == ok
    if not ok:
        assert step_problem(f) == INVALID_STEP_MESSAGE


def test_not_a_step_and_empty(tmp_path):
    (tmp_path / 'x.stp').write_text('hello')
    (tmp_path / 'e.stp').write_text('')
    assert 'ISO-10303-21' in step_problem(tmp_path / 'x.stp')
    assert 'vacío' in step_problem(tmp_path / 'e.stp')


def test_entity_found_across_chunk_boundary(tmp_path, monkeypatch):
    import app.geometry.step_check as sc
    monkeypatch.setattr(sc, '_CHUNK', 1024)
    body = LOOSE.replace('ENDSEC;\nEND', '#9=CARTESIAN_POINT(\'\',(0.,0.,0.));\n' * 200
                         + "#15=MANIFOLD_SOLID_BREP('',#99);\nENDSEC;\nEND")
    f = tmp_path / 'big.stp'
    f.write_text(body)
    assert step_problem(f) is None


@pytest.fixture
def client(tmp_path):
    from app import create_app
    app = create_app('testing')
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    return app.test_client(), app, tmp_path


def test_upload_rejects_loose_geometry(client):
    c, app, folder = client
    # rejected right after saving, before any DB access (the test DB has no tables)
    r = c.post('/api/step-view/upload/', data={'file': (io.BytesIO(LOOSE.encode()), 'cylinder_shaft.stp')},
               content_type='multipart/form-data')
    assert r.status_code == 422 and 'geometría sólida' in r.get_json()['error']
    assert not (folder / 'cylinder_shaft.stp').exists()
