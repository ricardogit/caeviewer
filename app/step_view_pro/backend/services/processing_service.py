"""
Processing Service - Servicio de procesamiento en background
============================================================

Servicio para procesar archivos STEP en background:
1. Parsing de entidades
2. Conversión a GLB
3. Extracción de características
"""

import logging
import threading
import queue
import os
import json
from typing import Optional, Dict
from datetime import datetime

# Optional imports
try:
    from app.step_view_pro.backend.step_graph_parser import STEPGraphParser
    GRAPH_PARSER_AVAILABLE = True
except ImportError:
    GRAPH_PARSER_AVAILABLE = False
    logging.warning("step_graph_parser not available")

try:
    from app.step_view_pro.backend.step_to_glb_converter import STEPToGLBConverter, ConversionConfig
    GLB_CONVERTER_AVAILABLE = True
except ImportError:
    GLB_CONVERTER_AVAILABLE = False
    logging.warning("step_to_glb_converter not available")

from app.step_view_pro.models import STEPFileHeader
from app.models import Part
from app.extensions import db
from app.step_view_pro.backend.services.notification_service import notification_service

logger = logging.getLogger(__name__)


class ProcessingJob:
    """Representa un trabajo de procesamiento"""

    def __init__(self, job_id: str, model_id: str, file_path: str, quality: str = 'medium'):
        self.job_id = job_id
        self.model_id = model_id
        self.file_path = file_path
        self.quality = quality
        self.status = 'QUEUED'
        self.created_at = datetime.utcnow()
        self.started_at = None
        self.completed_at = None
        self.error = None


