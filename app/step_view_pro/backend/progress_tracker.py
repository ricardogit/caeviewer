"""
Progress Tracker - Sistema de seguimiento de progreso para conversiones STEP
"""
import logging
import redis
import json
from datetime import datetime, timedelta
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class ProgressTracker:
    """
    Rastrea el progreso de conversiones de archivos STEP a GLB.

    Usa Redis para almacenar el estado del progreso de manera que múltiples
    workers y el frontend puedan acceder a la información.
    """

    def __init__(self, redis_client=None):
        """
        Inicializa el tracker con cliente Redis.

        Args:
            redis_client: Cliente Redis existente o None para crear uno nuevo
        """
        self.redis_client = redis_client
        self.key_prefix = "step_conversion_progress:"
        self.key_expiry = 3600  # 1 hora

        # Si no hay Redis, usar fallback en memoria
        self.fallback_storage = {}
        self.use_redis = False

        if redis_client:
            try:
                redis_client.ping()
                self.use_redis = True
                logger.info("ProgressTracker usando Redis")
            except Exception as e:
                logger.warning(f"Redis no disponible, usando almacenamiento en memoria: {e}")
        else:
            logger.warning("Redis no configurado, usando almacenamiento en memoria")

    def _get_key(self, job_id: str) -> str:
        """Genera clave Redis para un job específico."""
        return f"{self.key_prefix}{job_id}"

    def start_job(self, job_id: str, filename: str, total_steps: int = 100):
        """
        Inicia tracking de un nuevo job de conversión.

        Args:
            job_id: ID único del job (usualmente part_id o file_hash)
            filename: Nombre del archivo siendo procesado
            total_steps: Total de pasos (para calcular porcentaje)
        """
        data = {
            'job_id': job_id,
            'filename': filename,
            'status': 'started',
            'progress': 0,
            'current_step': 'Iniciando conversión',
            'total_steps': total_steps,
            'started_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
            'error': None
        }

        self._save(job_id, data)
        logger.info(f"Job iniciado: {job_id} - {filename}")

    def update_progress(
        self,
        job_id: str,
        progress: int,
        current_step: str,
        details: Optional[str] = None
    ):
        """
        Actualiza el progreso de un job.

        Args:
            job_id: ID del job
            progress: Progreso actual (0-100)
            current_step: Descripción del paso actual
            details: Detalles adicionales opcionales
        """
        data = self.get_progress(job_id)
        if not data:
            logger.warning(f"Job {job_id} no encontrado, creando nuevo")
            self.start_job(job_id, "unknown", 100)
            data = self.get_progress(job_id)

        data['progress'] = min(progress, 100)
        data['current_step'] = current_step
        data['status'] = 'processing'
        data['updated_at'] = datetime.utcnow().isoformat()

        if details:
            data['details'] = details

        self._save(job_id, data)
        logger.debug(f"Progreso actualizado: {job_id} - {progress}% - {current_step}")

    def complete_job(self, job_id: str, output_path: Optional[str] = None):
        """
        Marca un job como completado.

        Args:
            job_id: ID del job
            output_path: Ruta del archivo GLB generado
        """
        data = self.get_progress(job_id)
        if not data:
            logger.warning(f"Job {job_id} no encontrado")
            return

        data['status'] = 'completed'
        data['progress'] = 100
        data['current_step'] = 'Conversión completada'
        data['completed_at'] = datetime.utcnow().isoformat()
        data['updated_at'] = datetime.utcnow().isoformat()

        if output_path:
            data['output_path'] = output_path

        self._save(job_id, data)
        logger.info(f"Job completado: {job_id}")

    def fail_job(self, job_id: str, error: str):
        """
        Marca un job como fallido.

        Args:
            job_id: ID del job
            error: Mensaje de error
        """
        data = self.get_progress(job_id)
        if not data:
            logger.warning(f"Job {job_id} no encontrado")
            return

        data['status'] = 'failed'
        data['error'] = error
        data['failed_at'] = datetime.utcnow().isoformat()
        data['updated_at'] = datetime.utcnow().isoformat()

        self._save(job_id, data)
        logger.error(f"Job fallido: {job_id} - {error}")

    def get_progress(self, job_id: str) -> Optional[Dict]:
        """
        Obtiene el progreso actual de un job.

        Args:
            job_id: ID del job

        Returns:
            Dict con datos de progreso o None si no existe
        """
        if self.use_redis:
            try:
                key = self._get_key(job_id)
                data = self.redis_client.get(key)
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.error(f"Error obteniendo progreso de Redis: {e}")

        # Fallback a memoria
        return self.fallback_storage.get(job_id)

    def _save(self, job_id: str, data: Dict):
        """Guarda datos de progreso (Redis o memoria)."""
        if self.use_redis:
            try:
                key = self._get_key(job_id)
                self.redis_client.setex(
                    key,
                    self.key_expiry,
                    json.dumps(data)
                )
                return
            except Exception as e:
                logger.error(f"Error guardando en Redis: {e}")

        # Fallback a memoria
        self.fallback_storage[job_id] = data

    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """
        Limpia jobs antiguos de la memoria (Redis expira automáticamente).

        Args:
            max_age_hours: Edad máxima en horas
        """
        if not self.use_redis:
            cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
            to_delete = []

            for job_id, data in self.fallback_storage.items():
                updated_at = datetime.fromisoformat(data.get('updated_at', '2000-01-01'))
                if updated_at < cutoff:
                    to_delete.append(job_id)

            for job_id in to_delete:
                del self.fallback_storage[job_id]

            if to_delete:
                logger.info(f"Limpiados {len(to_delete)} jobs antiguos")


# Instancia global del tracker
_tracker_instance = None


def get_progress_tracker(redis_client=None) -> ProgressTracker:
    """
    Obtiene la instancia global del ProgressTracker.

    Args:
        redis_client: Cliente Redis (solo necesario la primera vez)

    Returns:
        Instancia de ProgressTracker
    """
    global _tracker_instance

    if _tracker_instance is None:
        _tracker_instance = ProgressTracker(redis_client)

    return _tracker_instance
