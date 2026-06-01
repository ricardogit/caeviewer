"""Design Graph API — full CRUD for DesignGraph, DesignNode, DesignEdge.

FASE 1 — complete implementation.
"""
import logging
from flask import Blueprint, jsonify, request
from app.extensions import db
from app.design.models.graph import DesignGraph, DesignNode, DesignEdge
from app.design.services.graph_service import DesignGraphService, VALID_NODE_TYPES, VALID_EDGE_TYPES

logger = logging.getLogger(__name__)
bp = Blueprint('design_graph', __name__)
_svc = DesignGraphService()


# ── Health ────────────────────────────────────────────────────────────────────

@bp.route('/status', methods=['GET'])
def status():
    try:
        total = DesignGraph.query.count()
    except Exception:
        total = None
    return jsonify({
        'module': 'design.graph',
        'status': 'ok',
        'total_graphs': total,
        'node_types': sorted(VALID_NODE_TYPES),
        'edge_types': sorted(VALID_EDGE_TYPES),
    }), 200


# ── DesignGraph CRUD ──────────────────────────────────────────────────────────

@bp.route('/', methods=['POST'])
def create_graph():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400

    tier = int(data.get('tier', 1))
    if tier not in (0, 1, 2, 3):
        return jsonify({'error': 'tier must be 0-3'}), 400

    graph = DesignGraph(
        name=name,
        description=data.get('description', ''),
        tier=tier,
        status='draft',
        meta=data.get('metadata', {}),
    )
    db.session.add(graph)
    db.session.flush()   # assign id before hash computation

    graph.hash = _svc.compute_graph_hash(str(graph.id))
    db.session.commit()

    return jsonify(_graph_summary(graph)), 201


@bp.route('/', methods=['GET'])
def list_graphs():
    try:
        graphs = DesignGraph.query.order_by(DesignGraph.created_at.desc()).all()
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
    return jsonify({
        'graphs': [_graph_summary(g) for g in graphs],
        'total': len(graphs),
    }), 200


@bp.route('/<string:graph_id>', methods=['GET'])
def get_graph(graph_id):
    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404

    rf = _svc.to_reactflow_format(graph_id)
    return jsonify({
        **_graph_summary(graph),
        'nodes': rf['nodes'],
        'edges': rf['edges'],
    }), 200


@bp.route('/<string:graph_id>', methods=['PUT'])
def update_graph(graph_id):
    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404

    data = request.get_json(silent=True) or {}
    if 'name' in data and data['name'].strip():
        graph.name = data['name'].strip()
    if 'description' in data:
        graph.description = data['description']
    if 'status' in data and data['status'] in ('draft', 'simulating', 'optimizing', 'validated'):
        graph.status = data['status']
    if 'tier' in data and int(data['tier']) in (0, 1, 2, 3):
        graph.tier = int(data['tier'])
    if 'metadata' in data:
        graph.meta = data['metadata']

    graph.version += 1
    graph.hash = _svc.compute_graph_hash(graph_id)
    db.session.commit()
    return jsonify(_graph_summary(graph)), 200


@bp.route('/<string:graph_id>', methods=['DELETE'])
def delete_graph(graph_id):
    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404

    db.session.delete(graph)
    db.session.commit()
    return jsonify({'success': True, 'deleted_id': graph_id}), 200


# ── Nodes ─────────────────────────────────────────────────────────────────────

@bp.route('/<string:graph_id>/nodes', methods=['POST'])
def add_node(graph_id):
    if not DesignGraph.query.filter_by(id=graph_id).first():
        return jsonify({'error': 'Graph not found'}), 404

    data = request.get_json(silent=True) or {}
    node_type = (data.get('node_type') or '').upper()
    label = (data.get('label') or '').strip()

    if not node_type or node_type not in VALID_NODE_TYPES:
        return jsonify({'error': f'node_type must be one of {sorted(VALID_NODE_TYPES)}'}), 400
    if not label:
        return jsonify({'error': 'label is required'}), 400

    try:
        node = _svc.add_node(
            graph_id=graph_id,
            node_type=node_type,
            label=label,
            properties=data.get('properties', {}),
            level=int(data.get('level', 0)),
            pos_x=float(data.get('pos_x', 0.0)),
            pos_y=float(data.get('pos_y', 0.0)),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'node_id': str(node.id),
        'node_type': node.node_type,
        'label': node.label,
        'level': node.level,
        'pos_x': node.pos_x,
        'pos_y': node.pos_y,
        'properties': node.properties,
        'created_at': node.created_at.isoformat(),
    }), 201


