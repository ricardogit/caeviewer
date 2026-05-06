"""
Graph API Routes - Endpoints para navegación completa del grafo de entidades STEP
Versión expandida con GraphBuilder
Autor: STEP Benchmark Team
Versión: 2.0.0
"""

from flask import Blueprint, jsonify, request
import logging
import os

from app.step_view_pro.models import STEPFileHeader, STEPEntity
from app.models import Part
from app.extensions import db
from app.step_view_pro.backend.graph_builder import GraphBuilder

logger = logging.getLogger(__name__)
bp = Blueprint('graph_api', __name__)


@bp.route('/<string:header_id>/tree', methods=['GET'])
def get_entity_tree(header_id):
    """
    Obtiene árbol jerárquico de entidades (paginado y con límite de profundidad)

    Query Params:
        force_recompute (bool): Forzar recomputación del árbol
        max_depth (int): Niveles máximos de profundidad (default 3)
        limit (int): Máximo de nodos a devolver (default 300)
    """
    from app.step_view_pro.models import STEPFileHeader, STEPEntity
    force_recompute = request.args.get('force_recompute', 'false').lower() == 'true'
    max_depth = int(request.args.get('max_depth', 3))
    limit = min(int(request.args.get('limit', 300)), 1000)

    logger.info(f"GET /graph/{header_id}/tree depth={max_depth} limit={limit}")

    try:
        # Check if header exists
        header = STEPFileHeader.query.get(header_id)
        if not header:
            return jsonify({'error': 'Header not found'}), 404

        # Use cached tree if available and not forcing recompute
        if not force_recompute and header.entity_tree_json:
            return jsonify(header.entity_tree_json), 200

        # Count entities first — skip expensive CTE for large files
        total = STEPEntity.query.filter_by(header_id=header_id).count()

        if total > 2000:
            # Large file: return roots only; frontend expands children on demand
            roots = STEPEntity.query.filter_by(
                header_id=header_id, is_root=True
            ).limit(limit).all()

            nodes = [{
                'entity_id': e.entity_id,
                'entity_type': e.entity_type,
                'entity_label': e.entity_label or '',
                'entity_category': e.entity_category or 'unknown',
                'manufacturing_feature': e.manufacturing_feature,
                'is_root': True,
                'is_leaf': e.is_leaf,
                'depth_level': 0,
                'has_children': bool(e.references_to),
                'children': [],
            } for e in roots]

            return jsonify({
                'roots': nodes,
                'metadata': {
                    'total_nodes': total,
                    'displayed_nodes': len(nodes),
                    'truncated': True,
                    'lazy': True,
                    'message': f'Archivo grande ({total} entidades). Expansión bajo demanda.',
                }
            }), 200

        # Small file: use GraphBuilder
        builder = GraphBuilder(header_id)
        tree = builder.compute_entity_tree(use_cache=not force_recompute)
        if force_recompute:
            builder.save_tree_to_cache(tree)
        return jsonify(tree), 200

    except ValueError as e:
        logger.warning(f"Header no encontrado: {e}")
        return jsonify({'error': str(e)}), 404

    except Exception as e:
        logger.exception(f"Error obteniendo árbol: {e}")
        return jsonify({'error': f'Error interno: {str(e)}'}), 500


