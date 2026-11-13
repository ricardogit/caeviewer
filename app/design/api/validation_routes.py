"""Design Validation API — experiments, correlation and recalibration (FASE 8).

  GET  /status
  POST /experiments/preview          parse an uploaded file (no storage): detected columns, points, ranges
  POST /experiments                  store an experiment (multipart: file + fields, or JSON); calibrate=1 →
                                     tensile: recalibrate the material; structural: correlate with the latest run
  GET  /experiments[?graph_id&material_id&test_type]   ·   GET/DELETE /experiments/<id>
  POST /<graph_id>/correlate         {experiment_id, run_id?} → metrics (+ stored SimExperimentCorrelation)
  GET  /<graph_id>/correlations
  GET  /<graph_id>/confidence        confidence before simulating, similar cases, recommended tests
  POST /<graph_id>/recalibrate       {experiment_id, mode: replace|bayes, apply: true}
                                     tensile → material parameters (+ linked MATERIAL nodes);
                                     structural → effective E of the study's MATERIAL node

test_type: 'tensile' (σ-ε / force-displacement curve of a specimen) | 'structural' (sensors on the part).
"""
from __future__ import annotations

import json
import logging
import os
import uuid as _uuid
from datetime import datetime

import numpy as np
from flask import Blueprint, jsonify, request, current_app

from app.extensions import db
from app.design.models.validation import ExperimentalRecord, SimExperimentCorrelation

logger = logging.getLogger(__name__)
bp = Blueprint('design_validation', __name__)

TEST_TYPES = {'tensile': 'Tracción (probeta)', 'structural': 'Estático de la pieza (sensores)'}


def _finite(x):
    from app.design.api.material_routes import _finite as f
    return f(x)


def _uuid_or_none(v):
    try:
        return _uuid.UUID(str(v)) if v not in (None, '', 'null') else None
    except (ValueError, TypeError):
        return None


def _get(model, id_):
    u = _uuid_or_none(id_)
    return db.session.get(model, u) if u else None


@bp.route('/status', methods=['GET'])
def status():
    total = 0
    try:
        total = ExperimentalRecord.query.count()
    except Exception:
        pass
    return jsonify({'module': 'design.validation', 'status': 'ok', 'total_experiments': total,
                    'test_types': TEST_TYPES}), 200


# ── Experiments ───────────────────────────────────────────────────────────────

def _form():
    """Fields + file text from multipart or JSON."""
    if request.files:
        f = request.files.get('file') or next(iter(request.files.values()))
        raw = f.read()
        fields = request.form.to_dict()
        return fields, raw.decode('utf-8-sig', errors='replace'), f.filename, raw
    body = request.get_json(silent=True) or {}
    text = body.get('csv')
    return body, text, body.get('filename'), text.encode() if text else None


def _num(v):
    try:
        return float(v) if v not in (None, '', 'null') else None
    except (TypeError, ValueError):
        return None


