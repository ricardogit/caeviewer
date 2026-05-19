"""
Comparison API Routes - Endpoints para comparación de versiones
"""

from flask import Blueprint, jsonify, request
import logging

from app.step_view_pro.models import STEPFileHeader, FileComparison, FileVersion
from app.models import Part
from app.extensions import db
from app.step_view_pro.backend.comparison_tools import ComparisonTools, VersionManager
from app.step_view_pro.backend.step_processor import load_step_shape

logger = logging.getLogger(__name__)
bp = Blueprint('comparison_api', __name__)


@bp.route('/compare', methods=['POST'])
def compare_files():
    """
    Compara dos archivos STEP

    Body:
        {
            "file1_id": "uuid",
            "file2_id": "uuid",
            "include_geometry": true,
            "save_result": true
        }

    Returns:
        {
            "comparison_id": "uuid",
            "file1_name": "...",
            "file2_name": "...",
            "change_summary": {...},
            "metadata_diff": {...},
            "structure_diff": {...},
            "geometry_diff": {...},
            "similarity_score": 0.95
        }
    """
    try:
        data = request.get_json()
        file1_id = data.get('file1_id')
        file2_id = data.get('file2_id')
        include_geometry = data.get('include_geometry', True)
        save_result = data.get('save_result', True)

        if not file1_id or not file2_id:
            return jsonify({'error': 'file1_id and file2_id required'}), 400

        # Accept header UUIDs directly, or part_id as fallback
        def _resolve(fid):
            h = STEPFileHeader.query.get(fid)
            if not h:
                h = STEPFileHeader.query.filter_by(part_id=fid).first()
            return h

        header1 = _resolve(file1_id)
        header2 = _resolve(file2_id)

        if not header1 or not header2:
            return jsonify({'error': 'Graph headers not found for one or both files'}), 404

        # Convertir headers a dict
        header1_dict = {
            'id': str(header1.id),
            'file_name': header1.file_name,
            'file_description': header1.file_description,
            'file_schema': header1.file_schema,
            'author': header1.author,
            'organization': header1.organization,
            'time_stamp': header1.time_stamp.isoformat() if header1.time_stamp else None,
            'total_entities': header1.total_entities,
            'total_references': header1.total_references,
            'max_depth': header1.max_depth,
            'root_entities': header1.root_entities,
            'leaf_entities': header1.leaf_entities,
            'depth_distribution': header1.depth_distribution
        }

        header2_dict = {
            'id': str(header2.id),
            'file_name': header2.file_name,
            'file_description': header2.file_description,
            'file_schema': header2.file_schema,
            'author': header2.author,
            'organization': header2.organization,
            'time_stamp': header2.time_stamp.isoformat() if header2.time_stamp else None,
            'total_entities': header2.total_entities,
            'total_references': header2.total_references,
            'max_depth': header2.max_depth,
            'root_entities': header2.root_entities,
            'leaf_entities': header2.leaf_entities,
            'depth_distribution': header2.depth_distribution
        }

        # Cargar geometrías si se solicita
        shape1 = None
        shape2 = None

        def _part_path(h):
            part = h.part if h else None
            return part.file_path if part else None

        path1 = _part_path(header1)
        path2 = _part_path(header2)

        if include_geometry and path1 and path2:
            try:
                from app.step_view_pro.backend.step_processor import load_step_shape as _load
                shape1 = _load(path1, 0)
                shape2 = _load(path2, 0)
            except Exception as e:
                logger.warning(f"Could not load shapes for geometry comparison: {e}")

        # Ejecutar comparación
        from app.step_view_pro.backend.comparison_tools import ComparisonTools
        comparison_result = ComparisonTools.create_comparison_result(
            header1_dict,
            header2_dict,
            shape1,
            shape2
        )

        # Guardar resultado si se solicita
        if save_result:
            comparison = FileComparison(
                file1_id=header1.id,
                file2_id=header2.id,
                change_summary=comparison_result.change_summary,
                metadata_diff=comparison_result.metadata_diff,
                structure_diff=comparison_result.structure_diff,
                geometry_diff=comparison_result.geometry_diff,
                similarity_score=comparison_result.similarity_score
            )
            db.session.add(comparison)
            db.session.commit()

            comparison_result.comparison_id = str(comparison.id)

        return jsonify(comparison_result.to_dict()), 200

    except Exception as e:
        logger.exception(f"Error comparing files: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/history/<string:file1_id>/<string:file2_id>', methods=['GET'])
def get_comparison_history(file1_id, file2_id):
    """
    Obtiene historial de comparaciones entre dos archivos

    Returns:
        {
            "total": 3,
            "comparisons": [...]
        }
    """
    try:
        comparisons = FileComparison.query.filter(
            ((FileComparison.file1_id == file1_id) & (FileComparison.file2_id == file2_id)) |
            ((FileComparison.file1_id == file2_id) & (FileComparison.file2_id == file1_id))
        ).order_by(FileComparison.compared_at.desc()).all()

        return jsonify({
            'total': len(comparisons),
            'comparisons': [c.to_dict() for c in comparisons]
        }), 200

    except Exception as e:
        logger.exception(f"Error getting comparison history: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:comparison_id>', methods=['GET'])
def get_comparison(comparison_id):
    """
    Obtiene resultado de una comparación específica

    Returns:
        {
            "id": "uuid",
            "file1_id": "uuid",
            "file2_id": "uuid",
            ...
        }
    """
    try:
        comparison = FileComparison.query.get(comparison_id)

        if not comparison:
            return jsonify({'error': 'Comparison not found'}), 404

        return jsonify(comparison.to_dict()), 200

    except Exception as e:
        logger.exception(f"Error getting comparison: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/versions/<string:header_id>/create', methods=['POST'])
def create_version(header_id):
    """
    Crea una nueva versión de un archivo

    Body:
        {
            "version_label": "v1.0",
            "change_description": "Initial version",
            "changed_by": "user@example.com"
        }

    Returns:
        {
            "version_id": "uuid",
            "version_number": 1,
            "version_label": "v1.0",
            ...
        }
    """
    try:
        data = request.get_json() or {}

        header = STEPFileHeader.query.get(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        # Obtener último número de versión
        last_version = FileVersion.query.filter_by(
            header_id=header.id
        ).order_by(FileVersion.version_number.desc()).first()

        next_version_number = (last_version.version_number + 1) if last_version else 1

        # Crear snapshot de metadatos
        metadata_snapshot = {
            'file_name': header.file_name,
            'file_schema': header.file_schema,
            'total_entities': header.total_entities,
            'author': header.author,
            'organization': header.organization
        }

        # Crear versión
        version = FileVersion(
            header_id=header.id,
            version_number=next_version_number,
            version_label=data.get('version_label', f'v{next_version_number}.0'),
            file_hash=header.file_hash,
            metadata_snapshot=metadata_snapshot,
            change_description=data.get('change_description'),
            changed_by=data.get('changed_by')
        )

        db.session.add(version)
        db.session.commit()

        return jsonify({
            'version_id': str(version.id),
            'version_number': version.version_number,
            'version_label': version.version_label,
            'created_at': version.created_at.isoformat()
        }), 201

    except Exception as e:
        logger.exception(f"Error creating version: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/versions/<string:header_id>/list', methods=['GET'])
def list_versions(header_id):
    """
    Lista todas las versiones de un archivo

    Returns:
        {
            "total": 3,
            "versions": [
                {
                    "version_number": 3,
                    "version_label": "v3.0",
                    "change_description": "...",
                    "created_at": "..."
                },
                ...
            ]
        }
    """
    try:
        header = STEPFileHeader.query.get(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        versions = FileVersion.query.filter_by(
            header_id=header.id
        ).order_by(FileVersion.version_number.desc()).all()

        return jsonify({
            'total': len(versions),
            'versions': [
                {
                    'version_id': str(v.id),
                    'version_number': v.version_number,
                    'version_label': v.version_label,
                    'file_hash': v.file_hash,
                    'change_description': v.change_description,
                    'changed_by': v.changed_by,
                    'created_at': v.created_at.isoformat()
                }
                for v in versions
            ]
        }), 200

    except Exception as e:
        logger.exception(f"Error listing versions: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/similarity', methods=['POST'])
def calculate_similarity():
    """
    Calcula similitud entre dos archivos sin guardar

    Body:
        {
            "file1_id": "uuid",
            "file2_id": "uuid",
            "include_geometry": true
        }

    Returns:
        {
            "similarity_score": 0.95,
            "file1_name": "...",
            "file2_name": "..."
        }
    """
    try:
        data = request.get_json()
        file1_id = data.get('file1_id')
        file2_id = data.get('file2_id')
        include_geometry = data.get('include_geometry', False)

        if not file1_id or not file2_id:
            return jsonify({'error': 'file1_id and file2_id required'}), 400

        header1 = STEPFileHeader.query.get(file1_id)
        header2 = STEPFileHeader.query.get(file2_id)

        if not header1 or not header2:
            return jsonify({'error': 'One or both files not found'}), 404

        header1_dict = {
            'file_name': header1.file_name,
            'file_schema': header1.file_schema,
            'total_entities': header1.total_entities
        }

        header2_dict = {
            'file_name': header2.file_name,
            'file_schema': header2.file_schema,
            'total_entities': header2.total_entities
        }

        shape1 = None
        shape2 = None

        def _pp(h):
            part = h.part if h else None
            return part.file_path if part else None

        p1, p2 = _pp(header1), _pp(header2)
        if include_geometry and p1 and p2:
            try:
                shape1 = load_step_shape(p1, 0)
                shape2 = load_step_shape(p2, 0)
            except Exception:
                pass

        similarity = ComparisonTools.calculate_similarity(
            header1_dict,
            header2_dict,
            shape1,
            shape2
        )

        return jsonify({
            'similarity_score': similarity,
            'file1_name': header1.file_name,
            'file2_name': header2.file_name,
            'file1_id': str(header1.id),
            'file2_id': str(header2.id)
        }), 200

    except Exception as e:
        logger.exception(f"Error calculating similarity: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/batch-compare', methods=['POST'])
def batch_compare():
    """
    Compara un archivo con múltiples otros archivos

    Body:
        {
            "base_file_id": "uuid",
            "compare_file_ids": ["uuid1", "uuid2", "uuid3"],
            "include_geometry": false
        }

    Returns:
        {
            "base_file_name": "...",
            "comparisons": [
                {
                    "file_id": "uuid1",
                    "file_name": "...",
                    "similarity_score": 0.95,
                    "has_changes": false
                },
                ...
            ]
        }
    """
    try:
        data = request.get_json()
        base_file_id = data.get('base_file_id')
        compare_file_ids = data.get('compare_file_ids', [])
        include_geometry = data.get('include_geometry', False)

        if not base_file_id or not compare_file_ids:
            return jsonify({'error': 'base_file_id and compare_file_ids required'}), 400

        base_header = STEPFileHeader.query.get(base_file_id)
        if not base_header:
            return jsonify({'error': 'Base file not found'}), 404

        results = []

        for file_id in compare_file_ids:
            try:
                compare_header = STEPFileHeader.query.get(file_id)
                if not compare_header:
                    results.append({
                        'file_id': file_id,
                        'error': 'File not found'
                    })
                    continue

                # Ejecutar comparación rápida
                base_dict = {
                    'file_schema': base_header.file_schema,
                    'total_entities': base_header.total_entities
                }
                compare_dict = {
                    'file_schema': compare_header.file_schema,
                    'total_entities': compare_header.total_entities
                }

                similarity = ComparisonTools.calculate_similarity(
                    base_dict,
                    compare_dict
                )

                results.append({
                    'file_id': str(compare_header.id),
                    'file_name': compare_header.file_name,
                    'similarity_score': similarity,
                    'has_changes': similarity < 0.99
                })

            except Exception as e:
                logger.exception(f"Error comparing with {file_id}: {e}")
                results.append({
                    'file_id': file_id,
                    'error': str(e)
                })

        return jsonify({
            'base_file_id': str(base_header.id),
            'base_file_name': base_header.file_name,
            'total_compared': len(results),
            'comparisons': results
        }), 200

    except Exception as e:
        logger.exception(f"Error in batch compare: {e}")
        return jsonify({'error': str(e)}), 500


logger.info("[OK] Comparison API routes loaded")
