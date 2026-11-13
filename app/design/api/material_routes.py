"""Design Material API — active material models with uncertainty (FASE 6).

Material library (table material_models):
  GET/POST /                         list / create   {name, model_type, parameters: {E: {value, std}, …}}
  GET/PUT/DELETE /<id>
  POST /fit-curves                   stateless fit of tensile-test curves (CSV files or JSON datasets)
  POST /<id>/fit                     fit and store the result in the material (parameters + calibration)
  POST /<id>/predict                 σ(ε), tangent and confidence band of the stored fit
  POST /<id>/assign                  copy the material into a graph MATERIAL node (E, ν, ρ, σy with std)

Uncertainty propagation (job 'uncertainty.mc', SimulationRun purpose='uncertainty'):
  GET  /uncertainty/<graph_id>/setup     random-variable candidates (defaults from the MATERIAL node), ROMs
  POST /uncertainty/<graph_id>/run       {distributions, n_samples, confidence, seed, failure, method, rom_id}
  POST /<id>/propagate-uncertainty       same, with the material's std as distributions ({graph_id, …})
  GET  /uncertainty/<graph_id>/list
  GET  /uncertainty/run/<run_id>         statistics, reliability, sensitivities, convergence
  GET  /uncertainty/run/<run_id>/surface binary pack (xyz mm, tris, mean/std/upper fields)
  GET  /<id>/uncertainty-results         runs that used this material
"""
from __future__ import annotations

import logging
import math
import uuid as _uuid
from datetime import datetime

import numpy as np
from flask import Blueprint, Response, jsonify, request

from app.extensions import db
from app.design.models.material import MaterialModel

logger = logging.getLogger(__name__)
bp = Blueprint('design_material', __name__)

MPA = 1e6


