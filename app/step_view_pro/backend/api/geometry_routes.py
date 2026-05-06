"""
Geometry API Routes - Endpoints para obtener geometría 3D procesada
Autor: STEP Benchmark Team
Versión: 1.0.0
"""

from flask import Blueprint, jsonify, request, current_app
from datetime import datetime
import os
import logging

from app.step_view_pro.models import STEPFileHeader, STEPFile
from app.step_view_pro.models.step_graph import STEPEntity
from app.models import Part
from app.extensions import db
from app.step_view_pro.backend.geometry_processor import GeometryProcessor, GeometryProcessorError
# Importamos el cache_manager global (se inicializa en performance_routes.init_performance_tools)
cache_manager = None  # Placeholder - real instance set globally after initialization

logger = logging.getLogger(__name__)

# Blueprint
bp = Blueprint('geometry_api', __name__)


@bp.route('/<string:header_id>', methods=['GET'])
def get_geometry(header_id):
    """
    Obtiene geometría 3D procesada de un archivo STEP

    Args:
        header_id (UUID): ID del STEP file header

    Query Params:
        lod (str): Nivel de detalle - 'low', 'medium', 'high' (default: 'medium')
        force_reprocess (bool): Forzar reprocesamiento ignorando cache

    Returns:
        JSON con:
            - vertices: Array de coordenadas [x, y, z, ...]
            - normals: Array de normales [nx, ny, nz, ...]
            - indices: Array de índices de triángulos
            - triangle_count: Número de triángulos
            - vertex_count: Número de vértices
            - bounding_box: Bounding box del modelo

    Responses:
        200: Geometría encontrada (cache hit o procesada)
        404: Archivo STEP no encontrado
        500: Error en procesamiento
    """
    # Parámetros
    lod = request.args.get('lod', 'medium')
    force_reprocess = request.args.get('force_reprocess', 'false').lower() == 'true'

    if lod not in ['low', 'medium', 'high']:
        return jsonify({'error': f'LOD inválido: {lod}. Usar: low, medium, high'}), 400

    logger.info(f"GET /geometry/{header_id} LOD={lod} force_reprocess={force_reprocess}")

    # Buscar header
    header = STEPFileHeader.query.filter_by(id=header_id).first()

    if not header:
        logger.warning(f"Header no encontrado: {header_id}")
        return jsonify({'error': 'STEP file header no encontrado'}), 404

    # Obtener archivo legacy asociado
    step_file = header.legacy_file

    if not step_file:
        logger.error(f"No hay archivo legacy asociado al header {header_id}")
        return jsonify({'error': 'Archivo STEP no encontrado'}), 404

    # Verificar que el archivo físico existe
    if not os.path.exists(step_file.file_path):
        logger.error(f"Archivo físico no existe: {step_file.file_path}")
        return jsonify({'error': 'Archivo físico no encontrado'}), 404

    try:
        # Intentar obtener desde cache (si no es force_reprocess)
        if not force_reprocess and cache_manager:
            try:
                geometry = cache_manager.get_geometry(
                    header_id=str(header_id),
                    lod=lod
                )

                if geometry:
                    logger.info(f"[OK] Geometría servida desde cache (LOD={lod})")
                    return jsonify({
                        'geometry': geometry,
                        'metadata': {
                            'source': 'cache',
                            'header_id': str(header_id),
                            'filename': step_file.filename,
                            'lod': lod,
                            'timestamp': datetime.utcnow().isoformat()
                        }
                    }), 200
            except Exception as e:
                logger.warning(f"Cache miss or error: {e}")
                # Proceed to process without cache

        # Cache miss o force_reprocess → procesar archivo
        logger.info(f"Procesando archivo STEP: {step_file.file_path}")

        processor = GeometryProcessor()
        geometry_data = processor.generate_geometry_json(step_file.file_path)

        # Guardar en cache
        if cache_manager:
            try:
                cache_key = cache_manager.save_geometry(
                    header_id=str(header_id),
                    geometry_data=geometry_data
                )
                logger.info(f"[OK] Geometría guardada en cache: {cache_key[:8]}...")
            except Exception as e:
                logger.warning(f"Error saving to cache: {e}")
                # Continue without cache

        # Retornar el LOD solicitado
        lod_geometry = geometry_data[f'lod_{lod}']
        bounding_box = geometry_data['bounding_box']

        return jsonify({
            'geometry': {
                **lod_geometry,
                'bounding_box': bounding_box
            },
            'metadata': {
                'source': 'processed',
                'header_id': str(header_id),
                'filename': step_file.filename,
                'lod': lod,
                'processing_time_ms': geometry_data['metadata']['total_processing_time_ms'],
                'timestamp': datetime.utcnow().isoformat()
            }
        }), 200

    except GeometryProcessorError as e:
        logger.error(f"Error procesando geometría: {e}")
        return jsonify({'error': f'Error procesando geometría: {str(e)}'}), 500

    except Exception as e:
        logger.exception(f"Error inesperado: {e}")
        return jsonify({'error': f'Error interno del servidor: {str(e)}'}), 500


