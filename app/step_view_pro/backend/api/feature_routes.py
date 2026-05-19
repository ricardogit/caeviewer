"""
Feature API Routes - Endpoints para detección y gestión de manufacturing features
Versión: 1.0.0
Autor: STEP-View Pro Team
"""

from flask import Blueprint, jsonify, request
import logging
import os

from app.step_view_pro.models import STEPFileHeader, STEPEntity
from app.models import Part
from app.extensions import db
from app.step_view_pro.backend.feature_extractor import (
    FeatureExtractor,
    extract_features_for_file,
    PYTHONOCC_AVAILABLE
)
from app.step_view_pro.backend.advanced_feature_extractor import (
    AdvancedFeatureExtractor,
    extract_advanced_features_for_file,
    get_advanced_capabilities
)

logger = logging.getLogger(__name__)
bp = Blueprint('feature_api', __name__)


def _resolve_header(header_id):
    """Resolve STEPFileHeader by its UUID or by part_id fallback."""
    header = STEPFileHeader.query.get(header_id)
    if not header:
        header = STEPFileHeader.query.filter_by(part_id=header_id).first()
    return header


@bp.route('/<string:header_id>/extract', methods=['POST'])
def extract_features(header_id):
    """
    Extrae manufacturing features de un archivo STEP

    Body (opcional):
        method (str): "geometric" (analiza geometría con PythonOCC) o "entity" (usa BD)
        force_recompute (bool): Forzar recomputación aunque ya existan features

    Returns:
        JSON con:
            - total_features: Número total de features detectados
            - features_by_type: Agrupación por tipo (HOLE, POCKET, etc.)
            - features: Array de features con detalles
            - saved_to_db: Cuántos features se guardaron en BD
    """
    data = request.get_json() or {}
    method = data.get('method', 'entity')  # Por defecto, usar análisis de entidades
    force_recompute = data.get('force_recompute', False)

    logger.info(f"POST /features/{header_id}/extract method={method}")

    # Verificar que el header existe
    header = _resolve_header(header_id)
    if not header:
        return jsonify({'error': 'Header no encontrado'}), 404

    resolved_id = str(header.id)

    # Verificar si ya hay features y no es force_recompute
    if not force_recompute:
        existing_features = STEPEntity.query.filter(
            STEPEntity.header_id == resolved_id,
            STEPEntity.manufacturing_feature.isnot(None)
        ).count()

        if existing_features > 0:
            logger.info(f"Features already extracted ({existing_features} found). Use force_recompute=true to recompute.")
            return jsonify({
                'message': 'Features already extracted',
                'existing_features': existing_features,
                'hint': 'Use force_recompute=true to recompute',
                'features_by_type': {}
            }), 200

    # Método geométrico requiere PythonOCC
    if method == 'geometric' and not PYTHONOCC_AVAILABLE:
        return jsonify({
            'error': 'PythonOCC not available. Use method=entity instead.'
        }), 400

    try:
        # Obtener filepath del archivo STEP original
        part = header.part
        if not part or not part.file_path:
            return jsonify({'error': 'Associated STEP file not found for this header'}), 404

        if not os.path.exists(part.file_path):
            return jsonify({'error': 'STEP file not found on disk'}), 404

        # Extraer features
        result = extract_features_for_file(
            header_id=resolved_id,
            filepath=part.file_path,
            method=method
        )

        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error extracting features: {e}")
        return jsonify({'error': f'Error interno: {str(e)}'}), 500