def _finite(x):
    """JSON-safe: NaN/inf → None, numpy → python (recursively)."""
    if isinstance(x, dict):
        return {str(k): _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    if isinstance(x, np.ndarray):
        return _finite(x.tolist())
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return x if math.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def _get_material(material_id):
    try:
        return db.session.get(MaterialModel, _uuid.UUID(str(material_id)))
    except (ValueError, TypeError):
        return None


def _mat_dict(m: MaterialModel, full: bool = True) -> dict:
    d = {'id': str(m.id), 'name': m.name, 'model_type': m.model_type, 'parameters': m.parameters or {},
         'description': m.description, 'graph_id': str(m.graph_id) if m.graph_id else None,
         'is_active': m.is_active, 'created_at': m.created_at.isoformat() if m.created_at else None,
         'updated_at': m.updated_at.isoformat() if m.updated_at else None}
    cal = m.calibration or {}
    if full:
        d['calibration'] = {k: v for k, v in cal.items() if k not in ('cov', 's2')}
    else:
        d['calibration'] = {k: cal.get(k) for k in ('best_model', 'label', 'r_squared', 'n_specimens', 'date')}
    return _finite(d)


# ── Library CRUD ──────────────────────────────────────────────────────────────

@bp.route('/status', methods=['GET'])
def status():
    from app.design.services.material.parametric import CURVE_MODELS
    total = 0
    try:
        total = MaterialModel.query.count()
    except Exception:
        pass
    return jsonify({'module': 'design.material', 'status': 'ok', 'total_materials': total,
                    'curve_models': [{'key': m.key, 'label': m.label, 'description': m.description,
                                      'params': m.param_names, 'elastoplastic': m.elastoplastic}
                                     for m in CURVE_MODELS.values()]}), 200


def _clean_parameters(params: dict) -> dict:
    out = {}
    for k, v in (params or {}).items():
        if isinstance(v, dict):
            val = v.get('value')
            if val is None:
                continue
            out[k] = {'value': float(val), 'std': float(v.get('std') or 0.0),
                      **({'unit': v['unit']} if v.get('unit') is not None else {})}
        elif v is not None:
            out[k] = {'value': float(v), 'std': 0.0}
    return out


@bp.route('/', methods=['GET'])
def list_materials():
    q = MaterialModel.query.filter_by(is_active=True).order_by(MaterialModel.name, MaterialModel.created_at)
    return jsonify({'materials': [_mat_dict(m, full=False) for m in q.all()]}), 200


@bp.route('/', methods=['POST'])
def create_material():
    """Body: { name, model_type, parameters: { E: {value, std}, nu: {value, std}, rho: …, sigma_y: … } }"""
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'El material necesita un nombre.'}), 422
    try:
        params = _clean_parameters(body.get('parameters'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Parámetros inválidos'}), 422
    m = MaterialModel(name=name, model_type=body.get('model_type') or 'linear_elastic_isotropic',
                      parameters=params, calibration={}, description=body.get('description'),
                      graph_id=body.get('graph_id'))
    db.session.add(m)
    db.session.commit()
    return jsonify(_mat_dict(m)), 201


@bp.route('/<string:material_id>', methods=['GET'])
def get_material(material_id):
    m = _get_material(material_id)
    if m is None:
        return jsonify({'error': 'Material not found'}), 404
    return jsonify(_mat_dict(m)), 200


@bp.route('/<string:material_id>', methods=['PUT'])
def update_material(material_id):
    m = _get_material(material_id)
    if m is None:
        return jsonify({'error': 'Material not found'}), 404
    body = request.get_json(silent=True) or {}
    if 'name' in body:
        if not (body['name'] or '').strip():
            return jsonify({'error': 'El material necesita un nombre.'}), 422
        m.name = body['name'].strip()
    if 'model_type' in body:
        m.model_type = body['model_type']
    if 'description' in body:
        m.description = body['description']
    if 'parameters' in body:
        try:
            m.parameters = _clean_parameters(body['parameters'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Parámetros inválidos'}), 422
    m.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(_mat_dict(m)), 200


@bp.route('/<string:material_id>', methods=['DELETE'])
def delete_material(material_id):
    """Soft delete (validation records may reference the material)."""
    m = _get_material(material_id)
    if m is None:
        return jsonify({'error': 'Material not found'}), 404
    m.is_active = False
    db.session.commit()
    return jsonify({'deleted': str(m.id)}), 200


# ── Curve fitting ─────────────────────────────────────────────────────────────

def _datasets_from_request():
    """Tensile curves from multipart CSV files ('files') or JSON {datasets: [{name, strain, stress|csv}]}.
    Stress in the JSON datasets is in MPa unless ``stress_unit`` says otherwise."""
    from app.design.services.material.parametric import parse_curve_csv, _UNIT_STRESS
    if request.files:
        opts = request.form
        files = request.files.getlist('files') or list(request.files.values())
        raw = [{'name': f.filename, 'csv': f.read().decode('utf-8-sig', errors='replace')} for f in files]
    else:
        opts = request.get_json(silent=True) or {}
        raw = opts.get('datasets') or ([opts] if 'strain' in opts or 'csv' in opts else [])
    if not raw:
        raise ValueError('Sube al menos un archivo CSV de ensayo (o datasets JSON).')

    def num(k):
        v = opts.get(k)
        return float(v) if v not in (None, '', 'null') else None

    datasets, notes = [], []
    for i, d in enumerate(raw):
        name = d.get('name') or f'Probeta {i + 1}'
        if 'csv' in d:
            p = parse_curve_csv(d['csv'], strain_unit=opts.get('strain_unit') or 'auto',
                                stress_unit=opts.get('stress_unit') or 'auto',
                                area_mm2=num('area_mm2'), gauge_mm=num('gauge_mm'))
            datasets.append({'name': name, 'strain': p['strain'], 'stress': p['stress']})
            notes.append({'name': name, 'notes': p['notes'], 'columns': p['columns'], 'n_rows': p['n_rows']})
        else:
            su = (opts.get('stress_unit') or 'mpa').lower()
            scale = _UNIT_STRESS.get(su, 1.0)
            e = np.asarray(d['strain'], float)
            if (opts.get('strain_unit') or '') in ('%', 'percent'):
                e = e / 100
            datasets.append({'name': name, 'strain': e, 'stress': np.asarray(d['stress'], float) * scale})
            notes.append({'name': name, 'notes': [], 'columns': ['strain', 'stress'], 'n_rows': len(e)})
    models = opts.get('models')
    if isinstance(models, str):
        models = [m for m in models.split(',') if m]
    conf = float(opts.get('confidence') or 0.95)
    return datasets, notes, models, conf


def _run_fit():
    from app.design.services.material.parametric import ParametricMaterialModel, MaterialFitError
    try:
        datasets, notes, models, conf = _datasets_from_request()
        pm = ParametricMaterialModel()
        res = pm.fit(datasets, models, confidence=conf)
    except (MaterialFitError, ValueError, KeyError) as e:
        return None, None, (jsonify({'error': str(e)}), 422)
    for s, n in zip(res['specimens'], notes):
        s['parse_notes'] = n['notes']
        s['columns'] = n['columns']
        s['n_rows'] = n['n_rows']
    return res, pm, None


@bp.route('/fit-curves', methods=['POST'])
def fit_curves():
    """Fit all candidate models to the uploaded curves (nothing stored)."""
    res, _, err = _run_fit()
    if err:
        return err
    return jsonify(_finite(res)), 200


@bp.route('/<string:material_id>/fit', methods=['POST'])
def fit_material(material_id):
    """Fit and store. Form/JSON as /fit-curves, plus optional ``model`` to force a candidate."""
    m = _get_material(material_id)
    if m is None:
        return jsonify({'error': 'Material not found'}), 404
    res, pm, err = _run_fit()
    if err:
        return err
    forced = (request.form.get('model') if request.files else (request.get_json(silent=True) or {}).get('model'))
    chosen = next((r for r in pm.results if r['model'] == forced), pm.best) if forced else pm.best
    sel = {**res, 'best_model': chosen['model'], 'label': chosen['label'], 'parameters': chosen['parameters'],
           'r_squared': chosen['r2']}
    from app.design.services.material.parametric import material_parameters_from_fit
    apply_fit_to_material(m, res, chosen, material_parameters_from_fit(sel, m.parameters))
    db.session.commit()
    sync_material_nodes(m)
    return jsonify({**_finite(sel), 'material': _mat_dict(m)}), 200


def apply_fit_to_material(m: MaterialModel, res: dict, chosen: dict, parameters: dict, extra: dict | None = None):
    """Store a curve fit in the material (parameters, model type, calibration; keeps the history).
    Does not commit."""
    m.parameters = parameters
    m.model_type = f"elastoplastic_{chosen['model']}" if chosen['elastoplastic'] else 'linear_elastic_isotropic'
    per0 = chosen['_per'][0]
    history = list((m.calibration or {}).get('history') or [])
    m.calibration = _finite({
        'best_model': chosen['model'], 'label': chosen['label'], 'r_squared': chosen['r2'],
        'aicc': chosen['aicc'], 'n_specimens': len(res['specimens']), 'std_source': res['std_source'],
        'date': datetime.utcnow().isoformat(), 'method': 'least_squares (scipy TRF) + AICc',
        'all_results': res['all_results'], 'specimens': res['specimens'], 'properties': res['properties'],
        'curves': res['curves'], 'confidence': res['confidence'], 'fit_parameters': chosen['parameters'],
        'cov': per0['_cov'], 's2': per0['_s2'], 'history': history, **(extra or {}),
    })
    m.updated_at = datetime.utcnow()


def node_props_from_material(m: MaterialModel, props: dict) -> dict:
    """MATERIAL node properties from a library material (the FEM kernel is linear elastic: E, ν, ρ
    with std, and σy as the yield strength of the failure criterion)."""
    P = m.parameters or {}
    props = dict(props or {})
    # the user may have switched the node to J2 plasticity: keep it (the fit supplies its hardening)
    if props.get('model_type') != 'elastoplastic_vonmises':
        props['model_type'] = 'linear_elastic_isotropic'
    for k in ('E', 'nu', 'rho'):
        if k in P:
            props[k] = P[k]['value']
            props[f'{k}_std'] = P[k].get('std') or 0.0
    if 'sigma_y' in P:
        props['yield_strength'] = P['sigma_y']['value']
        props['yield_std'] = P['sigma_y'].get('std') or 0.0
    props.pop('E_source', None)                      # E comes from the material again (not a structural E*)
    props['material_id'] = str(m.id)
    props['material_name'] = m.name
    props['constitutive_fit'] = (m.calibration or {}).get('best_model')
    table = _hardening_table(m)
    if table:
        props['hardening_table'] = table          # used when MATERIAL model_type = elastoplastic_vonmises
    else:
        props.pop('hardening_table', None)
    return _finite(props)


def _hardening_table(m: MaterialModel) -> dict | None:
    """Plastic branch of the stored tensile fit as a J2 hardening table (FASE 2.5), Pa."""
    from app.design.services.material.parametric import CURVE_MODELS, MPA as _M
    from app.design.services.fem.plasticity import hardening_table_from_fit
    cal = m.calibration or {}
    model = CURVE_MODELS.get(cal.get('best_model'))
    fp = cal.get('fit_parameters') or {}
    if model is None or not model.elastoplastic or not all(n in fp for n in model.param_names):
        return None
    try:
        p = np.array([fp[n]['value'] / (_M if model.param_units.get(n) == 'MPa' else 1) for n in model.param_names])
        ue = ((cal.get('properties') or {}).get('uniform_elongation') or {})
        ue = ue.get('value') if isinstance(ue, dict) else ue
        t = hardening_table_from_fit(model, p, model.E(p), max(float(ue or 0.1), 0.01))
        return {'ep': t['ep'], 'sy': t['sy'], 'model': model.key} if t else None
    except Exception:                                   # a bad stored fit must not break the assignment
        return None


def sync_material_nodes(m: MaterialModel) -> list[str]:
    """Refresh every MATERIAL node linked to the material (after a fit / recalibration)."""
    from app.design.models.graph import DesignNode
    from app.design.services.graph_service import DesignGraphService
    nodes = DesignNode.query.filter(DesignNode.node_type == 'MATERIAL',
                                    DesignNode.properties['material_id'].astext == str(m.id)).all()
    svc = DesignGraphService()
    for n in nodes:
        svc.update_node(n.graph_id, n.id, {'properties': node_props_from_material(m, n.properties)})
    return [str(n.id) for n in nodes]


@bp.route('/<string:material_id>/predict', methods=['POST'])
def predict_material(material_id):
    """Body: { strain: float | [..], confidence } → stress, tangent [Pa] and band of the stored fit."""
    from app.design.services.material.parametric import CURVE_MODELS, MPA as _M
    from app.design.services.material.calibrator import prediction_band
    m = _get_material(material_id)
    if m is None:
        return jsonify({'error': 'Material not found'}), 404
    cal = m.calibration or {}
    body = request.get_json(silent=True) or {}
    eps = np.atleast_1d(np.asarray(body.get('strain', 0.0), float))
    if cal.get('best_model') in CURVE_MODELS:
        model = CURVE_MODELS[cal['best_model']]
        fp = cal['fit_parameters']
        p = np.array([fp[n]['value'] / (_M if model.param_units.get(n) == 'MPa' else 1) for n in model.param_names])
        s = model.predict(eps, p)
        h = 1e-7
        t = (model.predict(eps + h, p) - model.predict(eps - h, p)) / (2 * h)
        out = {'model': model.key, 'strain': eps.tolist(), 'stress': (s * _M).tolist(),
               'tangent_modulus': (t * _M).tolist()}
        if cal.get('cov') is not None:
            cov = np.array([[np.nan if v is None else v for v in row] for row in cal['cov']], float)
            lo, hi, _ = prediction_band(model.predict, eps, p, cov, float(body.get('confidence', 0.95)))
            out['lower'], out['upper'] = (lo * _M).tolist(), (hi * _M).tolist()
        return jsonify(_finite(out)), 200
    E = (m.parameters or {}).get('E', {}).get('value')
    if not E:
        return jsonify({'error': 'El material no tiene E ni ajuste.'}), 422
    return jsonify({'model': 'linear', 'strain': eps.tolist(), 'stress': (E * eps).tolist(),
                    'tangent_modulus': [E] * len(eps)}), 200


@bp.route('/<string:material_id>/assign', methods=['POST'])
def assign_material(material_id):
    """Body: { graph_id, node_id } → MATERIAL node properties from the library material.

    The FEM kernel is linear-elastic: the node gets E, ν, ρ (with their std) and σy as the yield
    strength used by the failure criterion of the uncertainty study.
    """
    from app.design.models.graph import DesignNode
    from app.design.services.graph_service import DesignGraphService
    m = _get_material(material_id)
    if m is None:
        return jsonify({'error': 'Material not found'}), 404
    body = request.get_json(silent=True) or {}
    node = DesignNode.query.filter_by(id=body.get('node_id'), graph_id=body.get('graph_id')).first()
    if node is None or node.node_type != 'MATERIAL':
        return jsonify({'error': 'Nodo MATERIAL no encontrado en el grafo'}), 404
    props = node_props_from_material(m, node.properties)
    DesignGraphService().update_node(body['graph_id'], node.id, {'properties': props, 'label': node.label or m.name})
    return jsonify({'node_id': str(node.id), 'properties': _finite(props)}), 200


# ── Uncertainty propagation ───────────────────────────────────────────────────

def _material_node_props(graph_id) -> dict:
    from app.design.models.graph import DesignNode
    n = (DesignNode.query.filter_by(graph_id=graph_id, node_type='MATERIAL')
         .order_by(DesignNode.created_at, DesignNode.id).first())
    return dict(n.properties or {}) if n else {}


def _graph_roms(graph_id):
    from app.design.models.simulation import SimulationRun
    runs = (SimulationRun.query.filter(SimulationRun.graph_id == graph_id, SimulationRun.purpose == 'rom',
                                       SimulationRun.status == 'done')
            .order_by(SimulationRun.created_at.desc()).limit(20).all())
    return [{'rom_id': str(r.id), 'hash': r.hash, 'created_at': r.created_at.isoformat() if r.created_at else None,
             'parameter_space': ((r.solver_config or {}).get('rom') or {}).get('parameter_space') or {},
             'n_modes': (r.summary or {}).get('n_modes'),
             'validation_max_error_u': (r.summary or {}).get('validation_max_error_u')} for r in runs]


@bp.route('/uncertainty/<string:graph_id>/setup', methods=['GET'])
def uncertainty_setup(graph_id):
    """Candidates for random variables with defaults: material std from the MATERIAL node
    (E_std, nu_std, rho_std, yield_strength/yield_std); loads with 0 std."""
    from app.design.services.graph_to_solver_spec import graph_to_solver_spec, GraphSpecError
    from app.design.services.rom.pod import describe_parameters
    from app.design.services.material.uncertainty import TIER_MC_SAMPLES, MAX_ROM_SAMPLES
    try:
        spec = graph_to_solver_spec(graph_id)
    except GraphSpecError as e:
        return jsonify({'error': str(e), 'kind': 'graph_spec'}), 422
    props = _material_node_props(graph_id)
    params = []
    for p in describe_parameters(spec):
        std = float(props.get(f"{p['key']}_std") or 0.0) if p['key'] in ('E', 'nu', 'rho') else 0.0
        params.append({**p, 'std': std})
    failure = None
    if props.get('yield_strength'):
        failure = {'yield_mean': float(props['yield_strength']), 'yield_std': float(props.get('yield_std') or 0.0)}
    return jsonify(_finite({
        'graph_id': graph_id, 'parameters': params, 'failure': failure,
        'material': {k: props.get(k) for k in ('material_id', 'material_name', 'constitutive_fit')},
        'roms': _graph_roms(graph_id), 'tier_samples': TIER_MC_SAMPLES, 'max_rom_samples': MAX_ROM_SAMPLES,
    })), 200


def _launch_uncertainty(graph_id: str, body: dict, material=None):
    from app.design.models.graph import DesignGraph
    from app.design.models.simulation import SimulationRun
    from app.design.api.solver_routes import prepare_spec, _create_and_enqueue
    from app.design.services.rom.pod import describe_parameters
    from app.design.services.material.runner import sample_cap
    graph = db.session.get(DesignGraph, graph_id)
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404
    keys = ('distributions', 'n_samples', 'confidence', 'seed', 'failure', 'method', 'rom_id')
    data = {k: v for k, v in body.items() if k not in keys}
    data, err = prepare_spec(graph_id, data)
    if err:
        return err
    if not data.get('loads') or not data.get('bcs'):
        return jsonify({'error': 'El estudio necesita al menos una restricción y una carga.', 'kind': 'graph_spec'}), 422
    available = {p['key']: p for p in describe_parameters(data)}
    dists = {}
    for k, d in (body.get('distributions') or {}).items():
        if k not in available:
            return jsonify({'error': f"Variable desconocida '{k}'", 'available': list(available)}), 422
        try:
            mean = float(d.get('mean', available[k]['nominal']))
            std = float(d.get('std') or 0.0)
        except (TypeError, ValueError):
            return jsonify({'error': f"Distribución inválida para '{k}'"}), 422
        if std < 0:
            return jsonify({'error': f"Desviación negativa en '{k}'"}), 422
        if std > 0:
            dists[k] = {'mean': mean, 'std': std, 'dist': 'normal'}
    if material is not None:
        P = material.parameters or {}
        for k in ('E', 'nu', 'rho'):
            if k in P and k in available and float(P[k].get('std') or 0) > 0 and k not in dists:
                dists[k] = {'mean': float(P[k]['value']), 'std': float(P[k]['std']), 'dist': 'normal'}
    if not dists:
        return jsonify({'error': 'Ninguna variable aleatoria: indica al menos una desviación estándar > 0.'}), 422
    # the means are the study's values: make the solver spec agree with them
    mat = dict(data.get('material') or {})
    for k in ('E', 'nu', 'rho'):
        if k in dists:
            mat[k] = dists[k]['mean']
    data['material'] = mat
    failure = body.get('failure')
    if failure is None and material is not None and 'sigma_y' in (material.parameters or {}):
        sy = material.parameters['sigma_y']
        failure = {'yield_mean': sy['value'], 'yield_std': sy.get('std') or 0.0}
    if failure:
        try:
            failure = {'yield_mean': float(failure['yield_mean']), 'yield_std': float(failure.get('yield_std') or 0)}
        except (KeyError, TypeError, ValueError):
            return jsonify({'error': 'Criterio de fallo inválido (yield_mean, yield_std en Pa).'}), 422
        if failure['yield_mean'] <= 0:
            failure = None
    # method: explicit ROM, auto (newest ROM covering the random variables) or full
    method = body.get('method', 'auto')
    rom = None
    if method in ('auto', 'rom'):
        roms = _graph_roms(graph_id)
        if body.get('rom_id'):
            roms = [r for r in roms if r['rom_id'] == str(body['rom_id'])]
            if not roms:
                return jsonify({'error': 'ROM no encontrado o sin terminar para este estudio.'}), 404
        need = [k for k in dists if k != 'E']
        rom = next((r for r in roms if all(k in r['parameter_space'] for k in need)), None)
        if rom is None and method == 'rom':
            return jsonify({'error': 'Ningún ROM del estudio varía ' + ', '.join(need) +
                            ' — construye uno en la pestaña ROM o usa solves completos.'}), 422
    method = 'rom' if rom else 'full'
    tier = int(data.get('tier', 1))
    cap = sample_cap(method, tier)
    try:
        n = int(body.get('n_samples') or min(cap, 1000 if method == 'rom' else cap))
        conf = float(body.get('confidence', 0.95))
        seed = int(body.get('seed', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'n_samples, confidence y seed deben ser numéricos'}), 422
    if n < 10:
        return jsonify({'error': 'Al menos 10 muestras.'}), 422
    if n > cap:
        return jsonify({'error': 'TierLimitExceeded',
                        'message': f'{n} muestras superan el límite de {cap} para '
                                   f"{'el ROM' if method == 'rom' else f'solves completos en tier {tier}'}.",
                        'limit': cap}), 413
    if not 0.5 <= conf < 1:
        return jsonify({'error': 'El nivel de confianza debe estar en [0.5, 1).'}), 422
    cfg = {'distributions': dists, 'n_samples': n, 'confidence': conf, 'seed': seed, 'failure': failure,
           'method': method}
    if rom:
        cfg['rom_id'] = rom['rom_id']
        cfg['rom_hash'] = rom['hash']
    if material is not None:
        cfg['material_id'] = str(material.id)
    elif _material_node_props(graph_id).get('material_id'):
        cfg['material_id'] = str(_material_node_props(graph_id)['material_id'])
    data['uncertainty'] = cfg
    data['graph_id'] = graph_id
    run, job = _create_and_enqueue(graph, data, purpose='uncertainty')
    return jsonify({'run_id': str(run.id), 'job_id': str(job.id), 'hash': run.hash, 'status': 'queued',
                    'method': method, 'n_samples': n, 'rom_id': cfg.get('rom_id'),
                    'distributions': dists, 'failure': failure}), 202


@bp.route('/uncertainty/<string:graph_id>/run', methods=['POST'])
def run_uncertainty(graph_id):
    return _launch_uncertainty(graph_id, request.get_json(silent=True) or {})


@bp.route('/<string:material_id>/propagate-uncertainty', methods=['POST'])
def propagate_uncertainty(material_id):
    """Body: { graph_id, n_samples, confidence, method, rom_id } — std from the material."""
    m = _get_material(material_id)
    if m is None:
        return jsonify({'error': 'Material not found'}), 404
    body = request.get_json(silent=True) or {}
    if not body.get('graph_id'):
        return jsonify({'error': 'graph_id requerido'}), 422
    return _launch_uncertainty(str(body['graph_id']), body, material=m)


def _unc_run(run_id):
    from app.design.models.simulation import SimulationRun
    try:
        run = db.session.get(SimulationRun, _uuid.UUID(str(run_id)))
    except (ValueError, TypeError):
        return None
    if run is None or 'uncertainty' not in (run.solver_config or {}):
        return None
    return run


def _unc_brief(r):
    s = r.summary or {}
    cfg = (r.solver_config or {}).get('uncertainty') or {}
    return _finite({'run_id': str(r.id), 'status': r.status, 'hash': r.hash, 'purpose': r.purpose,
                    'created_at': r.created_at.isoformat() if r.created_at else None,
                    'method': cfg.get('method'), 'n_samples': cfg.get('n_samples'),
                    'variables': sorted(cfg.get('distributions') or {}),
                    'max_von_mises_mean_mpa': s.get('max_von_mises_mean_mpa'),
                    'max_von_mises_ci_high_mpa': s.get('max_von_mises_ci_high_mpa'),
                    'p_failure': s.get('p_failure'), 'beta': s.get('beta'),
                    'wall_time_s': s.get('wall_time_s'), 'error': (r.mesh_stats or {}).get('error')})


@bp.route('/uncertainty/<string:graph_id>/list', methods=['GET'])
def list_uncertainty(graph_id):
    from app.design.models.simulation import SimulationRun
    runs = (SimulationRun.query.filter(SimulationRun.graph_id == graph_id,
                                       SimulationRun.purpose.in_(('uncertainty',)))
            .order_by(SimulationRun.created_at.desc()).limit(50).all())
    return jsonify({'runs': [_unc_brief(r) for r in runs]}), 200


@bp.route('/uncertainty/run/<string:run_id>', methods=['GET'])
def uncertainty_run(run_id):
    run = _unc_run(run_id)
    if run is None:
        return jsonify({'error': 'Uncertainty run not found'}), 404
    return jsonify(_finite({**_unc_brief(run), 'graph_id': str(run.graph_id),
                            'setup': (run.solver_config or {}).get('uncertainty'),
                            'summary': run.summary or {}})), 200


@bp.route('/uncertainty/run/<string:run_id>/surface', methods=['GET'])
def uncertainty_surface(run_id):
    """Binary pack: xyz [mm], tris, disp_mean [m] and the scalar fields (float32)."""
    import os
    from app.design.services.binpack import pack_arrays
    from app.design.services.material.runner import result_path
    run = _unc_run(run_id)
    if run is None or run.status != 'done':
        return jsonify({'error': 'Resultados no disponibles'}), 404
    path = result_path(run_id)
    if not os.path.exists(path):
        return jsonify({'error': 'Archivo de resultados no encontrado'}), 404
    with np.load(path) as z:
        arrays = [('xyz', (z['surf_xyz'] * 1000.0).astype(np.float32)),
                  ('tris', z['surf_tris'].astype(np.uint32)),
                  ('disp_mean', z['surf_disp_mean'].astype(np.float32))]
        for k in ('vm_mean', 'vm_std', 'vm_high', 'vm_low', 'u_mean', 'u_std', 'u_high'):
            arrays.append((k, z[f'surf_{k}'].astype(np.float32)))
    body = pack_arrays({'run_id': run_id, 'r': 0, 'confidence': (run.summary or {}).get('confidence')}, arrays)
    return Response(body, mimetype='application/octet-stream', headers={'Cache-Control': 'private, max-age=3600'})


@bp.route('/<string:material_id>/uncertainty-results', methods=['GET'])
def uncertainty_results(material_id):
    from app.design.models.simulation import SimulationRun
    m = _get_material(material_id)
    if m is None:
        return jsonify({'error': 'Material not found'}), 404
    runs = (SimulationRun.query.filter(SimulationRun.purpose == 'uncertainty')
            .order_by(SimulationRun.created_at.desc()).limit(200).all())
    mine = [r for r in runs if ((r.solver_config or {}).get('uncertainty') or {}).get('material_id') == str(m.id)]
    return jsonify({'material_id': str(m.id), 'runs': [_unc_brief(r) for r in mine]}), 200
