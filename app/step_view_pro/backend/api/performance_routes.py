"""
Performance API Routes - Endpoints para monitoreo y optimización de performance
"""

from flask import Blueprint, jsonify, request
import logging

from app.extensions import db
from app.step_view_pro.backend.performance.cache_manager import PostgreSQLCacheManager
from app.step_view_pro.backend.performance.performance_monitor import PerformanceMonitor
from app.step_view_pro.backend.performance.query_optimizer import QueryOptimizer

logger = logging.getLogger(__name__)
bp = Blueprint('performance_api', __name__)

# Instancias globales (inicializadas en app startup)
cache_manager = None
performance_monitor = None
query_optimizer = None


def init_performance_tools(redis_url=None):
    """Inicializa herramientas de performance"""
    global cache_manager, performance_monitor, query_optimizer

    cache_manager = PostgreSQLCacheManager(db.session, redis_url=redis_url)
    performance_monitor = PerformanceMonitor(db.session)
    query_optimizer = QueryOptimizer(db.session)

    logger.info("[OK] Performance tools initialized")


@bp.route('/cache/stats', methods=['GET'])
def get_cache_stats():
    """
    Obtiene estadísticas de cache

    Returns:
        {
            "l1_hits": 150,
            "l1_misses": 50,
            "l1_hit_rate": 75.0,
            "l2_hits": 30,
            "l2_misses": 20,
            "l2_hit_rate": 60.0,
            "total_gets": 200,
            "total_sets": 100,
            "redis_enabled": true
        }
    """
    try:
        if not cache_manager:
            return jsonify({'error': 'Cache manager not initialized'}), 500

        stats = cache_manager.get_stats()
        return jsonify(stats), 200

    except Exception as e:
        logger.exception(f"Error getting cache stats: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/cache/clear', methods=['POST'])
def clear_cache():
    """
    Limpia cache

    Body:
        {
            "namespace": "geometry",  // opcional
            "clear_stats": false
        }

    Returns:
        {
            "success": true,
            "keys_deleted": 150
        }
    """
    try:
        if not cache_manager:
            return jsonify({'error': 'Cache manager not initialized'}), 500

        data = request.get_json() or {}
        namespace = data.get('namespace')
        clear_stats = data.get('clear_stats', False)

        if namespace:
            count = cache_manager.invalidate_namespace(namespace)
        else:
            # Limpiar todos los namespaces comunes
            count = 0
            for ns in ['geometry', 'tree', 'features', 'pmi', 'measurements']:
                count += cache_manager.invalidate_namespace(ns)

        if clear_stats:
            cache_manager.clear_stats()

        return jsonify({
            'success': True,
            'keys_deleted': count
        }), 200

    except Exception as e:
        logger.exception(f"Error clearing cache: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/cache/cleanup', methods=['POST'])
def cleanup_expired_cache():
    """
    Limpia entradas expiradas del cache L2

    Returns:
        {
            "success": true,
            "entries_deleted": 50
        }
    """
    try:
        if not cache_manager:
            return jsonify({'error': 'Cache manager not initialized'}), 500

        count = cache_manager.cleanup_expired()

        return jsonify({
            'success': True,
            'entries_deleted': count
        }), 200

    except Exception as e:
        logger.exception(f"Error cleaning up cache: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/metrics', methods=['GET'])
def get_performance_metrics():
    """
    Obtiene métricas de performance

    Query params:
        metric_type: Filtrar por tipo
        metric_name: Filtrar por nombre
        hours: Últimas N horas (default: 24)
        limit: Máximo de resultados (default: 1000)

    Returns:
        {
            "metrics": [...],
            "count": 150
        }
    """
    try:
        if not performance_monitor:
            return jsonify({'error': 'Performance monitor not initialized'}), 500

        metric_type = request.args.get('metric_type')
        metric_name = request.args.get('metric_name')
        hours = int(request.args.get('hours', 24))
        limit = int(request.args.get('limit', 1000))

        metrics = performance_monitor.get_metrics(
            metric_type=metric_type,
            metric_name=metric_name,
            hours=hours,
            limit=limit
        )

        return jsonify({
            'metrics': metrics,
            'count': len(metrics)
        }), 200

    except Exception as e:
        logger.exception(f"Error getting metrics: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/metrics/aggregated', methods=['GET'])
def get_aggregated_metrics():
    """
    Obtiene métricas agregadas

    Query params:
        metric_type: Filtrar por tipo
        metric_name: Filtrar por nombre
        hours: Últimas N horas

    Returns:
        {
            "count": 100,
            "avg_duration_ms": 250.5,
            "min_duration_ms": 50.0,
            "max_duration_ms": 1200.0,
            "avg_memory_mb": 5.2,
            "avg_cpu_percent": 15.3
        }
    """
    try:
        if not performance_monitor:
            return jsonify({'error': 'Performance monitor not initialized'}), 500

        metric_type = request.args.get('metric_type')
        metric_name = request.args.get('metric_name')
        hours = int(request.args.get('hours', 24))

        metrics = performance_monitor.get_aggregated_metrics(
            metric_type=metric_type,
            metric_name=metric_name,
            hours=hours
        )

        return jsonify(metrics), 200

    except Exception as e:
        logger.exception(f"Error getting aggregated metrics: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/system', methods=['GET'])
def get_system_stats():
    """
    Obtiene estadísticas del sistema

    Returns:
        {
            "cpu_percent": 25.5,
            "cpu_count": 8,
            "memory_total_gb": 16.0,
            "memory_used_gb": 8.5,
            "memory_percent": 53.1,
            "disk_total_gb": 500.0,
            "disk_used_gb": 250.0,
            "disk_percent": 50.0,
            "timestamp": "2025-01-07T12:00:00Z"
        }
    """
    try:
        if not performance_monitor:
            return jsonify({'error': 'Performance monitor not initialized'}), 500

        stats = performance_monitor.get_system_stats()
        return jsonify(stats), 200

    except Exception as e:
        logger.exception(f"Error getting system stats: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/metrics/cleanup', methods=['POST'])
def cleanup_old_metrics():
    """
    Elimina métricas antiguas

    Body:
        {
            "days": 7
        }

    Returns:
        {
            "success": true,
            "metrics_deleted": 500
        }
    """
    try:
        if not performance_monitor:
            return jsonify({'error': 'Performance monitor not initialized'}), 500

        data = request.get_json() or {}
        days = data.get('days', 7)

        count = performance_monitor.cleanup_old_metrics(days=days)

        return jsonify({
            'success': True,
            'metrics_deleted': count
        }), 200

    except Exception as e:
        logger.exception(f"Error cleaning up metrics: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/query/analyze', methods=['POST'])
def analyze_query():
    """
    Analiza un query SQL para detectar problemas

    Body:
        {
            "query": "SELECT * FROM step_entities WHERE ..."
        }

    Returns:
        {
            "statement": "...",
            "issues": ["Using SELECT *", "No LIMIT clause"],
            "suggestions": ["Specify only needed columns", "Add LIMIT"],
            "complexity_score": 2
        }
    """
    try:
        if not query_optimizer:
            return jsonify({'error': 'Query optimizer not initialized'}), 500

        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({'error': 'query required in body'}), 400

        # TODO: Implementar análisis de query string
        # Por ahora retornamos análisis simple

        return jsonify({
            'statement': data['query'],
            'issues': [],
            'suggestions': [],
            'complexity_score': 0
        }), 200

    except Exception as e:
        logger.exception(f"Error analyzing query: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/query/slow', methods=['GET'])
def get_slow_queries():
    """
    Obtiene queries lentos del log

    Query params:
        threshold_ms: Threshold en milisegundos

    Returns:
        {
            "slow_queries": [
                {
                    "statement": "SELECT ...",
                    "duration_ms": 1500.0,
                    "timestamp": "..."
                }
            ],
            "count": 5
        }
    """
    try:
        if not query_optimizer:
            return jsonify({'error': 'Query optimizer not initialized'}), 500

        threshold_ms = int(request.args.get('threshold_ms', 1000))

        slow_queries = query_optimizer.get_slow_queries(threshold_ms=threshold_ms)

        return jsonify({
            'slow_queries': slow_queries,
            'count': len(slow_queries)
        }), 200

    except Exception as e:
        logger.exception(f"Error getting slow queries: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/optimize/suggestions', methods=['GET'])
def get_optimization_suggestions():
    """
    Obtiene sugerencias de optimización general

    Returns:
        {
            "cache_suggestions": [...],
            "query_suggestions": [...],
            "index_suggestions": [...]
        }
    """
    try:
        suggestions = {
            'cache_suggestions': [],
            'query_suggestions': [],
            'index_suggestions': []
        }

        # Cache suggestions
        if cache_manager:
            stats = cache_manager.get_stats()
            if stats['l1_hit_rate'] < 50:
                suggestions['cache_suggestions'].append({
                    'type': 'low_hit_rate',
                    'message': f"Low L1 cache hit rate ({stats['l1_hit_rate']}%). Consider increasing cache TTL.",
                    'priority': 'medium'
                })

        # Query suggestions
        if query_optimizer:
            slow_queries = query_optimizer.get_slow_queries()
            if len(slow_queries) > 10:
                suggestions['query_suggestions'].append({
                    'type': 'many_slow_queries',
                    'message': f"Found {len(slow_queries)} slow queries. Review and optimize.",
                    'priority': 'high'
                })

        # Sistema suggestions
        if performance_monitor:
            system_stats = performance_monitor.get_system_stats()
            if system_stats.get('memory_percent', 0) > 80:
                suggestions['cache_suggestions'].append({
                    'type': 'high_memory',
                    'message': f"High memory usage ({system_stats['memory_percent']}%). Consider clearing cache.",
                    'priority': 'high'
                })

        return jsonify(suggestions), 200

    except Exception as e:
        logger.exception(f"Error getting suggestions: {e}")
        return jsonify({'error': str(e)}), 500


logger.info("[OK] Performance API routes loaded")
