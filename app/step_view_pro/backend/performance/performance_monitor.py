"""
Performance Monitor - Monitoreo y análisis de performance del sistema
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Monitoreo de tiempo de ejecución
- Uso de memoria
- Uso de CPU
- Análisis de queries SQL
- Profiling de funciones
- Métricas agregadas
"""

import logging
import time
import psutil
import functools
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """
    Monitor de performance del sistema
    """

    def __init__(self, db_session=None):
        """
        Inicializa monitor

        Args:
            db_session: SQLAlchemy session para guardar métricas
        """
        self.db = db_session
        self.process = psutil.Process()

    @contextmanager
    def measure(self, metric_type: str, metric_name: str,
                save_to_db: bool = False, metadata: Optional[Dict] = None):
        """
        Context manager para medir performance

        Args:
            metric_type: Tipo de métrica ('query', 'api', 'processing')
            metric_name: Nombre de la métrica
            save_to_db: Guardar en base de datos
            metadata: Metadata adicional

        Usage:
            with monitor.measure('api', 'get_geometry'):
                result = expensive_operation()
        """
        start_time = time.time()
        start_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        start_cpu = self.process.cpu_percent()

        try:
            yield
        finally:
            duration_ms = (time.time() - start_time) * 1000
            end_memory = self.process.memory_info().rss / 1024 / 1024
            memory_delta = end_memory - start_memory
            cpu_percent = self.process.cpu_percent()

            logger.debug(
                f"PERF [{metric_type}:{metric_name}] "
                f"Duration: {duration_ms:.2f}ms, "
                f"Memory: {memory_delta:+.2f}MB, "
                f"CPU: {cpu_percent:.1f}%"
            )

            if save_to_db and self.db:
                self._save_metric(
                    metric_type, metric_name,
                    duration_ms, memory_delta, cpu_percent,
                    metadata
                )

    def _save_metric(self, metric_type: str, metric_name: str,
                     duration_ms: float, memory_mb: float, cpu_percent: float,
                     metadata: Optional[Dict]):
        """Guarda métrica en base de datos"""
        from app.step_view_pro.models import PerformanceMetric

        try:
            metric = PerformanceMetric(
                metric_type=metric_type,
                metric_name=metric_name,
                duration_ms=duration_ms,
                memory_mb=memory_mb,
                cpu_percent=cpu_percent,
                metric_metadata=metadata or {}
            )
            self.db.add(metric)
            self.db.commit()

        except Exception as e:
            logger.exception(f"Error saving performance metric: {e}")
            self.db.rollback()

    def get_metrics(self, metric_type: Optional[str] = None,
                    metric_name: Optional[str] = None,
                    hours: int = 24,
                    limit: int = 1000) -> list:
        """
        Obtiene métricas registradas

        Args:
            metric_type: Filtrar por tipo
            metric_name: Filtrar por nombre
            hours: Últimas N horas
            limit: Máximo de resultados

        Returns:
            Lista de métricas
        """
        from app.step_view_pro.models import PerformanceMetric

        try:
            query = PerformanceMetric.query

            if metric_type:
                query = query.filter_by(metric_type=metric_type)

            if metric_name:
                query = query.filter_by(metric_name=metric_name)

            if hours:
                since = datetime.utcnow() - timedelta(hours=hours)
                query = query.filter(PerformanceMetric.measured_at >= since)

            query = query.order_by(PerformanceMetric.measured_at.desc())
            query = query.limit(limit)

            metrics = query.all()

            return [
                {
                    'id': str(m.id),
                    'metric_type': m.metric_type,
                    'metric_name': m.metric_name,
                    'duration_ms': m.duration_ms,
                    'memory_mb': m.memory_mb,
                    'cpu_percent': m.cpu_percent,
                    'metadata': m.metric_metadata,
                    'measured_at': m.measured_at.isoformat()
                }
                for m in metrics
            ]

        except Exception as e:
            logger.exception(f"Error getting metrics: {e}")
            return []

    def get_aggregated_metrics(self, metric_type: Optional[str] = None,
                               metric_name: Optional[str] = None,
                               hours: int = 24) -> Dict:
        """
        Obtiene métricas agregadas

        Args:
            metric_type: Filtrar por tipo
            metric_name: Filtrar por nombre
            hours: Últimas N horas

        Returns:
            Dict con estadísticas agregadas
        """
        from app.step_view_pro.models import PerformanceMetric
        from sqlalchemy import func

        try:
            query = self.db.query(
                func.count(PerformanceMetric.id).label('count'),
                func.avg(PerformanceMetric.duration_ms).label('avg_duration'),
                func.min(PerformanceMetric.duration_ms).label('min_duration'),
                func.max(PerformanceMetric.duration_ms).label('max_duration'),
                func.avg(PerformanceMetric.memory_mb).label('avg_memory'),
                func.avg(PerformanceMetric.cpu_percent).label('avg_cpu')
            )

            if metric_type:
                query = query.filter(PerformanceMetric.metric_type == metric_type)

            if metric_name:
                query = query.filter(PerformanceMetric.metric_name == metric_name)

            if hours:
                since = datetime.utcnow() - timedelta(hours=hours)
                query = query.filter(PerformanceMetric.measured_at >= since)

            result = query.first()

            if not result or result.count == 0:
                return {
                    'count': 0,
                    'avg_duration_ms': 0,
                    'min_duration_ms': 0,
                    'max_duration_ms': 0,
                    'avg_memory_mb': 0,
                    'avg_cpu_percent': 0
                }

            return {
                'count': result.count,
                'avg_duration_ms': round(result.avg_duration, 2) if result.avg_duration else 0,
                'min_duration_ms': round(result.min_duration, 2) if result.min_duration else 0,
                'max_duration_ms': round(result.max_duration, 2) if result.max_duration else 0,
                'avg_memory_mb': round(result.avg_memory, 2) if result.avg_memory else 0,
                'avg_cpu_percent': round(result.avg_cpu, 2) if result.avg_cpu else 0
            }

        except Exception as e:
            logger.exception(f"Error getting aggregated metrics: {e}")
            return {}

    def get_system_stats(self) -> Dict:
        """
        Obtiene estadísticas del sistema actual

        Returns:
            Dict con CPU, memoria, disco
        """
        try:
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
                'cpu_percent': psutil.cpu_percent(interval=0.1),
                'cpu_count': psutil.cpu_count(),
                'memory_total_gb': round(memory.total / 1024 / 1024 / 1024, 2),
                'memory_used_gb': round(memory.used / 1024 / 1024 / 1024, 2),
                'memory_percent': memory.percent,
                'disk_total_gb': round(disk.total / 1024 / 1024 / 1024, 2),
                'disk_used_gb': round(disk.used / 1024 / 1024 / 1024, 2),
                'disk_percent': disk.percent,
                'timestamp': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.exception(f"Error getting system stats: {e}")
            return {}

    def cleanup_old_metrics(self, days: int = 7) -> int:
        """
        Elimina métricas antiguas

        Args:
            days: Eliminar métricas más antiguas que N días

        Returns:
            Número de métricas eliminadas
        """
        from app.step_view_pro.models import PerformanceMetric

        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            count = PerformanceMetric.query.filter(
                PerformanceMetric.measured_at < cutoff
            ).delete()

            self.db.commit()
            logger.info(f"Cleaned up {count} old performance metrics")
            return count

        except Exception as e:
            logger.exception(f"Error cleaning up metrics: {e}")
            self.db.rollback()
            return 0


def timed(metric_type: str, metric_name: str, save_to_db: bool = False):
    """
    Decorator para medir tiempo de ejecución de funciones

    Args:
        metric_type: Tipo de métrica
        metric_name: Nombre de la métrica
        save_to_db: Guardar en base de datos

    Usage:
        @timed('processing', 'parse_step_file', save_to_db=True)
        def parse_step_file(file_path):
            # expensive operation
            return result
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.time() - start_time) * 1000
                logger.debug(
                    f"PERF [{metric_type}:{metric_name}:{func.__name__}] "
                    f"Duration: {duration_ms:.2f}ms"
                )

                if save_to_db:
                    # Guardar métrica (requiere monitor global)
                    try:
                        from app import performance_monitor
                        performance_monitor._save_metric(
                            metric_type, metric_name,
                            duration_ms, 0, 0, None
                        )
                    except:
                        pass

        return wrapper
    return decorator


logger.info("OK Performance Monitor module loaded")