class ProcessingService:
    """
    Servicio para procesamiento asíncrono de archivos STEP
    """

    def __init__(self, num_workers: int = 2, output_dir: str = 'data/processed'):
        """
        Inicializar servicio de procesamiento

        Args:
            num_workers: Número de workers concurrentes
            output_dir: Directorio para archivos procesados
        """
        self.num_workers = num_workers
        self.output_dir = output_dir

        # Cola de trabajos
        self.job_queue = queue.Queue()

        # Dict de trabajos activos {model_id: ProcessingJob}
        self.active_jobs: Dict[str, ProcessingJob] = {}

        # Lock para thread safety
        self.lock = threading.Lock()

        # Workers
        self.workers = []
        self.running = False

        # Crear directorio de salida
        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"ProcessingService initialized with {num_workers} workers")

    def start(self) -> None:
        """Iniciar workers de procesamiento"""
        if self.running:
            logger.warning("ProcessingService already running")
            return

        self.running = True

        # Iniciar workers
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"ProcessingWorker-{i}",
                daemon=True
            )
            worker.start()
            self.workers.append(worker)

        logger.info(f"Started {self.num_workers} processing workers")

    def stop(self) -> None:
        """Detener workers de procesamiento"""
        if not self.running:
            return

        self.running = False

        # Enviar señal de parada a todos los workers
        for _ in range(self.num_workers):
            self.job_queue.put(None)

        # Esperar a que terminen
        for worker in self.workers:
            worker.join(timeout=5.0)

        self.workers = []
        logger.info("Stopped processing workers")

    def enqueue_processing(self, model_id: str, file_path: str, quality: str = 'medium') -> str:
        """
        Encolar un archivo para procesamiento

        Args:
            model_id: ID del modelo
            file_path: Ruta al archivo STEP
            quality: Calidad de conversión (low, medium, high, ultra)

        Returns:
            job_id del trabajo encolado
        """
        import uuid

        job_id = str(uuid.uuid4())

        job = ProcessingJob(
            job_id=job_id,
            model_id=model_id,
            file_path=file_path,
            quality=quality
        )

        with self.lock:
            self.active_jobs[model_id] = job

        # Agregar a cola
        self.job_queue.put(job)

        logger.info(f"Enqueued processing job: {job_id} for model {model_id}")

        return job_id

    def is_processing(self, model_id: str) -> bool:
        """
        Verificar si un modelo está en procesamiento

        Args:
            model_id: ID del modelo

        Returns:
            True si está en procesamiento
        """
        with self.lock:
            if model_id in self.active_jobs:
                job = self.active_jobs[model_id]
                return job.status in ['QUEUED', 'PROCESSING']
        return False

    def cancel_processing(self, model_id: str) -> bool:
        """
        Cancelar procesamiento de un modelo

        Args:
            model_id: ID del modelo

        Returns:
            True si se canceló exitosamente
        """
        with self.lock:
            if model_id in self.active_jobs:
                job = self.active_jobs[model_id]

                if job.status == 'QUEUED':
                    # Marcar como cancelado
                    job.status = 'CANCELLED'
                    del self.active_jobs[model_id]
                    logger.info(f"Cancelled queued job for model {model_id}")
                    return True
                elif job.status == 'PROCESSING':
                    # No se puede cancelar en medio del procesamiento
                    logger.warning(f"Cannot cancel processing job for model {model_id} (already started)")
                    return False

        return False

    def _worker_loop(self) -> None:
        """Loop principal del worker"""
        worker_name = threading.current_thread().name
        logger.info(f"{worker_name} started")

        while self.running:
            try:
                # Obtener siguiente trabajo (blocking con timeout)
                job = self.job_queue.get(timeout=1.0)

                # Señal de parada
                if job is None:
                    break

                # Verificar si fue cancelado
                if job.status == 'CANCELLED':
                    continue

                # Procesar trabajo
                self._process_job(job)

            except queue.Empty:
                # Timeout, continuar esperando
                continue

            except Exception as e:
                logger.error(f"{worker_name} error: {str(e)}", exc_info=True)

        logger.info(f"{worker_name} stopped")

    def _process_job(self, job: ProcessingJob) -> None:
        """
        Procesar un trabajo de conversión

        Args:
            job: Trabajo a procesar
        """
        model_id = job.model_id
        file_path = job.file_path

        try:
            # Actualizar estado
            job.status = 'PROCESSING'
            job.started_at = datetime.utcnow()

            logger.info(f"Processing started for model {model_id}")

            # Notificar inicio
            notification_service.notify_processing_started(model_id)

            # ETAPA 1: Parsing (0-33%)
            self._stage_parsing(model_id, file_path)

            # ETAPA 2: Conversión a GLB (33-66%)
            glb_path, thumbnail_path, metrics = self._stage_conversion(
                model_id,
                file_path,
                job.quality
            )

            # ETAPA 3: Extracción de características (66-100%)
            self._stage_feature_extraction(model_id, file_path)

            # Actualizar estado final
            job.status = 'COMPLETED'
            job.completed_at = datetime.utcnow()

            # Notificar finalización
            notification_service.notify_processing_complete(
                model_id=model_id,
                glb_url=f'/api/viewer/model/{model_id}/glb',
                thumbnail_url=f'/api/viewer/model/{model_id}/thumbnail',
                metrics=metrics
            )

            logger.info(f"Processing completed for model {model_id}")

        except Exception as e:
            # Error en procesamiento
            job.status = 'ERROR'
            job.error = str(e)

            logger.error(f"Processing error for model {model_id}: {str(e)}", exc_info=True)

            # Notificar error
            notification_service.notify_processing_error(
                model_id=model_id,
                error=str(e),
                stage=job.status,
                can_retry=True
            )

        finally:
            # Limpiar de trabajos activos
            with self.lock:
                if model_id in self.active_jobs:
                    del self.active_jobs[model_id]

    def _stage_parsing(self, model_id: str, file_path: str) -> dict:
        """
        Etapa 1: Parsing del archivo STEP

        Args:
            model_id: ID del modelo
            file_path: Ruta al archivo

        Returns:
            Resultado del parsing
        """
        notification_service.notify_progress(
            model_id,
            stage='parsing',
            progress=5,
            message='Parsing STEP file...'
        )

        # Parsear archivo
        parser = STEPGraphParser()
        result = parser.parse(file_path)

        # Actualizar BD con resultados del parsing
        step_file = db.session.query(Part).filter_by(id=int(model_id)).first()
        if step_file:
            step_file.entity_count = result.get('entity_count', 0)

            # Calcular categorías de entidades
            entities = result.get('entities', [])
            categories = {}
            for entity in entities:
                cat = entity.get('entity_category', 'OTHER')
                categories[cat] = categories.get(cat, 0) + 1

            # Guardar métricas
            step_file.complexity_score = self._calculate_complexity(result)

            db.session.commit()

        notification_service.notify_progress(
            model_id,
            stage='parsing',
            progress=33,
            message=f'Parsed {result.get("entity_count", 0)} entities'
        )

        logger.info(f"Parsing complete for model {model_id}: {result.get('entity_count', 0)} entities")

        return result

    def _stage_conversion(self, model_id: str, file_path: str, quality: str) -> tuple:
        """
        Etapa 2: Conversión a GLB

        Args:
            model_id: ID del modelo
            file_path: Ruta al archivo
            quality: Calidad de conversión

        Returns:
            Tupla (glb_path, thumbnail_path, metrics)
        """
        notification_service.notify_progress(
            model_id,
            stage='converting',
            progress=40,
            message='Converting STEP to GLB...'
        )

        # Configurar conversor
        config = ConversionConfig.from_quality_preset(quality)
        config.generate_thumbnail = True
        config.calculate_metrics = True

        converter = STEPToGLBConverter(config=config)

        # Convertir
        result = converter.convert(
            step_path=file_path,
            model_id=model_id,
            output_dir=self.output_dir
        )

        # Actualizar BD con métricas
        step_file = db.session.query(Part).filter_by(id=int(model_id)).first()
        if step_file and result.metrics:
            metrics = result.metrics

            # Extraer métricas importantes
            if 'bounding_box' in metrics:
                bbox = metrics['bounding_box']  # stored in step_file.bounding_box if needed

            if 'volume' in metrics:
                pass  # stored in part model if needed

            if 'surface_area' in metrics:
                pass  # stored in part model if needed

            db.session.commit()

        notification_service.notify_progress(
            model_id,
            stage='converting',
            progress=66,
            message='GLB conversion complete'
        )

        logger.info(f"Conversion complete for model {model_id}: {result.glb_path}")

        return result.glb_path, result.thumbnail_path, result.metrics

    def _stage_feature_extraction(self, model_id: str, file_path: str) -> dict:
        """
        Etapa 3: Extracción de características

        Args:
            model_id: ID del modelo
            file_path: Ruta al archivo

        Returns:
            Features extraídas
        """
        notification_service.notify_progress(
            model_id,
            stage='extracting',
            progress=75,
            message='Extracting features...'
        )

        # TODO: Implementar extracción de características
        # Por ahora, features básicas
        features = {
            'extracted_at': datetime.utcnow().isoformat(),
            'file_analyzed': os.path.basename(file_path)
        }

        notification_service.notify_progress(
            model_id,
            stage='extracting',
            progress=95,
            message='Feature extraction complete'
        )

        logger.info(f"Feature extraction complete for model {model_id}")

        return features

    def _calculate_complexity(self, parse_result: dict) -> float:
        """
        Calcular score de complejidad del modelo

        Args:
            parse_result: Resultado del parsing

        Returns:
            Score de complejidad (0-1)
        """
        entity_count = parse_result.get('entity_count', 0)

        # Score simple basado en número de entidades
        # TODO: Implementar cálculo más sofisticado
        if entity_count < 100:
            return 0.1
        elif entity_count < 500:
            return 0.3
        elif entity_count < 1000:
            return 0.5
        elif entity_count < 5000:
            return 0.7
        else:
            return 0.9

    def get_job_status(self, model_id: str) -> Optional[dict]:
        """
        Obtener estado de un trabajo

        Args:
            model_id: ID del modelo

        Returns:
            Dict con estado del trabajo o None
        """
        with self.lock:
            if model_id in self.active_jobs:
                job = self.active_jobs[model_id]
                return {
                    'job_id': job.job_id,
                    'model_id': job.model_id,
                    'status': job.status,
                    'quality': job.quality,
                    'created_at': job.created_at.isoformat(),
                    'started_at': job.started_at.isoformat() if job.started_at else None,
                    'error': job.error
                }
        return None

    def get_stats(self) -> dict:
        """
        Obtener estadísticas del servicio

        Returns:
            Dict con estadísticas
        """
        with self.lock:
            active_count = len([j for j in self.active_jobs.values() if j.status == 'PROCESSING'])
            queued_count = len([j for j in self.active_jobs.values() if j.status == 'QUEUED'])

            return {
                'running': self.running,
                'num_workers': self.num_workers,
                'queue_size': self.job_queue.qsize(),
                'active_jobs': active_count,
                'queued_jobs': queued_count,
                'total_jobs': len(self.active_jobs)
            }


# Instancia global del servicio
processing_service = ProcessingService(num_workers=2)

# Auto-iniciar el servicio
processing_service.start()