@bp.route('/<string:header_id>/list', methods=['GET'])
def list_features(header_id):
    """
    Lista todos los features detectados para un archivo

    Query Params:
        feature_type (str): Filtrar por tipo (HOLE, POCKET, SLOT, etc.)
        limit (int): Máximo de resultados (default: 100)

    Returns:
        JSON con array de features
    """
    feature_type = request.args.get('feature_type')
    limit = int(request.args.get('limit', 100))

    logger.info(f"GET /features/{header_id}/list type={feature_type}")

    # Validate that header exists
    header = _resolve_header(header_id)
    if not header:
        return jsonify({'error': 'Header not found'}), 404
    header_id = str(header.id)

    # Construir query
    query = STEPEntity.query.filter(
        STEPEntity.header_id == header_id,
        STEPEntity.manufacturing_feature.isnot(None)
    )

    if feature_type:
        # Filtrar por tipo
        query = query.filter(STEPEntity.manufacturing_feature == feature_type)

    entities = query.limit(limit).all()

    # Construir respuesta
    features = []
    for entity in entities:
        feature_data = entity.feature_metadata or {}
        feature_data['entity_id'] = entity.entity_id
        feature_data['entity_type'] = entity.entity_type
        feature_data['id'] = str(entity.id)  # Add the database ID for proper linking
        features.append(feature_data)

    # Agrupar por tipo
    features_by_type = {}
    for feature in features:
        ftype = feature.get('feature_type', 'UNKNOWN')
        if ftype not in features_by_type:
            features_by_type[ftype] = []
        features_by_type[ftype].append(feature)

    return jsonify({
        'total': len(features),
        'features': features,
        'features_by_type': features_by_type
    }), 200


@bp.route('/<string:header_id>/feature/<string:feature_id>', methods=['GET'])
def get_feature_details(header_id, feature_id):
    """
    Obtiene detalles de un feature específico

    Returns:
        JSON con datos completos del feature
    """
    logger.info(f"GET /features/{header_id}/feature/{feature_id}")

    # Buscar entidad con ese feature_id
    entity = STEPEntity.query.filter_by(
        header_id=header_id,
        manufacturing_feature=feature_id
    ).first()

    if not entity:
        return jsonify({'error': 'Feature no encontrado'}), 404

    feature_data = entity.feature_metadata or {}
    feature_data['entity_id'] = entity.entity_id
    feature_data['entity_type'] = entity.entity_type
    feature_data['entity_label'] = entity.entity_label

    return jsonify(feature_data), 200


@bp.route('/<string:header_id>/stats', methods=['GET'])
def get_feature_stats(header_id):
    """
    Obtiene estadísticas de features detectados

    Returns:
        JSON con métricas:
            - total_features
            - features_by_type (count)
            - average_dimensions (por tipo)
    """
    logger.info(f"GET /features/{header_id}/stats")

    # Contar features por tipo
    entities = STEPEntity.query.filter(
        STEPEntity.header_id == header_id,
        STEPEntity.manufacturing_feature.isnot(None)
    ).all()

    if not entities:
        return jsonify({
            'total_features': 0,
            'features_by_type': {},
            'message': 'No features detected. Run /extract first.'
        }), 200

    # Agrupar y analizar
    features_by_type = {}
    dimensions_by_type = {}

    for entity in entities:
        metadata = entity.feature_metadata or {}
        ftype = metadata.get('feature_type', 'UNKNOWN')

        # Contar
        if ftype not in features_by_type:
            features_by_type[ftype] = 0
            dimensions_by_type[ftype] = []

        features_by_type[ftype] += 1

        # Recopilar dimensiones
        dims = metadata.get('dimensions', {})
        if dims:
            dimensions_by_type[ftype].append(dims)

    # Calcular promedios
    average_dimensions = {}
    for ftype, dims_list in dimensions_by_type.items():
        if not dims_list:
            continue

        # Promediar cada parámetro
        avg_dims = {}
        for key in dims_list[0].keys():
            values = [d[key] for d in dims_list if key in d and d[key] is not None]
            if values:
                avg_dims[key] = sum(values) / len(values)

        average_dimensions[ftype] = avg_dims

    return jsonify({
        'total_features': len(entities),
        'features_by_type': features_by_type,
        'average_dimensions': average_dimensions,
        'extraction_complete': True
    }), 200