@bp.route('/<string:graph_id>/nodes/<string:node_id>', methods=['PUT'])
def update_node(graph_id, node_id):
    data = request.get_json(silent=True) or {}
    try:
        node = _svc.update_node(graph_id, node_id, data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404

    return jsonify({
        'node_id': str(node.id),
        'label': node.label,
        'level': node.level,
        'properties': node.properties,
        'pos_x': node.pos_x,
        'pos_y': node.pos_y,
        'updated_at': node.updated_at.isoformat(),
    }), 200


@bp.route('/<string:graph_id>/nodes/<string:node_id>', methods=['DELETE'])
def delete_node(graph_id, node_id):
    try:
        _svc.delete_node(graph_id, node_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify({'success': True, 'deleted_node_id': node_id}), 200


# ── Edges ─────────────────────────────────────────────────────────────────────

@bp.route('/<string:graph_id>/edges', methods=['POST'])
def add_edge(graph_id):
    if not DesignGraph.query.filter_by(id=graph_id).first():
        return jsonify({'error': 'Graph not found'}), 404

    data = request.get_json(silent=True) or {}
    source_id  = data.get('source_id', '')
    target_id  = data.get('target_id', '')
    edge_type  = (data.get('edge_type') or '').upper()

    if not source_id or not target_id:
        return jsonify({'error': 'source_id and target_id are required'}), 400
    if edge_type not in VALID_EDGE_TYPES:
        return jsonify({'error': f'edge_type must be one of {sorted(VALID_EDGE_TYPES)}'}), 400

    # Validate nodes belong to this graph
    for nid, role in [(source_id, 'source'), (target_id, 'target')]:
        if not DesignNode.query.filter_by(id=nid, graph_id=graph_id).first():
            return jsonify({'error': f'{role} node {nid} not found in graph'}), 404

    try:
        edge = _svc.add_edge(
            graph_id=graph_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            weight=float(data.get('weight', 1.0)),
            properties=data.get('properties', {}),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'edge_id': str(edge.id),
        'source_id': str(edge.source_id),
        'target_id': str(edge.target_id),
        'edge_type': edge.edge_type,
        'weight': edge.weight,
        'created_at': edge.created_at.isoformat(),
    }), 201


@bp.route('/<string:graph_id>/edges/<string:edge_id>', methods=['DELETE'])
def delete_edge(graph_id, edge_id):
    try:
        _svc.delete_edge(graph_id, edge_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify({'success': True, 'deleted_edge_id': edge_id}), 200


# ── Graph utilities ───────────────────────────────────────────────────────────

@bp.route('/<string:graph_id>/validate', methods=['GET'])
def validate_graph(graph_id):
    if not DesignGraph.query.filter_by(id=graph_id).first():
        return jsonify({'error': 'Graph not found'}), 404

    errors = _svc.validate_completeness(graph_id)
    has_errors = any(e['severity'] == 'error' for e in errors)

    return jsonify({
        'graph_id': graph_id,
        'ready_for_simulation': not has_errors,
        'errors': errors,
        'error_count': sum(1 for e in errors if e['severity'] == 'error'),
        'warning_count': sum(1 for e in errors if e['severity'] == 'warning'),
    }), 200


@bp.route('/<string:graph_id>/dependency-order', methods=['GET'])
def dependency_order(graph_id):
    if not DesignGraph.query.filter_by(id=graph_id).first():
        return jsonify({'error': 'Graph not found'}), 404
    order = _svc.compute_dependency_order(graph_id)
    return jsonify({'graph_id': graph_id, 'order': order}), 200


@bp.route('/<string:graph_id>/dag-check', methods=['GET'])
def dag_check(graph_id):
    """Phase 2: Check if graph is a valid DAG (no cycles)."""
    if not DesignGraph.query.filter_by(id=graph_id).first():
        return jsonify({'error': 'Graph not found'}), 404

    result = _svc.check_dag_validity(graph_id)
    return jsonify({
        'graph_id': graph_id,
        'is_dag': result['is_dag'],
        'cycles': result['cycles'],
        'message': '✓ Grafo es DAG válido' if result['is_dag'] else f'⚠️ {len(result["cycles"])} ciclo(s) detectado(s)',
    }), 200


@bp.route('/<string:graph_id>/export/jsonld', methods=['GET'])
def export_jsonld(graph_id):
    return jsonify({'error': 'Not implemented — FASE 7'}), 501


# ── Import from existing modules ──────────────────────────────────────────────

@bp.route('/<string:graph_id>/import/step', methods=['POST'])
def import_step_geometry(graph_id):
    """Create a GEOMETRY node from an existing STEP file in step_view_pro."""
    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404

    data = request.get_json(silent=True) or {}
    step_file_id = data.get('step_file_id') or data.get('header_id')
    if not step_file_id:
        return jsonify({'error': 'step_file_id is required'}), 400

    try:
        from app.step_view_pro.models import STEPFile
        step_file = STEPFile.query.filter_by(id=step_file_id).first()
        label = step_file.original_filename if step_file else f'STEP:{step_file_id[:8]}'
    except Exception:
        label = f'STEP:{str(step_file_id)[:8]}'

    node = _svc.add_node(
        graph_id=graph_id,
        node_type='GEOMETRY',
        label=label,
        properties={'source': 'step_viewer', 'step_file_id': str(step_file_id)},
        level=2,
        pos_x=float(data.get('pos_x', 200.0)),
        pos_y=float(data.get('pos_y', 150.0)),
    )
    return jsonify({'node_id': str(node.id), 'label': node.label}), 201


@bp.route('/<string:graph_id>/import/mesh', methods=['POST'])
def import_cae_mesh(graph_id):
    """Create a GEOMETRY node from an existing CAE mesh."""
    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404

    data = request.get_json(silent=True) or {}
    mesh_id = data.get('mesh_id')
    if not mesh_id:
        return jsonify({'error': 'mesh_id is required'}), 400

    try:
        from app.cae.models import CAEMesh
        mesh = CAEMesh.query.filter_by(id=mesh_id).first()
        label = mesh.original_filename if mesh else f'Mesh:{str(mesh_id)[:8]}'
        props = {
            'source': 'cae_viewer', 'mesh_id': str(mesh_id),
            'node_count': getattr(mesh, 'node_count', None),
            'element_count': getattr(mesh, 'element_count', None),
        }
    except Exception:
        label = f'Mesh:{str(mesh_id)[:8]}'
        props = {'source': 'cae_viewer', 'mesh_id': str(mesh_id)}

    node = _svc.add_node(
        graph_id=graph_id,
        node_type='GEOMETRY',
        label=label,
        properties=props,
        level=2,
        pos_x=float(data.get('pos_x', 200.0)),
        pos_y=float(data.get('pos_y', 150.0)),
    )
    return jsonify({'node_id': str(node.id), 'label': node.label}), 201


# ── Helper ────────────────────────────────────────────────────────────────────

def _graph_summary(graph) -> dict:
    return {
        'id': str(graph.id),
        'name': graph.name,
        'description': graph.description or '',
        'version': graph.version,
        'tier': graph.tier,
        'status': graph.status,
        'hash': graph.hash or '',
        'created_at': graph.created_at.isoformat(),
        'updated_at': graph.updated_at.isoformat(),
    }