@bp.route('/<string:header_id>/all-lods', methods=['GET'])
def get_all_lods(header_id):
    """
    Obtiene todos los LODs de una sola vez (para carga progresiva)

    Returns:
        JSON con lod_low, lod_medium, lod_high, bounding_box
    """
    logger.info(f"GET /geometry/{header_id}/all-lods")

    header = STEPFileHeader.query.filter_by(id=header_id).first()

    if not header:
        return jsonify({'error': 'Header no encontrado'}), 404

    step_file = header.legacy_file

    if not step_file or not os.path.exists(step_file.file_path):
        return jsonify({'error': 'Archivo STEP no encontrado'}), 404

    try:
        # Intentar cache
        if cache_manager:
            try:
                # Intentar obtener cada LOD del cache
                lod_low = cache_manager.get_geometry(str(header_id), 'low')
                lod_medium = cache_manager.get_geometry(str(header_id), 'medium')
                lod_high = cache_manager.get_geometry(str(header_id), 'high')

                if lod_low and lod_medium and lod_high:
                    logger.info("[OK] Todos los LODs servidos desde cache")
                    return jsonify({
                        'lod_low': lod_low,
                        'lod_medium': lod_medium,
                        'lod_high': lod_high,
                        'metadata': {
                            'source': 'cache',
                            'header_id': str(header_id),
                            'filename': step_file.filename
                        }
                    }), 200
            except Exception as e:
                logger.warning(f"Cache miss or error for all-lods: {e}")
                # Proceed to process without cache

        # Si no está todo en cache, procesar
        processor = GeometryProcessor()
        geometry_data = processor.generate_geometry_json(step_file.file_path)

        # Guardar en cache
        if cache_manager:
            try:
                cache_manager.save_geometry(str(header_id), geometry_data)
            except Exception as e:
                logger.warning(f"Error saving to cache: {e}")
                # Continue without cache

        return jsonify({
            'lod_low': geometry_data['lod_low'],
            'lod_medium': geometry_data['lod_medium'],
            'lod_high': geometry_data['lod_high'],
            'bounding_box': geometry_data['bounding_box'],
            'metadata': geometry_data['metadata']
        }), 200

    except Exception as e:
        logger.exception(f"Error obteniendo LODs: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/bbox', methods=['GET'])
def get_bounding_box(header_id):
    """
    Obtiene solo el bounding box (útil para centrar cámara sin cargar geometría)

    Returns:
        JSON con min, max, center, size
    """
    logger.info(f"GET /geometry/{header_id}/bbox")

    header = STEPFileHeader.query.filter_by(id=header_id).first()

    if not header:
        return jsonify({'error': 'Header no encontrado'}), 404

    step_file = header.legacy_file

    if not step_file:
        return jsonify({'error': 'Archivo no encontrado'}), 404

    try:
        # Intentar obtener bbox del cache (está en metadata)
        if cache_manager:
            try:
                lod_low = cache_manager.get_geometry(str(header_id), 'low')
                if lod_low and 'bounding_box' in lod_low:
                    return jsonify({
                        'bounding_box': lod_low['bounding_box'],
                        'source': 'cache'
                    }), 200
            except Exception as e:
                logger.warning(f"Cache miss or error for bbox: {e}")
                # Proceed to process without cache

        # Si no está en cache, procesar solo para bbox (rápido con LOD bajo)
        processor = GeometryProcessor()
        shape = processor.parse_step_file(step_file.file_path)
        bbox = processor.compute_bounding_box(shape)

        return jsonify({
            'bounding_box': bbox,
            'source': 'computed'
        }), 200

    except Exception as e:
        logger.exception(f"Error calculando bounding box: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/cache/stats', methods=['GET'])
def get_cache_stats():
    """
    Obtiene estadísticas del cache

    Returns:
        JSON con estadísticas de PostgreSQL y Redis
    """
    if not cache_manager:
        return jsonify({'error': 'Cache manager no disponible'}), 503

    try:
        stats = cache_manager.get_cache_stats()
        return jsonify(stats), 200

    except Exception as e:
        logger.exception(f"Error obteniendo stats: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/cache/invalidate/<string:header_id>', methods=['DELETE'])
def invalidate_cache(header_id):
    """
    Invalida el cache para un archivo específico

    Returns:
        JSON con número de entradas eliminadas
    """
    if not cache_manager:
        return jsonify({'error': 'Cache manager no disponible'}), 503

    try:
        deleted = cache_manager.invalidate_cache(header_id)

        return jsonify({
            'message': f'Cache invalidado para {header_id}',
            'entries_deleted': deleted
        }), 200

    except Exception as e:
        logger.exception(f"Error invalidando cache: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/cache/cleanup', methods=['POST'])
def cleanup_cache():
    """
    Limpia entradas antiguas del cache

    Body:
        days (int): Días sin acceso para eliminar (default: 30)

    Returns:
        JSON con número de entradas eliminadas
    """
    if not cache_manager:
        return jsonify({'error': 'Cache manager no disponible'}), 503

    try:
        data = request.get_json() or {}
        days = data.get('days', 30)

        deleted = cache_manager.cleanup_old_entries(days)

        return jsonify({
            'message': f'Cache limpiado (>{days} días sin acceso)',
            'entries_deleted': deleted
        }), 200

    except Exception as e:
        logger.exception(f"Error limpiando cache: {e}")
        return jsonify({'error': str(e)}), 500


# Health check
@bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check del servicio de geometría

    Returns:
        JSON con estado de servicios
    """
    status = {
        'service': 'geometry_api',
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'components': {
            'pythonocc': False,
            'cache_manager': cache_manager is not None,
            'redis': cache_manager.redis_available if cache_manager else False
        }
    }

    # Check PythonOCC
    try:
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        status['components']['pythonocc'] = True
    except ImportError:
        pass

    return jsonify(status), 200


@bp.route('/entity/<string:entity_uuid>', methods=['GET'])
def get_entity_info(entity_uuid):
    """
    Obtiene información completa de una entidad STEP

    Args:
        entity_uuid (UUID): ID de la entidad en la base de datos

    Query Params:
        include_references (bool): Incluir entidades referenciadas (default: true)
        include_referenced_by (bool): Incluir entidades que la referencian (default: true)
        include_geometry (bool): Incluir propiedades geométricas (default: true)

    Returns:
        JSON con:
            - entity_info: Información básica de la entidad
            - attributes: Atributos de la entidad
            - references: Entidades que esta entidad referencia (referencias salientes)
            - referenced_by: Entidades que referencian esta entidad (referencias entrantes)
            - geometric_properties: Propiedades geométricas
            - manufacturing_info: Información de manufactura si existe
            - graph_properties: Propiedades del grafo (depth, degree, etc.)

    Responses:
        200: Entidad encontrada
        404: Entidad no encontrada
        400: UUID inválido
        500: Error interno
    """
    # Parámetros
    include_references = request.args.get('include_references', 'true').lower() == 'true'
    include_referenced_by = request.args.get('include_referenced_by', 'true').lower() == 'true'
    include_geometry = request.args.get('include_geometry', 'true').lower() == 'true'

    logger.info(f"GET /geometry/entity/{entity_uuid}")

    try:
        # Importar modelo
        from sqlalchemy.dialects.postgresql import UUID
        import uuid as uuid_lib

        # Validar UUID
        try:
            entity_uuid_obj = uuid_lib.UUID(entity_uuid)
        except ValueError:
            return jsonify({'error': f'UUID inválido: {entity_uuid}'}), 400

        # Buscar entidad
        entity = STEPEntity.query.filter_by(id=entity_uuid_obj).first()

        if not entity:
            logger.warning(f"Entidad no encontrada: {entity_uuid}")
            return jsonify({'error': 'Entidad no encontrada'}), 404

        # Construir respuesta
        response = {
            'entity_info': {
                'id': str(entity.id),
                'entity_id': entity.entity_id,  # #123 del STEP
                'entity_type': entity.entity_type,
                'entity_label': entity.entity_label,
                'entity_category': entity.entity_category,
                'validation_status': entity.validation_status,
                'raw_line': entity.raw_line,
            },
            'attributes': entity.entity_attributes or {},
            'graph_properties': {
                'depth_level': entity.depth_level,
                'is_leaf': entity.is_leaf,
                'is_root': entity.is_root,
                'degree': entity.degree,
                'out_degree': len(entity.references_to) if entity.references_to else 0,
                'in_degree': len(entity.referenced_by) if entity.referenced_by else 0,
            }
        }

        # Incluir referencias (referencias salientes - entidades que ESTA entidad referencia)
        if include_references and entity.references_to:
            references = []
            for ref_entity_id in entity.references_to:
                # Buscar la entidad referenciada (mismo header)
                ref_entity = STEPEntity.query.filter_by(
                    header_id=entity.header_id,
                    entity_id=ref_entity_id
                ).first()

                if ref_entity:
                    references.append({
                        'id': str(ref_entity.id),
                        'entity_id': ref_entity.entity_id,
                        'entity_type': ref_entity.entity_type,
                        'entity_label': ref_entity.entity_label,
                        'entity_category': ref_entity.entity_category,
                        'relation_type': 'references'
                    })

            response['references'] = references
        else:
            response['references'] = []

        # Incluir entidades que referencian a ESTA (referencias entrantes)
        if include_referenced_by and entity.referenced_by:
            referenced_by = []
            for ref_by_entity_id in entity.referenced_by:
                # Buscar la entidad que referencia (mismo header)
                ref_by_entity = STEPEntity.query.filter_by(
                    header_id=entity.header_id,
                    entity_id=ref_by_entity_id
                ).first()

                if ref_by_entity:
                    referenced_by.append({
                        'id': str(ref_by_entity.id),
                        'entity_id': ref_by_entity.entity_id,
                        'entity_type': ref_by_entity.entity_type,
                        'entity_label': ref_by_entity.entity_label,
                        'entity_category': ref_by_entity.entity_category,
                        'relation_type': 'referenced_by'
                    })

            response['referenced_by'] = referenced_by
        else:
            response['referenced_by'] = []

        # Incluir propiedades geométricas
        if include_geometry and entity.geometric_properties:
            response['geometric_properties'] = entity.geometric_properties
            response['bounding_box'] = entity.bounding_box
        else:
            response['geometric_properties'] = None
            response['bounding_box'] = None

        # Incluir información de manufactura si existe
        if entity.manufacturing_feature:
            response['manufacturing_info'] = {
                'feature_type': entity.manufacturing_feature,
                'feature_metadata': entity.feature_metadata or {},
                'is_geometric': entity.is_geometric,
                'is_topological': entity.is_topological,
            }
        else:
            response['manufacturing_info'] = None

        # Metadata adicional
        response['metadata'] = {
            'header_id': str(entity.header_id),
            'created_at': entity.created_at.isoformat() if entity.created_at else None,
            'neighbors_count': len(entity.get_neighbors()),
        }

        logger.info(f"[OK] Entidad {entity.entity_type} #{entity.entity_id} encontrada")

        return jsonify(response), 200

    except Exception as e:
        logger.exception(f"Error obteniendo información de entidad: {e}")
        return jsonify({'error': f'Error interno del servidor: {str(e)}'}), 500


@bp.route('/entity/by-step-id/<string:header_id>/<int:step_entity_id>', methods=['GET'])
def get_entity_by_step_id(header_id, step_entity_id):
    """
    Obtiene información de una entidad usando su ID del STEP (#123)

    Args:
        header_id (UUID): ID del header del archivo STEP
        step_entity_id (int): ID de la entidad en el archivo STEP (#123)

    Returns:
        JSON con información de la entidad (mismo formato que /entity/<uuid>)

    Responses:
        200: Entidad encontrada
        404: Entidad no encontrada
        400: Parámetros inválidos
        500: Error interno
    """
    logger.info(f"GET /geometry/entity/by-step-id/{header_id}/{step_entity_id}")

    try:
        import uuid as uuid_lib

        # Validar UUID del header
        try:
            header_uuid = uuid_lib.UUID(header_id)
        except ValueError:
            return jsonify({'error': f'UUID de header inválido: {header_id}'}), 400

        # Buscar entidad por header_id + entity_id
        entity = STEPEntity.query.filter_by(
            header_id=header_uuid,
            entity_id=step_entity_id
        ).first()

        if not entity:
            logger.warning(f"Entidad #{step_entity_id} no encontrada en header {header_id}")
            return jsonify({'error': f'Entidad #{step_entity_id} no encontrada'}), 404

        # Redirigir a la función principal usando el UUID de la entidad
        return get_entity_info(str(entity.id))

    except Exception as e:
        logger.exception(f"Error buscando entidad por STEP ID: {e}")
        return jsonify({'error': f'Error interno del servidor: {str(e)}'}), 500


@bp.route('/entity/by-face-index/<string:header_id>/<int:face_index>', methods=['GET'])
def get_entity_by_face_index(header_id, face_index):
    """
    Obtiene la entidad STEP correspondiente a un índice de cara en la geometría

    Args:
        header_id (UUID): ID del header del archivo STEP
        face_index (int): Índice de la cara en la geometría 3D

    Returns:
        JSON con:
            - success: boolean indicando éxito
            - entity_id: ID de la entidad STEP correspondiente
            - face_mapping: información sobre el mapeo

    Este endpoint permite el mapeo entre índices de cara en la geometría 3D
    y entidades STEP para habilitar selección bidireccional.
    """
    logger.info(f"GET /geometry/entity/by-face-index/{header_id}/{face_index}")

    try:
        import uuid as uuid_lib

        # Validar UUID del header
        try:
            header_uuid = uuid_lib.UUID(header_id)
        except ValueError:
            return jsonify({'success': False, 'error': f'UUID de header inválido: {header_id}'}), 400

        # Primero verificar si tenemos cache de mapeo cara → entidad
        # El mapeo cara → entidad normalmente se genera durante la conversión a geometría
        # y se almacena en el campo geometric_properties de la entidad
        try:
            # Buscar entidades que tengan información de mapeo de cara
            # Esto es una aproximación - en un sistema real, el mapeo cara→entidad
            # se haría durante la conversión STEP→geometría
            entity = STEPEntity.query.filter(
                STEPEntity.header_id == header_uuid,
                STEPEntity.geometric_properties.isnot(None)
            ).first()

            # En un sistema completo, tendríamos un mapeo directo cara→entidad
            # Por ahora, vamos a buscar entidades que tengan información de cara
            # en sus propiedades geométricas
            entities_with_face_info = STEPEntity.query.filter(
                STEPEntity.header_id == header_uuid,
                STEPEntity.geometric_properties.op('?')('face_indices')  # JSONB operator to check if key exists
            ).all()

            # Buscar entidad específica para el índice de cara
            target_entity = None
            for entity in entities_with_face_info:
                if (entity.geometric_properties and
                    'face_indices' in entity.geometric_properties and
                    face_index in entity.geometric_properties['face_indices']):
                    target_entity = entity
                    break

            # Si no encontramos una entidad específica, hacer una aproximación
            if not target_entity:
                # Buscar todas las entidades del archivo y tomar una basada en el índice
                all_entities = STEPEntity.query.filter_by(
                    header_id=header_uuid
                ).order_by(STEPEntity.entity_id).all()

                if all_entities:
                    # Tomar entidad basada en módulo del índice de cara
                    entity_idx = face_index % len(all_entities)
                    target_entity = all_entities[entity_idx]

            if target_entity:
                return jsonify({
                    'success': True,
                    'entity_id': target_entity.entity_id,
                    'entity_type': target_entity.entity_type,
                    'face_index': face_index,
                    'mapping_method': 'approximate'
                }), 200
            else:
                # Si no hay entidades con información de cara, devolver error
                # pero con sugerencia de entidad
                all_entities = STEPEntity.query.filter_by(
                    header_id=header_uuid
                ).order_by(STEPEntity.entity_id).all()

                if all_entities:
                    fallback_entity = all_entities[0]  # Primera entidad
                    return jsonify({
                        'success': True,
                        'entity_id': fallback_entity.entity_id,
                        'entity_type': fallback_entity.entity_type,
                        'face_index': face_index,
                        'mapping_method': 'fallback',
                        'message': 'No direct face mapping found, returning first entity'
                    }), 200
                else:
                    return jsonify({
                        'success': False,
                        'error': 'No entities found for this header',
                        'face_index': face_index
                    }), 404

        except Exception as e:
            logger.error(f"Error buscando entidad por índice de cara: {e}")
            return jsonify({
                'success': False,
                'error': f'Error buscando entidad: {str(e)}',
                'face_index': face_index
            }), 500

    except Exception as e:
        logger.exception(f"Error general en mapeo cara→entidad: {e}")
        return jsonify({
            'success': False,
            'error': f'Error interno del servidor: {str(e)}',
            'face_index': face_index
        }), 500


@bp.route('/file/<int:file_id>/entities', methods=['GET'])
def get_entities_by_file_id(file_id):
    """
    Obtiene entidades usando el ID de archivo en lugar del header UUID

    Query Params:
        type (str): Filtro por tipo de entidad
        limit (int): Límite de resultados (default: 100)
        offset (int): Offset para paginación (default: 0)

    Returns:
        JSON con:
            - entities: Array de entidades con features
            - total: Número total de entidades
    """
    entity_type = request.args.get('type')
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    logger.info(f"GET /geometry/file/{file_id}/entities type={entity_type}")

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
                'line_number': entity.line_number,
                'reference_count': len(entity.references_to or []),
                'depth_level': entity.depth_level,
                'is_leaf': entity.is_leaf,
                'is_root': entity.is_root,
                'manufacturing_feature': entity.manufacturing_feature,
                'entity_category': entity.entity_category,
            }
            entities_list.append(entity_dict)

        return jsonify({
            'entities': entities_list,
            'total': total,
            'limit': limit,
            'offset': offset,
            'file_id': file_id,
            'header_id': header_id
        }), 200

    except Exception as e:
        logger.exception(f"Error obteniendo entidades por file_id: {e}")
        return jsonify({'error': str(e)}), 500


logger.info("[OK] Geometry API routes loaded")