@bp.route('/<string:header_id>/holes', methods=['GET'])
def get_holes_only(header_id):
    """
    Endpoint especializado para obtener solo agujeros

    Query Params:
        min_diameter (float): Diámetro mínimo
        max_diameter (float): Diámetro máximo
        subtype (str): THROUGH_HOLE o BLIND_HOLE

    Returns:
        JSON con array de holes
    """
    min_diameter = request.args.get('min_diameter', type=float)
    max_diameter = request.args.get('max_diameter', type=float)
    subtype = request.args.get('subtype')

    logger.info(f"GET /features/{header_id}/holes")

    # Obtener entidades con features tipo HOLE
    entities = STEPEntity.query.filter(
        STEPEntity.header_id == header_id,
        STEPEntity.feature_metadata['feature_type'].astext == 'HOLE'
    ).all()

    holes = []
    for entity in entities:
        metadata = entity.feature_metadata or {}

        # Filtrar por subtype
        if subtype and metadata.get('feature_subtype') != subtype:
            continue

        # Filtrar por diámetro
        dims = metadata.get('dimensions', {})
        diameter = dims.get('diameter')

        if diameter:
            if min_diameter and diameter < min_diameter:
                continue
            if max_diameter and diameter > max_diameter:
                continue

        hole_data = metadata.copy()
        hole_data['entity_id'] = entity.entity_id
        holes.append(hole_data)

    return jsonify({
        'total_holes': len(holes),
        'holes': holes
    }), 200


