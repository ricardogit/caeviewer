"""
Analysis API Routes - Endpoints para análisis avanzado de archivos STEP
"""

from flask import Blueprint, jsonify, request
import logging

from app.step_view_pro.models import STEPFileHeader, STEPEntity
from app.extensions import db
from app.step_view_pro.backend.analysis import (
    AnalysisTools,
    StatisticalAnalyzer,
    STEPValidator,
    AnomalyDetector,
    QualityChecker
)

logger = logging.getLogger(__name__)
bp = Blueprint('analysis_api', __name__)


@bp.route('/<string:header_id>/analyze', methods=['POST'])
def analyze_file(header_id):
    """
    Análisis completo de un archivo STEP

    Returns:
        {
            "file_id": "uuid",
            "file_name": "part.step",
            "basic_stats": {...},
            "complexity_analysis": {...},
            "quality_metrics": {...},
            "graph_analysis": {...},
            "overall_score": 85.5,
            "classification": "medium_complexity"
        }
    """
    try:
        header = STEPFileHeader.query.get(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        # Cargar entidades (sample para archivos grandes)
        max_entities = 10000
        entities_query = STEPEntity.query.filter_by(header_id=header.id)
        total_count = entities_query.count()

        if total_count > max_entities:
            # Muestreo
            entities = entities_query.limit(max_entities).all()
            logger.info(f"Sampling {max_entities} of {total_count} entities for analysis")
        else:
            entities = entities_query.all()

        # Convertir a dicts
        header_dict = {
            'id': str(header.id),
            'file_name': header.file_name,
            'file_schema': header.file_schema,
            'total_entities': header.total_entities,
            'total_references': header.total_references,
            'max_depth': header.max_depth,
            'root_entities': header.root_entities,
            'leaf_entities': header.leaf_entities,
            'file_size_bytes': header.file_size_bytes
        }

        entities_list = [
            {
                'entity_id': str(e.entity_id),
                'entity_type': e.entity_type,
                'depth': e.depth,
                'references': e.references or [],
                'referenced_by': e.referenced_by or []
            }
            for e in entities
        ]

        # Ejecutar análisis
        report = AnalysisTools.generate_analysis_report(header_dict, entities_list)

        return jsonify(report.to_dict()), 200

    except Exception as e:
        logger.exception(f"Error analyzing file: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/validate', methods=['POST'])
def validate_file(header_id):
    """
    Validación completa de un archivo STEP

    Returns:
        {
            "is_valid": true,
            "score": 95.0,
            "errors": [],
            "warnings": [...],
            "info": [...]
        }
    """
    try:
        header = STEPFileHeader.query.get(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        # Cargar entidades
        entities = STEPEntity.query.filter_by(header_id=header.id).limit(10000).all()

        header_dict = {
            'file_schema': header.file_schema,
            'total_entities': header.total_entities
        }

        entities_list = [
            {
                'entity_id': str(e.entity_id),
                'entity_type': e.entity_type,
                'references': e.references or []
            }
            for e in entities
        ]

        # Ejecutar validación
        result = STEPValidator.validate_complete(header_dict, entities_list)

        return jsonify(result.to_dict()), 200

    except Exception as e:
        logger.exception(f"Error validating file: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/complexity', methods=['GET'])
def get_complexity(header_id):
    """
    Análisis de complejidad

    Returns:
        {
            "complexity_score": 65.5,
            "cyclomatic_complexity": 150,
            "structural_complexity": 25.3,
            "type_diversity": 0.25,
            "classification": "complex",
            "factors": {...}
        }
    """
    try:
        header = STEPFileHeader.query.get(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        entities = STEPEntity.query.filter_by(header_id=header.id).limit(10000).all()

        header_dict = {
            'max_depth': header.max_depth
        }

        entities_list = [
            {
                'entity_type': e.entity_type,
                'references': e.references or []
            }
            for e in entities
        ]

        complexity = AnalysisTools.calculate_complexity_score(header_dict, entities_list)

        return jsonify(complexity), 200

    except Exception as e:
        logger.exception(f"Error calculating complexity: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/quality', methods=['GET'])
def get_quality_metrics(header_id):
    """
    Métricas de calidad

    Returns:
        {
            "quality_score": 92.5,
            "completeness": 95.0,
            "consistency": 98.0,
            "orphan_count": 10,
            "orphan_percentage": 1.5,
            "invalid_references": 5,
            "issues": [...]
        }
    """
    try:
        header = STEPFileHeader.query.get(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        entities = STEPEntity.query.filter_by(header_id=header.id).limit(10000).all()

        header_dict = {}

        entities_list = [
            {
                'entity_id': str(e.entity_id),
                'entity_type': e.entity_type,
                'references': e.references or [],
                'referenced_by': e.referenced_by or []
            }
            for e in entities
        ]

        quality = AnalysisTools.calculate_quality_metrics(header_dict, entities_list)

        return jsonify(quality), 200

    except Exception as e:
        logger.exception(f"Error calculating quality: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/anomalies', methods=['GET'])
def detect_anomalies(header_id):
    """
    Detección de anomalías

    Returns:
        {
            "total_anomalies": 2,
            "anomalies": [
                {
                    "type": "size_anomaly",
                    "severity": "high",
                    "message": "...",
                    "z_score": 4.5
                }
            ],
            "size_analysis": {...},
            "complexity_analysis": {...}
        }
    """
    try:
        current_header = STEPFileHeader.query.get(header_id)
        if not current_header:
            return jsonify({'error': 'File not found'}), 404

        # Obtener headers históricos (misma fuente/categoría)
        historical_headers = STEPFileHeader.query.filter(
            STEPFileHeader.id != current_header.id
        ).limit(100).all()

        historical_dicts = [
            {
                'file_size_bytes': h.file_size_bytes,
                'total_entities': h.total_entities
            }
            for h in historical_headers
        ]

        current_dict = {
            'file_size_bytes': current_header.file_size_bytes,
            'total_entities': current_header.total_entities
        }

        # Detectar anomalías
        anomalies = AnomalyDetector.detect_all_anomalies(historical_dicts, current_dict)

        return jsonify(anomalies), 200

    except Exception as e:
        logger.exception(f"Error detecting anomalies: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:header_id>/quality-checks', methods=['GET'])
def run_quality_checks(header_id):
    """
    Checks de calidad específicos

    Returns:
        {
            "naming_conventions": {...},
            "geometry_validity": {...}
        }
    """
    try:
        header = STEPFileHeader.query.get(header_id)
        if not header:
            return jsonify({'error': 'File not found'}), 404

        entities = STEPEntity.query.filter_by(header_id=header.id).limit(1000).all()

        entities_list = [
            {
                'entity_id': str(e.entity_id),
                'entity_type': e.entity_type
            }
            for e in entities
        ]

        naming = QualityChecker.check_naming_conventions(entities_list)
        geometry = QualityChecker.check_geometry_validity(entities_list)

        return jsonify({
            'naming_conventions': naming,
            'geometry_validity': geometry
        }), 200

    except Exception as e:
        logger.exception(f"Error running quality checks: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/batch/statistics', methods=['POST'])
def batch_statistics():
    """
    Estadísticas de múltiples archivos

    Body:
        {
            "header_ids": ["uuid1", "uuid2", "uuid3"]
        }

    Returns:
        {
            "total_files": 3,
            "aggregated_stats": {...},
            "correlations": {...}
        }
    """
    try:
        data = request.get_json()
        header_ids = data.get('header_ids', [])

        if not header_ids:
            return jsonify({'error': 'header_ids required'}), 400

        headers = STEPFileHeader.query.filter(
            STEPFileHeader.id.in_(header_ids)
        ).all()

        if not headers:
            return jsonify({'error': 'No files found'}), 404

        headers_dicts = [
            {
                'id': str(h.id),
                'file_name': h.file_name,
                'total_entities': h.total_entities,
                'total_references': h.total_references,
                'max_depth': h.max_depth,
                'file_size_bytes': h.file_size_bytes
            }
            for h in headers
        ]

        # Calcular correlaciones
        correlations = StatisticalAnalyzer.calculate_correlations(headers_dicts)

        # Estadísticas agregadas
        import statistics as stats

        aggregated = {
            'total_files': len(headers),
            'avg_entities': round(stats.mean([h['total_entities'] for h in headers_dicts if h['total_entities']]), 2),
            'avg_references': round(stats.mean([h['total_references'] for h in headers_dicts if h['total_references']]), 2),
            'avg_depth': round(stats.mean([h['max_depth'] for h in headers_dicts if h['max_depth']]), 2),
            'avg_size_mb': round(stats.mean([h['file_size_bytes'] / 1024 / 1024 for h in headers_dicts if h['file_size_bytes']]), 2)
        }

        return jsonify({
            'total_files': len(headers),
            'aggregated_stats': aggregated,
            'correlations': correlations
        }), 200

    except Exception as e:
        logger.exception(f"Error calculating batch statistics: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/outliers', methods=['POST'])
def detect_outliers():
    """
    Detección de outliers en una métrica

    Body:
        {
            "metric": "total_entities",
            "method": "iqr",  // o "zscore"
            "limit": 100
        }

    Returns:
        {
            "outliers": [...],
            "count": 5,
            "method": "iqr",
            "bounds": {...}
        }
    """
    try:
        data = request.get_json()
        metric = data.get('metric', 'total_entities')
        method = data.get('method', 'iqr')
        limit = data.get('limit', 100)

        valid_metrics = {
            'total_entities',
            'total_references',
            'max_depth',
            'file_size_bytes'
        }

        if metric not in valid_metrics:
            return jsonify({'error': f'Invalid metric. Use one of: {valid_metrics}'}), 400

        # Obtener valores
        headers = STEPFileHeader.query.limit(limit).all()
        values = [getattr(h, metric, 0) for h in headers if getattr(h, metric, 0) is not None]

        if not values:
            return jsonify({'error': 'No data available'}), 404

        # Detectar outliers
        outlier_result = StatisticalAnalyzer.detect_outliers(values, method=method)

        return jsonify(outlier_result), 200

    except Exception as e:
        logger.exception(f"Error detecting outliers: {e}")
        return jsonify({'error': str(e)}), 500


logger.info("[OK] Analysis API routes loaded")