def _parse(test_type: str, fields: dict, text: str | None):
    """→ (raw_data, preview) for the experiment type."""
    from app.design.services.material.parametric import parse_curve_csv, MaterialFitError
    from app.design.services.validation.sensors import parse_sensor_csv, SensorError, QUANTITIES
    if test_type == 'tensile':
        if text:
            p = parse_curve_csv(text, strain_unit=fields.get('strain_unit') or 'auto',
                                stress_unit=fields.get('stress_unit') or 'auto',
                                area_mm2=_num(fields.get('area_mm2')), gauge_mm=_num(fields.get('gauge_mm')))
            eps, sig, cols, notes = p['strain'], p['stress'], p['columns'], p['notes']
        elif 'strain' in fields and 'stress' in fields:
            eps, sig = np.asarray(fields['strain'], float), np.asarray(fields['stress'], float)
            cols, notes = ['strain', 'stress'], []
        else:
            raise MaterialFitError('Falta el archivo CSV del ensayo.')
        step = max(1, len(eps) // 3000)                                   # keep ≤ 3000 points
        raw = {'strain': eps[::step].tolist(), 'stress': sig[::step].tolist(), 'stress_unit': 'MPa'}
        preview = {'columns': cols, 'notes': notes, 'n_points': int(len(eps)),
                   'strain_range': [float(np.nanmin(eps)), float(np.nanmax(eps))],
                   'stress_range_mpa': [float(np.nanmin(sig)), float(np.nanmax(sig))]}
        return raw, preview
    if test_type == 'structural':
        if text:
            sensors = parse_sensor_csv(text)
        elif fields.get('sensors'):
            sensors = fields['sensors'] if isinstance(fields['sensors'], list) else json.loads(fields['sensors'])
        else:
            raise SensorError('Falta el archivo CSV de sensores.')
        counts = {}
        for s in sensors:
            counts[s['quantity']] = counts.get(s['quantity'], 0) + 1
        preview = {'n_points': len(sensors), 'quantities': {k: {'n': v, 'label': QUANTITIES[k][0],
                                                                 'unit': QUANTITIES[k][1]} for k, v in counts.items()},
                   'sensors': sensors[:50]}
        return {'sensors': sensors}, preview
    raise ValueError(f"Tipo de ensayo desconocido '{test_type}' (tensile | structural)")


def _parse_errors():
    from app.design.services.material.parametric import MaterialFitError
    from app.design.services.validation.sensors import SensorError
    return (MaterialFitError, SensorError, ValueError, KeyError, json.JSONDecodeError)


@bp.route('/experiments/preview', methods=['POST'])
def preview_experiment():
    fields, text, _, _ = _form()
    try:
        _, preview = _parse(fields.get('test_type', 'tensile'), fields, text)
    except _parse_errors() as e:
        return jsonify({'error': str(e)}), 422
    return jsonify(_finite(preview)), 200


def _exp_dict(e: ExperimentalRecord, full: bool = False) -> dict:
    d = {'id': str(e.id), 'test_type': e.test_type, 'label': TEST_TYPES.get(e.test_type, e.test_type),
         'graph_id': str(e.graph_id) if e.graph_id else None,
         'material_id': str(e.material_id) if e.material_id else None,
         'conditions': e.conditions or {}, 'scalar_summary': e.scalar_summary or {}, 'source': e.source,
         'description': e.description, 'file_ref': e.file_ref,
         'created_at': e.created_at.isoformat() if e.created_at else None}
    if full:
        d['raw_data'] = e.raw_data or {}
    return _finite(d)


def _tensile_summary(raw: dict) -> dict:
    from app.design.services.material.parametric import ParametricMaterialModel
    r = ParametricMaterialModel().fit({'strain': raw['strain'], 'stress': raw['stress']})
    P = r['parameters']
    return {'best_model': r['best_model'], 'label': r['label'], 'r_squared': r['r_squared'],
            'E': P.get('E', {}).get('value'), 'E_std': P.get('E', {}).get('std'),
            'sigma_y': (P.get('sigma_02') or {}).get('value'), 'sigma_y_std': (P.get('sigma_02') or {}).get('std'),
            'uts': r['properties']['uts']['value'], 'uniform_elongation': r['properties']['uniform_elongation']['value'],
            'notes': r['specimens'][0]['notes']}


@bp.route('/experiments', methods=['POST'])
def create_experiment():
    """multipart: file, test_type, graph_id, material_id, temperature_c, strain_rate, load_factor,
    description, source, calibrate (1 → recalibrate/correlate right away), mode (replace|bayes)."""
    fields, text, filename, raw_bytes = _form()
    test_type = fields.get('test_type', 'tensile')
    if test_type not in TEST_TYPES:
        return jsonify({'error': f"test_type debe ser {' | '.join(TEST_TYPES)}"}), 422
    graph_id = _uuid_or_none(fields.get('graph_id'))
    material_id = _uuid_or_none(fields.get('material_id'))
    if test_type == 'structural' and not graph_id:
        return jsonify({'error': 'Un ensayo estructural pertenece a un estudio (graph_id).'}), 422
    try:
        raw, preview = _parse(test_type, fields, text)
        summary = _tensile_summary(raw) if test_type == 'tensile' else {
            'n_sensors': preview['n_points'], 'quantities': {k: v['n'] for k, v in preview['quantities'].items()}}
    except _parse_errors() as e:
        return jsonify({'error': str(e)}), 422
    cond = fields.get('conditions')
    if isinstance(cond, str):
        try:
            cond = json.loads(cond)
        except json.JSONDecodeError:
            cond = {}
    cond = dict(cond or {})
    for k in ('temperature_c', 'strain_rate', 'load_factor'):
        if _num(fields.get(k)) is not None:
            cond[k] = _num(fields.get(k))
    exp = ExperimentalRecord(id=_uuid.uuid4(), graph_id=graph_id, material_id=material_id, test_type=test_type,
                             conditions=cond, raw_data=_finite(raw), scalar_summary=_finite(summary),
                             source=fields.get('source') or 'user', description=fields.get('description'))
    if raw_bytes:
        d = os.path.join(str(current_app.config.get('DATA_DIR', 'data')), 'experiments', str(exp.id))
        os.makedirs(d, exist_ok=True)
        name = os.path.basename(filename or 'data.csv') or 'data.csv'
        with open(os.path.join(d, name), 'wb') as fh:
            fh.write(raw_bytes)
        exp.file_ref = f'experiments/{exp.id}/{name}'
    db.session.add(exp)
    db.session.commit()
    out = {'experiment': _exp_dict(exp), 'preview': _finite(preview)}
    if str(fields.get('calibrate', '')).lower() in ('1', 'true', 'yes'):
        if test_type == 'tensile' and (material_id or graph_id):
            body, code = _recalibrate_tensile(exp, graph_id, fields.get('mode', 'replace'), apply=True)
            out['recalibration'] = body
            out['recalibration_status'] = code
        elif test_type == 'structural':
            body, code = _correlate_structural(exp, str(graph_id), fields.get('run_id'))
            out['correlation'] = body
            out['correlation_status'] = code
    return jsonify(out), 201


@bp.route('/experiments', methods=['GET'])
def list_experiments():
    q = ExperimentalRecord.query
    for k in ('graph_id', 'material_id'):
        if request.args.get(k):
            q = q.filter(getattr(ExperimentalRecord, k) == _uuid_or_none(request.args[k]))
    if request.args.get('test_type'):
        q = q.filter(ExperimentalRecord.test_type == request.args['test_type'])
    rows = q.order_by(ExperimentalRecord.created_at.desc()).limit(200).all()
    return jsonify({'experiments': [_exp_dict(e) for e in rows]}), 200


@bp.route('/experiments/<string:experiment_id>', methods=['GET'])
def get_experiment(experiment_id):
    e = _get(ExperimentalRecord, experiment_id)
    if e is None:
        return jsonify({'error': 'Experiment not found'}), 404
    corr = SimExperimentCorrelation.query.filter_by(experiment_id=e.id).order_by(
        SimExperimentCorrelation.created_at.desc()).all()
    return jsonify({**_exp_dict(e, full=True), 'correlations': [_corr_dict(c) for c in corr]}), 200


@bp.route('/experiments/<string:experiment_id>', methods=['DELETE'])
def delete_experiment(experiment_id):
    e = _get(ExperimentalRecord, experiment_id)
    if e is None:
        return jsonify({'error': 'Experiment not found'}), 404
    SimExperimentCorrelation.query.filter_by(experiment_id=e.id).delete()
    db.session.delete(e)
    db.session.commit()
    import shutil
    shutil.rmtree(os.path.join(str(current_app.config.get('DATA_DIR', 'data')), 'experiments', str(e.id)),
                  ignore_errors=True)
    return jsonify({'deleted': experiment_id}), 200


# ── Correlation ───────────────────────────────────────────────────────────────

def _corr_dict(c: SimExperimentCorrelation, details: bool = True) -> dict:
    d = {'id': str(c.id), 'kind': c.kind, 'run_id': str(c.run_id) if c.run_id else None,
         'experiment_id': str(c.experiment_id), 'graph_id': str(c.graph_id) if c.graph_id else None,
         'material_id': str(c.material_id) if c.material_id else None, 'r2': c.correlation_r2,
         'max_relative_error': c.max_relative_error, 'field_compared': c.field_compared,
         'confidence_factor': c.confidence_factor, 'recalibration_delta': c.recalibration_delta,
         'created_at': c.created_at.isoformat() if c.created_at else None}
    if details:
        d['details'] = c.details
    return _finite(d)


def _latest_run(graph_id, run_id=None):
    from app.design.models.simulation import SimulationRun
    if run_id:
        run = _get(SimulationRun, run_id)
        return run if run is not None and str(run.graph_id) == str(graph_id) else None
    return (SimulationRun.query.filter(SimulationRun.graph_id == _uuid_or_none(graph_id),
                                       SimulationRun.status == 'done',
                                       SimulationRun.purpose.in_(('run', 'reproduce')))
            .order_by(SimulationRun.created_at.desc()).first())


def _structural_comparison(exp: ExperimentalRecord, run) -> dict:
    """Sensors of a structural experiment vs a finished run (interpolated in the elements)."""
    import h5py
    from app.design.services.validation.sensors import MeshProbe, simulate_sensors
    from app.design.services.validation.correlator import correlation_metrics
    path = os.path.join(str(current_app.config.get('SOLVER_DATA_DIR', 'data/solver')), f'{run.id}.h5')
    if not os.path.exists(path):
        raise FileNotFoundError('El run no tiene archivo de resultados.')
    with h5py.File(path, 'r') as f:
        nodes, elements = f['nodes'][:], f['elements'][:]
        u = f['fields/displacement/step_0'][:]
    sensors = (exp.raw_data or {}).get('sensors') or []
    lf = float((exp.conditions or {}).get('load_factor') or 1.0)
    sim = simulate_sensors(MeshProbe(nodes, elements), u, sensors, lf)
    m = np.array([s['value'] for s in sensors])
    s = sim['simulated']
    groups = {}
    for q in sorted({x['quantity'] for x in sensors}):
        idx = [i for i, x in enumerate(sensors) if x['quantity'] == q]
        groups[q] = correlation_metrics(m[idx], s[idx])
    # one global metric: each group normalized by its own scale so mm and µε can be pooled
    from app.design.services.validation.correlator import group_scales
    scale = group_scales(m, [x['quantity'] for x in sensors])
    overall = correlation_metrics(m / scale, s / scale)
    rows = [{**x, 'simulated': float(s[i]), 'error': float(s[i] - m[i]),
             'rel_error': float(abs(s[i] - m[i]) / max(abs(m[i]), 0.05 * scale[i])),
             'distance_mm': float(sim['distance_mm'][i]), 'outside': bool(sim['outside'][i])}
            for i, x in enumerate(sensors)]
    return {'overall': overall, 'groups': groups, 'sensors': rows, 'load_factor': lf,
            'mesh_h_mm': sim['mesh_h_mm'], 'E_run': float(((run.solver_config or {}).get('material') or {}).get('E', 0)),
            'n_outside': int(sim['outside'].sum())}


def _correlate_structural(exp, graph_id, run_id=None):
    run = _latest_run(graph_id, run_id)
    if run is None:
        return {'error': 'El estudio no tiene una simulación terminada con la que comparar.'}, 409
    try:
        comp = _structural_comparison(exp, run)
    except FileNotFoundError as e:
        return {'error': str(e)}, 409
    ov = comp['overall']
    fields = '+'.join(sorted(comp['groups']))
    c = SimExperimentCorrelation(id=_uuid.uuid4(), kind='structural', run_id=run.id, experiment_id=exp.id,
                                 graph_id=_uuid_or_none(graph_id), material_id=_material_id_of_graph(graph_id),
                                 correlation_r2=ov['r2'], max_relative_error=ov['max_rel_error'],
                                 field_compared=fields, confidence_factor=ov['confidence_factor'],
                                 details=_finite(comp))
    db.session.add(c)
    db.session.commit()
    return _corr_dict(c), 200


def _material_id_of_graph(graph_id):
    from app.design.models.graph import DesignNode
    n = (DesignNode.query.filter_by(graph_id=_uuid_or_none(graph_id), node_type='MATERIAL')
         .order_by(DesignNode.created_at, DesignNode.id).first())
    return _uuid_or_none((n.properties or {}).get('material_id')) if n else None


def _material_comparison(exp, material):
    from app.design.services.material.parametric import prepare_curve, ParametricMaterialModel
    from app.design.services.validation.recalibrator import predict_material_curve
    from app.design.services.validation.correlator import correlation_metrics
    raw = exp.raw_data or {}
    pm = ParametricMaterialModel()
    pm.fit({'strain': raw['strain'], 'stress': raw['stress']})          # toe offset of this test
    c = pm.specimens[0]
    e0 = c.get('strain_offset', 0.0)
    pred, label = predict_material_curve(material, c['strain'], e0)
    met = correlation_metrics(c['stress'], pred)
    return met, {'model': label, 'strain': (c['strain'] - e0).tolist(), 'measured': c['stress'].tolist(),
                 'predicted': pred.tolist()}


@bp.route('/<string:graph_id>/correlate', methods=['POST'])
def correlate(graph_id):
    """Body: {experiment_id, run_id?}. Structural → sensors vs run; tensile → test vs material model."""
    from app.design.models.material import MaterialModel
    body = request.get_json(silent=True) or {}
    exp = _get(ExperimentalRecord, body.get('experiment_id'))
    if exp is None:
        return jsonify({'error': 'Experiment not found'}), 404
    if exp.test_type == 'structural':
        out, code = _correlate_structural(exp, graph_id, body.get('run_id'))
        return jsonify(out), code
    mat = _get(MaterialModel, exp.material_id) or _get(MaterialModel, _material_id_of_graph(graph_id))
    if mat is None:
        return jsonify({'error': 'El ensayo no está ligado a un material de la biblioteca.'}), 422
    met, curve = _material_comparison(exp, mat)
    c = SimExperimentCorrelation(id=_uuid.uuid4(), kind='material', run_id=None, experiment_id=exp.id,
                                 graph_id=_uuid_or_none(graph_id), material_id=mat.id, correlation_r2=met['r2'],
                                 max_relative_error=met['max_rel_error'], field_compared='stress_strain',
                                 confidence_factor=met['confidence_factor'],
                                 details=_finite({'overall': met, 'curve': curve}))
    db.session.add(c)
    db.session.commit()
    return jsonify(_corr_dict(c)), 200


@bp.route('/<string:graph_id>/correlations', methods=['GET'])
def list_correlations(graph_id):
    rows = (SimExperimentCorrelation.query.filter(SimExperimentCorrelation.graph_id == _uuid_or_none(graph_id))
            .order_by(SimExperimentCorrelation.created_at.desc()).limit(100).all())
    return jsonify({'correlations': [_corr_dict(c, details=False) for c in rows]}), 200


@bp.route('/correlations/<string:correlation_id>', methods=['GET'])
def get_correlation(correlation_id):
    c = _get(SimExperimentCorrelation, correlation_id)
    if c is None:
        return jsonify({'error': 'Correlation not found'}), 404
    return jsonify(_corr_dict(c)), 200


@bp.route('/<string:graph_id>/confidence', methods=['GET'])
def confidence(graph_id):
    """Confidence factor before simulating + similar correlated cases + recommended tests."""
    from app.design.services.validation.correlator import SimulationCorrelator
    from app.design.services.graph_to_solver_spec import GraphSpecError
    sc = SimulationCorrelator()
    try:
        similar = sc.find_similar_runs(graph_id, top_k=int(request.args.get('top_k', 5)))
    except GraphSpecError as e:
        return jsonify({'error': str(e), 'kind': 'graph_spec'}), 422
    conf = sc.compute_confidence_factor(similar)
    rec = sc.recommend_validation_test(graph_id)
    level = ('sin historial' if not similar else 'alta' if conf >= 0.6 else 'media' if conf >= 0.3 else 'baja')
    return jsonify(_finite({'graph_id': graph_id, 'confidence_factor': conf, 'level': level,
                            'similar_runs': similar, **rec})), 200


# ── Recalibration ─────────────────────────────────────────────────────────────

def _recalibrate_tensile(exp, graph_id, mode: str, apply: bool):
    from app.design.models.material import MaterialModel
    from app.design.services.validation.recalibrator import ModelRecalibrator, history_entry
    from app.design.api.material_routes import apply_fit_to_material, sync_material_nodes, _mat_dict
    mat = _get(MaterialModel, exp.material_id) or (_get(MaterialModel, _material_id_of_graph(graph_id))
                                                  if graph_id else None)
    if mat is None:
        return {'error': 'El ensayo no está ligado a un material: elige uno de la biblioteca.'}, 422
    if mode not in ('replace', 'bayes'):
        return {'error': "mode debe ser 'replace' o 'bayes'"}, 422
    raw = exp.raw_data or {}
    try:
        r = ModelRecalibrator().tensile(mat, raw['strain'], raw['stress'], mode)
    except (ValueError, KeyError) as e:
        return {'error': str(e)}, 422
    out = {'material_id': str(mat.id), 'material_name': mat.name, 'mode': mode, 'applied': apply,
           'model_before': r['model_before'], 'model_after': r['fit']['label'],
           'before': {k: v for k, v in r['before'].items() if k != 'relative_errors'},
           'after': {k: v for k, v in r['after'].items() if k != 'relative_errors'},
           'delta': r['delta'], 'new_parameters': r['new_parameters'], 'curve': r['curve']}
    if apply:
        pm = r['pm']
        entry = history_entry(exp.id, r['delta'], mode, r['before'], r['after'])
        apply_fit_to_material(mat, r['fit'], pm.best, r['new_parameters'])
        mat.calibration = {**mat.calibration, 'history': (mat.calibration.get('history') or []) + [_finite(entry)],
                           'last_experiment_id': str(exp.id)}
        if exp.material_id is None:
            exp.material_id = mat.id
        c = SimExperimentCorrelation(id=_uuid.uuid4(), kind='material', run_id=None, experiment_id=exp.id,
                                     graph_id=_uuid_or_none(graph_id), material_id=mat.id,
                                     correlation_r2=r['before']['r2'], max_relative_error=r['before']['max_rel_error'],
                                     field_compared='stress_strain',
                                     confidence_factor=r['before']['confidence_factor'],
                                     recalibration_delta=_finite(r['delta']),
                                     details=_finite({'overall': r['before'], 'after': r['after'], 'curve': r['curve'],
                                                      'mode': mode}))
        db.session.add(c)
        db.session.commit()
        out['synced_nodes'] = sync_material_nodes(mat)
        out['correlation_id'] = str(c.id)
        out['material'] = _mat_dict(mat, full=False)
    return _finite(out), 200


def _recalibrate_structural(exp, graph_id, body, apply: bool):
    from app.design.models.graph import DesignNode
    from app.design.services.graph_service import DesignGraphService
    from app.design.services.validation.recalibrator import ModelRecalibrator
    run = _latest_run(graph_id, body.get('run_id'))
    if run is None:
        return {'error': 'El estudio no tiene una simulación terminada con la que comparar.'}, 409
    try:
        comp = _structural_comparison(exp, run)
    except FileNotFoundError as e:
        return {'error': str(e)}, 409
    sens = comp['sensors']
    E_run = comp['E_run']
    std = [x.get('std') for x in sens]
    try:
        r = ModelRecalibrator.structural_stiffness([x['simulated'] for x in sens], [x['value'] for x in sens], E_run,
                                                   std if all(v for v in std) else None,
                                                   groups=[x['quantity'] for x in sens])
    except ValueError as e:
        return {'error': str(e)}, 422
    delta = {'E': {'old': E_run, 'new': r['E_new'], 'rel_change': r['rel_change'], 'new_std': r['E_std'],
                   'kind': 'effective'}}
    warn = None
    if r['after']['r2'] < 0.9 or r['after']['max_rel_error'] > 0.15:
        warn = ('Tras corregir la rigidez la correlación sigue siendo pobre (R² < 0.9 o error > 15 %): la diferencia '
                'no es (solo) de E; '
                'revisa condiciones de contorno, cargas o la posición/orientación de los sensores.')
    out = {'mode': 'effective_stiffness', 'applied': apply, 'run_id': str(run.id), 'E_run': E_run,
           'E_new': r['E_new'], 'E_std': r['E_std'], 'slope': r['k'], 'delta': delta, 'warning': warn,
           'before': {k: v for k, v in r['before'].items() if k != 'relative_errors'},
           'after': {k: v for k, v in r['after'].items() if k != 'relative_errors'},
           'sensors': [{**x, 'simulated_after': v} for x, v in zip(sens, r['simulated_after'])]}
    if apply:
        node = (DesignNode.query.filter_by(graph_id=_uuid_or_none(graph_id), node_type='MATERIAL')
                .order_by(DesignNode.created_at, DesignNode.id).first())
        if node is None:
            return {'error': 'El estudio no tiene nodo MATERIAL.'}, 422
        props = dict(node.properties or {})
        props['E'] = r['E_new']
        if r['E_std']:
            props['E_std'] = r['E_std']
        props['E_source'] = f'identificado del ensayo {str(exp.id)[:8]} (E efectivo)'
        DesignGraphService().update_node(graph_id, node.id, {'properties': _finite(props)})
        c = SimExperimentCorrelation(id=_uuid.uuid4(), kind='structural', run_id=run.id, experiment_id=exp.id,
                                     graph_id=_uuid_or_none(graph_id), material_id=_material_id_of_graph(graph_id),
                                     correlation_r2=comp['overall']['r2'],
                                     max_relative_error=comp['overall']['max_rel_error'],
                                     field_compared='+'.join(sorted(comp['groups'])),
                                     confidence_factor=comp['overall']['confidence_factor'],
                                     recalibration_delta=_finite(delta),
                                     details=_finite({**comp, 'after': r['after']}))
        db.session.add(c)
        db.session.commit()
        out['node_id'] = str(node.id)
        out['correlation_id'] = str(c.id)
    return _finite(out), 200


@bp.route('/<string:graph_id>/recalibrate', methods=['POST'])
def recalibrate(graph_id):
    """Body: {experiment_id, mode: replace|bayes (tensile), apply: true, run_id?}."""
    body = request.get_json(silent=True) or {}
    exp = _get(ExperimentalRecord, body.get('experiment_id'))
    if exp is None:
        return jsonify({'error': 'Experiment not found'}), 404
    apply = bool(body.get('apply', True))
    if exp.test_type == 'tensile':
        out, code = _recalibrate_tensile(exp, graph_id, body.get('mode', 'replace'), apply)
    else:
        out, code = _recalibrate_structural(exp, graph_id, body, apply)
    return jsonify(out), code