@bp.route('/<string:header_id>/entity/<int:entity_id>', methods=['GET'])
def get_entity_details(header_id, entity_id):
    """
    Obtiene detalles completos de una entidad específica

    Returns:
        JSON con todos los campos de la entidad
    """
    logger.info(f"GET /graph/{header_id}/entity/{entity_id}")

    try:
        entity = STEPEntity.query.filter_by(
            header_id=header_id,
            entity_id=entity_id
        ).first()

        if not entity:
            return jsonify({'error': 'Entidad no encontrada'}), 404

        return jsonify({
            'entity_id': entity.entity_id,
            'entity_type': entity.entity_type,
            'entity_label': entity.entity_label,
            'attributes': entity.entity_attributes,
            'references_to': entity.references_to or [],
            'referenced_by': entity.referenced_by or [],
            'depth_level': entity.depth_level,
            'is_leaf': entity.is_leaf,
            'is_root': entity.is_root,
            'manufacturing_feature': entity.manufacturing_feature,
            'entity_category': entity.entity_category,
            'bounding_box': entity.bounding_box,
            'geometric_properties': getattr(entity, 'geometric_properties', None),
            'raw_line': entity.raw_line
        }), 200

    except Exception as e:
        logger.exception(f"Error obteniendo entidad {entity_id}: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/entity/<int:entity_id>/path-to-root', methods=['GET'])
def get_path_to_root(header_id, entity_id):
    """
    Obtiene el camino desde una entidad hasta la raíz del grafo

    Returns:
        JSON con array de nodos desde la entidad hasta la raíz
    """
    logger.info(f"GET /graph/{header_id}/entity/{entity_id}/path-to-root")

    try:
        builder = GraphBuilder(header_id)
        path = builder.get_entity_path_to_root(entity_id)

        return jsonify({
            'path': path,
            'length': len(path)
        }), 200

    except Exception as e:
        logger.exception(f"Error obteniendo path: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/entity/<int:entity_id>/subtree', methods=['GET'])
def get_subtree(header_id, entity_id):
    """
    Obtiene subárbol desde una entidad específica

    Query Params:
        max_depth (int): Profundidad máxima (default: 5)

    Returns:
        JSON con subárbol desde esa entidad
    """
    max_depth = int(request.args.get('max_depth', 5))

    logger.info(f"GET /graph/{header_id}/entity/{entity_id}/subtree depth={max_depth}")

    try:
        builder = GraphBuilder(header_id)
        subtree = builder.get_subtree(entity_id, max_depth)

        return jsonify(subtree), 200

    except Exception as e:
        logger.exception(f"Error obteniendo subtree: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/entity/<int:entity_id>/neighbors', methods=['GET'])
def get_neighbors(header_id, entity_id):
    """
    Obtiene vecindario de una entidad (N-hop neighbors)

    Query Params:
        distance (int): Número de saltos (default: 1)

    Returns:
        JSON con:
            - center: Nodo central
            - neighbors: Array de vecinos
            - edges: Array de conexiones
    """
    distance = int(request.args.get('distance', 1))

    logger.info(f"GET /graph/{header_id}/entity/{entity_id}/neighbors distance={distance}")

    try:
        builder = GraphBuilder(header_id)
        neighborhood = builder.get_neighbors(entity_id, distance)

        return jsonify(neighborhood), 200

    except Exception as e:
        logger.exception(f"Error obteniendo neighbors: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/entity/<int:entity_id>/children', methods=['GET'])
def get_entity_children(header_id, entity_id):
    """
    Obtiene hijos directos de una entidad (para expansión lazy del árbol)

    Query Params:
        limit (int): Máximo de hijos (default 200, max 500)

    Returns:
        JSON con:
            - children: Array de nodos hijo directos
            - count: Cantidad devuelta
            - has_more: Si hay más hijos no devueltos
    """
    limit = min(int(request.args.get('limit', 200)), 500)
    logger.info(f"GET /graph/{header_id}/entity/{entity_id}/children limit={limit}")

    try:
        parent = STEPEntity.query.filter_by(
            header_id=header_id, entity_id=entity_id
        ).first()

        if not parent:
            return jsonify({'error': 'Entity not found'}), 404

        child_ids = parent.references_to or []
        if not child_ids:
            return jsonify({'children': [], 'count': 0, 'has_more': False}), 200

        children = STEPEntity.query.filter(
            STEPEntity.header_id == header_id,
            STEPEntity.entity_id.in_(child_ids[:limit])
        ).all()

        return jsonify({
            'children': [{
                'entity_id': c.entity_id,
                'entity_type': c.entity_type,
                'entity_label': c.entity_label or '',
                'entity_category': c.entity_category or 'unknown',
                'manufacturing_feature': c.manufacturing_feature,
                'is_root': c.is_root,
                'is_leaf': c.is_leaf,
                'depth_level': c.depth_level,
                'has_children': bool(c.references_to),
                'children': [],
            } for c in children],
            'count': len(children),
            'has_more': len(child_ids) > limit,
        }), 200

    except Exception as e:
        logger.exception(f"Error obteniendo hijos de entidad {entity_id}: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/entities/search', methods=['POST'])
def search_entities_global():
    """
    Busca entidades en todos los archivos con filtros

    Body:
        header_id (str): ID del header a buscar (requerido)
        query (str): Texto a buscar en tipo o label
        entity_type (str): Filtro por tipo exacto
        manufacturing_feature (str): Filtro por feature
        limit (int): Máximo de resultados (default: 100)

    Returns:
        JSON con:
            - results: Array de entidades encontradas
            - count: Número de resultados
    """
    data = request.get_json() or {}
    header_id = data.get('header_id')  # Extract header_id from request body
    query_str = data.get('query')
    entity_type = data.get('entity_type')
    manufacturing_feature = data.get('manufacturing_feature')
    limit = data.get('limit', 100)

    if not header_id:
        return jsonify({'error': 'header_id is required in request body'}), 400

    logger.info(f"POST /graph/entities/search for header {header_id} query='{query_str}' type={entity_type}")

    try:
        builder = GraphBuilder(header_id)
        results = builder.search_entities(
            query=query_str,
            entity_type=entity_type,
            manufacturing_feature=manufacturing_feature,
            limit=limit
        )

        return jsonify({
            'results': results,
            'count': len(results)
        }), 200

    except ValueError as e:
        logger.warning(f"Header no encontrado: {e}")
        return jsonify({'error': str(e)}), 404

    except Exception as e:
        logger.exception(f"Error en búsqueda global: {e}")
        return jsonify({'error': f'Error interno: {str(e)}'}), 500


@bp.route('/<string:header_id>/search', methods=['POST'])
def search_entities(header_id):
    """
    Busca entidades por múltiples criterios

    Body:
        query (str): Texto a buscar en tipo o label
        entity_type (str): Filtro por tipo exacto
        manufacturing_feature (str): Filtro por feature
        limit (int): Máximo de resultados (default: 100)

    Returns:
        JSON con:
            - results: Array de entidades encontradas
            - count: Número de resultados
    """
    data = request.get_json() or {}
    query_str = data.get('query')
    entity_type = data.get('entity_type')
    manufacturing_feature = data.get('manufacturing_feature')
    limit = data.get('limit', 100)

    logger.info(f"POST /graph/{header_id}/search query='{query_str}' type={entity_type}")

    try:
        builder = GraphBuilder(header_id)
        results = builder.search_entities(
            query=query_str,
            entity_type=entity_type,
            manufacturing_feature=manufacturing_feature,
            limit=limit
        )

        return jsonify({
            'results': results,
            'count': len(results)
        }), 200

    except Exception as e:
        logger.exception(f"Error en búsqueda: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/entities', methods=['GET'])
def get_entities_with_features(header_id):
    """
    Obtiene entidades con información de features

    Query Params:
        type (str): Filtro por tipo de entidad
        manufacturing_feature (str): Filtro por feature de manufactura
        limit (int): Límite de resultados (default: 100)
        offset (int): Offset para paginación (default: 0)

    Returns:
        JSON con:
            - entities: Array de entidades con features
            - total: Número total de entidades
            - manufacturing_features: Estadísticas de features
    """
    entity_type = request.args.get('type')
    manufacturing_feature = request.args.get('manufacturing_feature')
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    logger.info(f"GET /graph/{header_id}/entities type={entity_type} feature={manufacturing_feature}")

    try:
        # Validate header_id format (should be UUID)
        import uuid
        try:
            uuid.UUID(header_id)
            # If it's a valid UUID, continue as normal
            valid_header_id = header_id
        except ValueError:
            # If it's not a valid UUID, treat it as a file ID and try to find the corresponding header
            try:
                file_id = int(header_id)  # Attempt to convert to integer if it's a file ID
                step_file = Part.query.get(file_id)
                if step_file and step_file.graph_header_id:
                    valid_header_id = str(step_file.graph_header_id)
                else:
                    return jsonify({'error': f'Invalid header_id format or file not found: {header_id}'}), 400
            except ValueError:
                # If header_id is neither a valid UUID nor an integer
                return jsonify({'error': f'Invalid header_id format: {header_id}'}), 400

        # Verify that the header exists
        header = STEPFileHeader.query.filter_by(id=valid_header_id).first()
        if not header:
            return jsonify({'error': f'STEP file header not found: {valid_header_id}'}), 404

        # Construir query
        query = STEPEntity.query.filter_by(header_id=valid_header_id)

        if entity_type:
            query = query.filter_by(entity_type=entity_type)

        if manufacturing_feature:
            if manufacturing_feature.startswith('feature:'):
                # Remove the 'feature:' prefix for actual lookup
                actual_feature = manufacturing_feature[8:]
                query = query.filter_by(manufacturing_feature=actual_feature)
            else:
                query = query.filter_by(manufacturing_feature=manufacturing_feature)

        # Obtener total
        total = query.count()

        # Aplicar límites y offset
        entities = query.limit(limit).offset(offset).all()

        # Convertir a diccionario
        entities_list = []
        for entity in entities:
            entity_dict = {
                'id': str(entity.id),  # Convert UUID to string
                'entity_id': entity.entity_id,
                'entity_type': entity.entity_type,
                'entity_label': entity.entity_label,
                'reference_count': len(entity.references_to or []),
                'depth_level': entity.depth_level,
                'is_leaf': entity.is_leaf,
                'is_root': entity.is_root,
                'manufacturing_feature': entity.manufacturing_feature,
                'entity_category': entity.entity_category,
                'raw_line': entity.raw_line[:100] if hasattr(entity, 'raw_line') and entity.raw_line else None  # Limitar longitud
            }
            entities_list.append(entity_dict)

        return jsonify({
            'entities': entities_list,
            'total': total,
            'limit': limit,
            'offset': offset,
            'header_id': valid_header_id,
            'manufacturing_features': {
                'has_features': bool([e for e in entities if e.manufacturing_feature]),
                'feature_count': len([e for e in entities if e.manufacturing_feature]),
                'feature_types': list(set(e.manufacturing_feature for e in entities if e.manufacturing_feature))
            }
        }), 200

    except Exception as e:
        logger.exception(f"Error obteniendo entidades: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/file/<int:file_id>/entities', methods=['GET'])
def get_entities_by_file_id(file_id):
    """
    Obtiene entidades usando el ID de archivo en lugar del header UUID

    Query Params:
        type (str): Filtro por tipo de entidad
        manufacturing_feature (str): Filtro por feature de manufactura
        limit (int): Límite de resultados (default: 100)
        offset (int): Offset para paginación (default: 0)

    Returns:
        JSON con:
            - entities: Array de entidades con features
            - total: Número total de entidades
            - manufacturing_features: Estadísticas de features
    """
    entity_type = request.args.get('type')
    manufacturing_feature = request.args.get('manufacturing_feature')
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    logger.info(f"GET /graph/file/{file_id}/entities type={entity_type} feature={manufacturing_feature}")

    try:
        # Get the STEP file to find its header_id
        step_file = Part.query.get(file_id)

        if not step_file:
            return jsonify({'error': f'STEP file not found: {file_id}'}), 404

        if not step_file.graph_header_id:
            return jsonify({'error': f'No graph header found for file: {file_id}'}), 404

        header_id = str(step_file.graph_header_id)

        # Construir query
        query = STEPEntity.query.filter_by(header_id=header_id)

        if entity_type:
            query = query.filter_by(entity_type=entity_type)

        if manufacturing_feature:
            if manufacturing_feature.startswith('feature:'):
                # Remove the 'feature:' prefix for actual lookup
                actual_feature = manufacturing_feature[8:]
                query = query.filter_by(manufacturing_feature=actual_feature)
            else:
                query = query.filter_by(manufacturing_feature=manufacturing_feature)

        # Obtener total
        total = query.count()

        # Aplicar límites y offset
        entities = query.limit(limit).offset(offset).all()

        # Convertir a diccionario
        entities_list = []
        for entity in entities:
            entity_dict = {
                'id': entity.id,
                'entity_id': entity.entity_id,
                'entity_type': entity.entity_type,
                'entity_label': entity.entity_label,
                'reference_count': len(entity.references_to or []),
                'depth_level': entity.depth_level,
                'is_leaf': entity.is_leaf,
                'is_root': entity.is_root,
                'manufacturing_feature': entity.manufacturing_feature,
                'entity_category': entity.entity_category,
                'raw_line': entity.raw_line[:100] if hasattr(entity, 'raw_line') and entity.raw_line else None  # Limitar longitud
            }
            entities_list.append(entity_dict)

        return jsonify({
            'entities': entities_list,
            'total': total,
            'limit': limit,
            'offset': offset,
            'file_id': file_id,
            'header_id': header_id,
            'manufacturing_features': {
                'has_features': bool([e for e in entities if e.manufacturing_feature]),
                'feature_count': len([e for e in entities if e.manufacturing_feature]),
                'feature_types': list(set(e.manufacturing_feature for e in entities if e.manufacturing_feature))
            }
        }), 200

    except Exception as e:
        logger.exception(f"Error obteniendo entidades por file_id: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/stats', methods=['GET'])
def get_graph_stats(header_id):
    """
    Obtiene estadísticas del grafo

    Returns:
        JSON con métricas del grafo
    """
    logger.info(f"GET /graph/{header_id}/stats")

    header = STEPFileHeader.query.filter_by(id=header_id).first()

    if not header:
        return jsonify({'error': 'Header no encontrado'}), 404

    # Contar entidades por tipo
    entity_type_counts = db.session.query(
        STEPEntity.entity_type,
        db.func.count(STEPEntity.id)
    ).filter_by(
        header_id=header_id
    ).group_by(
        STEPEntity.entity_type
    ).all()

    # Contar por categoría
    category_counts = db.session.query(
        STEPEntity.entity_category,
        db.func.count(STEPEntity.id)
    ).filter_by(
        header_id=header_id
    ).group_by(
        STEPEntity.entity_category
    ).all()

    # Contar manufacturing features
    feature_counts = db.session.query(
        STEPEntity.manufacturing_feature,
        db.func.count(STEPEntity.id)
    ).filter(
        STEPEntity.header_id == header_id,
        STEPEntity.manufacturing_feature.isnot(None)
    ).group_by(
        STEPEntity.manufacturing_feature
    ).all()

    return jsonify({
        'header_id': str(header_id),
        'total_entities': header.total_entities,
        'total_references': header.total_references,
        'max_depth': header.max_depth,
        'root_entities': header.root_entities,
        'leaf_entities': header.leaf_entities,
        'is_dag': header.is_dag,
        'entity_types': {
            type_name: count for type_name, count in entity_type_counts
        },
        'entity_categories': {
            cat: count for cat, count in category_counts if cat
        },
        'manufacturing_features': {
            feat: count for feat, count in feature_counts
        },
        'depth_distribution': header.depth_distribution
    }), 200


@bp.route('/<string:header_id>/precompute', methods=['POST'])
def precompute_tree(header_id):
    """
    Pre-computa y guarda el árbol de entidades

    Útil para ejecutar en background después de importar

    Returns:
        JSON con resultado de la pre-computación
    """
    logger.info(f"POST /graph/{header_id}/precompute")

    try:
        builder = GraphBuilder(header_id)

        # Computar árbol
        tree = builder.compute_entity_tree(use_cache=False)

        # Guardar en cache
        builder.save_tree_to_cache(tree)

        return jsonify({
            'message': 'Árbol pre-computado exitosamente',
            'metadata': tree['metadata']
        }), 200

    except Exception as e:
        logger.exception(f"Error pre-computando árbol: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:part_id>/parse', methods=['POST'])
def parse_graph_for_part(part_id):
    """
    Parsea el grafo STEP para una Part ya existente (CAPP o upload previo).
    Crea STEPFileHeader + STEPEntity records si no existen.

    Returns:
        JSON con header_id y conteo de entidades creadas
    """
    logger.info(f"POST /graph/{part_id}/parse")

    try:
        from app.services.step_graph_storage import parse_step_graph_for_part

        part = Part.query.get(part_id)
        if not part:
            return jsonify({'error': 'Part not found'}), 404

        if not part.file_path or not os.path.exists(part.file_path):
            return jsonify({'error': 'STEP file not found on disk', 'file_path': part.file_path}), 404

        header_id = parse_step_graph_for_part(part.file_path, str(part.id))

        entity_count = STEPEntity.query.filter_by(header_id=header_id).count()

        return jsonify({
            'success': True,
            'part_id': part_id,
            'header_id': header_id,
            'entity_count': entity_count
        }), 200

    except Exception as e:
        logger.exception(f"Error parsing graph for part {part_id}: {e}")
        return jsonify({'error': str(e)}), 500


logger.info("[OK] Graph API routes loaded (expanded version)")