@bp.route('/<string:header_id>/delete', methods=['DELETE'])
def delete_features(header_id):
    """
    Elimina todos los features detectados

    Útil para limpiar antes de recomputar

    Returns:
        JSON con número de features eliminados
    """
    logger.info(f"DELETE /features/{header_id}/delete")

    try:
        # Contar features antes de eliminar
        count_before = STEPEntity.query.filter(
            STEPEntity.header_id == header_id,
            STEPEntity.manufacturing_feature.isnot(None)
        ).count()

        # Limpiar campos
        STEPEntity.query.filter_by(header_id=header_id).update({
            'manufacturing_feature': None,
            'feature_metadata': None
        })

        db.session.commit()

        logger.info(f"Deleted {count_before} features")

        return jsonify({
            'message': 'Features deleted successfully',
            'deleted_count': count_before
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting features: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/extract-advanced', methods=['POST'])
def extract_advanced_features(header_id):
    """
    Extrae características de manufactura avanzadas de un archivo STEP

    Body (opcional):
        method (str): "geometric" (analiza geometría con PythonOCC) o "entity" (usa BD)
        force_recompute (bool): Forzar recomputación aunque ya existan features

    Returns:
        JSON con:
            - total_features: Número total de features detectados
            - features_by_type: Agrupación por tipo (más de 200 tipos)
            - features: Array de features con detalles
            - saved_to_db: Cuántos features se guardaron en BD
            - total_feature_types: Número de categorías de features
    """
    data = request.get_json() or {}
    method = data.get('method', 'geometric')  # Por defecto, usar análisis geométrico
    force_recompute = data.get('force_recompute', False)

    logger.info(f"POST /features/{header_id}/extract-advanced method={method}")

    # Verificar que el header existe
    header = _resolve_header(header_id)
    if not header:
        return jsonify({'error': 'Header no encontrado'}), 404

    resolved_id = str(header.id)

    # Verificar si ya hay features y no es force_recompute
    if not force_recompute:
        existing_features = STEPEntity.query.filter(
            STEPEntity.header_id == resolved_id,
            STEPEntity.manufacturing_feature.isnot(None)
        ).count()

        if existing_features > 0:
            logger.info(f"Features already extracted ({existing_features} found). Use force_recompute=true to recompute.")
            return jsonify({
                'message': 'Features already extracted',
                'existing_features': existing_features,
                'hint': 'Use force_recompute=true to recompute',
                'features_by_type': {}
            }), 200

    # Método geométrico requiere PythonOCC
    if method == 'geometric' and not PYTHONOCC_AVAILABLE:
        return jsonify({
            'error': 'PythonOCC not available. Use method=entity instead.'
        }), 400

    try:
        # Obtener filepath del archivo STEP original
        part = header.part
        if not part or not part.file_path:
            return jsonify({'error': 'Associated STEP file not found for this header'}), 404

        if not os.path.exists(part.file_path):
            return jsonify({'error': 'STEP file not found on disk'}), 404

        # Extraer features avanzados
        features = extract_advanced_features_for_file(
            header_id=resolved_id,
            method=method
        )

        # Convert features to serializable dicts
        features_dict = []
        for feature in features:
            from dataclasses import asdict
            feature_dict = asdict(feature)
            # Convert Enum to string
            if 'feature_type' in feature_dict and hasattr(feature_dict['feature_type'], 'value'):
                feature_dict['feature_type'] = feature_dict['feature_type'].value
            features_dict.append(feature_dict)

        result = {
            'features': features_dict,
            'total_features': len(features_dict),
            'extraction_method': method
        }

        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error extracting advanced features: {e}")
        return jsonify({'error': f'Error interno: {str(e)}'}), 500


@bp.route('/advanced-capabilities', methods=['GET'])
def get_advanced_feature_capabilities():
    """
    Retorna las capacidades avanzadas del sistema de feature extraction

    Returns:
        JSON con métodos disponibles y estado de dependencias
    """
    return jsonify(get_advanced_capabilities()), 200


@bp.route('/<string:header_id>/features-by-category', methods=['GET'])
def get_features_by_category(header_id):
    """
    Obtiene features agrupados por categoría temática

    Query Params:
        limit (int): Máximo de resultados (default: 100)

    Returns:
        JSON con features agrupados por categoría
    """
    limit = int(request.args.get('limit', 100))

    logger.info(f"GET /features/{header_id}/features-by-category")

    # Obtener todas las entidades con features
    entities = STEPEntity.query.filter(
        STEPEntity.header_id == header_id,
        STEPEntity.manufacturing_feature.isnot(None)
    ).limit(limit).all()

    # Agrupar por categoría (basado en feature_type)
    features_by_category = {}
    for entity in entities:
        metadata = entity.feature_metadata or {}
        feature_type = metadata.get('feature_type', 'UNKNOWN')

        # Mapear feature types a categorías
        category_map = {
            'HOLE': 'Holes & Cavities',
            'POCKET': 'Holes & Cavities',
            'SLOT': 'Holes & Cavities',
            'BOSS': 'Protrusions & Recesses',
            'FILLET': 'Curved Features',
            'CHAMFER': 'Angular Features',
            'RIB': 'Structural Features',
            'GROOVE': 'Surface Features',
            'THREAD': 'Manufacturing Features',
            'COUNTERBORE': 'Manufacturing Features',
            'COUNTERSINK': 'Manufacturing Features',
            'PLANE': 'Surface Features',
            'CYLINDER': 'Geometric Features',
            'CONE': 'Geometric Features',
            'SPHERE': 'Geometric Features',
            'TORUS': 'Geometric Features',
            'DATUM_FEATURE': 'Reference Features',
            'PROFILE_FEATURE': 'Design Features',
            'SYMMETRY_FEATURE': 'Design Features',
            'PATTERN_FEATURE': 'Design Features',
            'MIRROR_FEATURE': 'Design Features',
            'WALL_FEATURE': 'Structural Features',
            'WEB_FEATURE': 'Structural Features',
            'GUSSET_FEATURE': 'Structural Features',
            'FLANGE_FEATURE': 'Structural Features'
        }

        category = category_map.get(feature_type, 'General Features')

        if category not in features_by_category:
            features_by_category[category] = []

        feature_data = metadata.copy()
        feature_data['entity_id'] = entity.entity_id
        feature_data['entity_type'] = entity.entity_type
        features_by_category[category].append(feature_data)

    return jsonify({
        'total_categories': len(features_by_category),
        'features_by_category': features_by_category,
        'total_features': sum(len(v) for v in features_by_category.values())
    }), 200


@bp.route('/capabilities', methods=['GET'])
def get_capabilities():
    """
    Retorna las capacidades del sistema de feature extraction

    Returns:
        JSON con métodos disponibles y estado de dependencias
    """
    return jsonify({
        'pythonocc_available': PYTHONOCC_AVAILABLE,
        'supported_methods': ['entity', 'geometric'] if PYTHONOCC_AVAILABLE else ['entity'],
        'supported_feature_types': [
            'HOLE',
            'POCKET',
            'SLOT',
            'BOSS',
            'FILLET',
            'CHAMFER'
        ],
        'supported_hole_subtypes': [
            'THROUGH_HOLE',
            'BLIND_HOLE',
            'CYLINDRICAL_FEATURE'
        ]
    }), 200


logger.info("[OK] Feature API routes loaded")
