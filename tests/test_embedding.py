"""Study embedding for similar-case search (plan 8.2): family taxonomy + similarity ranking."""
import pytest

from app.design.services.validation.embedding import embed_study, material_family, study_similarity

STEEL = {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7850}
FIX = [{'node_set': 'fixed', 'dofs': [0, 1, 2]}]
TIP = [{'node_set': 'tip', 'force': [0, 0, -1000]}]


def beam(L=0.5):
    return {'mesh_source': 'cantilever', 'mesh_params': {'length': L, 'width': 0.025, 'height': 0.025, 'order': 2}}


def study(mat=STEEL, name='Acero AISI 1045', geo=None, bcs=FIX, loads=TIP, physics=None):
    s = {**(geo or beam()), 'material': mat, 'bcs': bcs, 'loads': loads}
    if physics:
        s['physics'] = physics
    return embed_study(s, material_name=name, n_dof=9000)


@pytest.mark.parametrize('name,family', [
    ('Acero AISI 1045', 'steel'), ('Inox 316L', 'stainless'), ('Aluminio 7075-T6', 'aluminium'), ('PLA', 'polymer'),
    ('CFRP T300/914', 'composite'), ('Caucho natural', 'elastomer'), ('PZT-5H', 'piezoceramic'),
    ('NdFeB N42', 'magnet'), ('Acero eléctrico M19', 'magnet'), ('Agua 20 °C', 'liquid'),
    ('Hierro fundido GG25', 'cast_iron'), ('Material 1', None), (None, None)])
def test_material_family(name, family):
    assert material_family(name) == family


def test_similarity_ranking():
    ref = study()
    sim = lambda other: study_similarity(ref, other)[0]          # noqa: E731
    same = sim(study())
    other_steel = sim(study({**STEEL, 'E': 205e9, 'nu': 0.29}, 'Acero S355'))
    unnamed = sim(study(name=None))
    stainless = sim(study({**STEEL, 'E': 193e9, 'nu': 0.29, 'rho': 8000}, 'Inox 304'))
    plastic = sim(study({**STEEL, 'type': 'elastoplastic_vonmises', 'sigma_y': 350e6}))
    aluminium = sim(study({**STEEL, 'E': 69e9, 'nu': 0.33, 'rho': 2700}, 'Aluminio 6061'))
    pla = sim(study({**STEEL, 'E': 3.5e9, 'nu': 0.36, 'rho': 1240}, 'PLA'))
    longer = sim(study(geo=beam(1.0)))
    thermal = sim(study({**STEEL, 'k': 50}, bcs=[{'node_set': 'fixed', 'temperature': 100}],
                        loads=[{'face_set': 'tip', 'convection': {'h': 10, 'T_inf': 20}}], physics=['thermal']))
    fluid = sim(study({'type': 'newtonian_fluid', 'mu': 1.41, 'rho': 1261}, 'Glicerina',
                      loads=[{'face_set': 'fixed', 'pressure': 100}], physics=['fluid']))
    assert same == pytest.approx(1.0) and unnamed == pytest.approx(1.0)   # unknown family: not a penalty
    assert 1.0 > other_steel > stainless > aluminium > pla
    assert plastic > aluminium and longer > pla
    assert max(thermal, fluid) <= 0.45 < pla                      # another physics is never a close case


def test_same_cad_identity_and_breakdown():
    a = embed_study({'geometry': {'step_sha256': 'abc'}, 'material': STEEL, 'bcs': FIX, 'loads': TIP})
    b = embed_study({'geometry': {'step_sha256': 'abc'}, 'material': STEEL, 'bcs': FIX, 'loads': TIP})
    c = embed_study({'geometry': {'step_sha256': 'xyz'}, 'material': STEEL, 'bcs': FIX, 'loads': TIP})
    s, parts = study_similarity(a, b)
    assert s == pytest.approx(1.0) and parts['geometry'] == 1.0
    assert study_similarity(a, c)[1]['geometry'] == 0.0          # unknown shapes, different parts
