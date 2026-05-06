"""
Notification Service - Sistema de notificaciones SSE
====================================================

Servicio para manejar notificaciones en tiempo real usando Server-Sent Events (SSE).
"""

import logging
import uuid
import queue
import threading
from typing import Dict, Optional, List
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Servicio de notificaciones SSE para comunicación en tiempo real
    con clientes durante el procesamiento de modelos
    """

    def __init__(self):
        """Inicializar servicio de notificaciones"""
        # Dict de colas de eventos por model_id
        # {model_id: {client_id: queue.Queue}}
        self.client_queues: Dict[str, Dict[str, queue.Queue]] = defaultdict(dict)

        # Lock para thread safety
        self.lock = threading.Lock()

        logger.info("NotificationService initialized")

    def register_client(self, model_id: str) -> str:
        """
        Registrar un nuevo cliente para recibir notificaciones

        Args:
            model_id: ID del modelo a monitorear

        Returns:
            client_id único para este cliente
        """
        client_id = str(uuid.uuid4())

        with self.lock:
            # Crear cola para este cliente
            self.client_queues[model_id][client_id] = queue.Queue(maxsize=100)

        logger.info(f"Client registered: {client_id} for model {model_id}")

        return client_id

    def unregister_client(self, model_id: str, client_id: str) -> None:
        """
        Desregistrar un cliente

        Args:
            model_id: ID del modelo
            client_id: ID del cliente
        """
        with self.lock:
            if model_id in self.client_queues:
                if client_id in self.client_queues[model_id]:
                    del self.client_queues[model_id][client_id]
                    logger.info(f"Client unregistered: {client_id} for model {model_id}")

                # Limpiar si no quedan clientes
                if not self.client_queues[model_id]:
                    del self.client_queues[model_id]
                    logger.debug(f"No more clients for model {model_id}, cleaned up")

    def notify(self, model_id: str, event_type: str, data: dict) -> int:
        """
        Enviar notificación a todos los clientes suscritos a un modelo

        Args:
            model_id: ID del modelo
            event_type: Tipo de evento (processing_started, processing, processing_complete, etc.)
            data: Datos del evento

        Returns:
            Número de clientes notificados
        """
        event = {
            'type': event_type,
            'data': {
                **data,
                'model_id': model_id,
                'timestamp': datetime.utcnow().isoformat()
            }
        }

        notified_count = 0

        with self.lock:
            if model_id in self.client_queues:
                # Enviar evento a todos los clientes suscritos
                for client_id, client_queue in self.client_queues[model_id].items():
                    try:
                        # Intentar poner en cola sin bloquear
                        client_queue.put_nowait(event)
                        notified_count += 1
                    except queue.Full:
                        logger.warning(
                            f"Queue full for client {client_id}, model {model_id}. Dropping event."
                        )

        if notified_count > 0:
            logger.debug(
                f"Notified {notified_count} clients for model {model_id}: {event_type}"
            )

        return notified_count

    def get_next_event(self, model_id: str, client_id: str, timeout: int = 30) -> Optional[dict]:
        """
        Obtener siguiente evento para un cliente (blocking)

        Args:
            model_id: ID del modelo
            client_id: ID del cliente
            timeout: Timeout en segundos

        Returns:
            Evento o None si timeout
        """
        with self.lock:
            if model_id not in self.client_queues:
                logger.warning(f"Model {model_id} not in queues")
                return None

            if client_id not in self.client_queues[model_id]:
                logger.warning(f"Client {client_id} not registered for model {model_id}")
                return None

            client_queue = self.client_queues[model_id][client_id]

        # Obtener evento de la cola (blocking con timeout)
        try:
            event = client_queue.get(timeout=timeout)
            return event
        except queue.Empty:
            # Timeout, no hay eventos
            return None

    def notify_processing_started(self, model_id: str) -> None:
        """
        Notificar inicio de procesamiento

        Args:
            model_id: ID del modelo
        """
        self.notify(model_id, 'processing_started', {
            'progress': 0,
            'stage': 'starting',
            'message': 'Processing started'
        })

    def notify_progress(self, model_id: str, stage: str, progress: int, message: str = '') -> None:
        """
        Notificar progreso de procesamiento

        Args:
            model_id: ID del modelo
            stage: Etapa actual (parsing, converting, extracting)
            progress: Progreso (0-100)
            message: Mensaje opcional
        """
        self.notify(model_id, 'processing', {
            'progress': progress,
            'stage': stage,
            'message': message
        })

    def notify_processing_complete(self, model_id: str, glb_url: str, thumbnail_url: str,
                                    metrics: Optional[dict] = None) -> None:
        """
        Notificar finalización exitosa de procesamiento

        Args:
            model_id: ID del modelo
            glb_url: URL del archivo GLB
            thumbnail_url: URL del thumbnail
            metrics: Métricas opcionales del modelo
        """
        data = {
            'progress': 100,
            'glb_url': glb_url,
            'thumbnail_url': thumbnail_url
        }

        if metrics:
            data['metrics'] = metrics

        self.notify(model_id, 'processing_complete', data)

    def notify_processing_error(self, model_id: str, error: str, stage: str,
                                can_retry: bool = True) -> None:
        """
        Notificar error en procesamiento

        Args:
            model_id: ID del modelo
            error: Mensaje de error
            stage: Etapa donde ocurrió el error
            can_retry: Si se puede reintentar
        """
        self.notify(model_id, 'processing_error', {
            'error': error,
            'stage': stage,
            'can_retry': can_retry
        })

    def get_active_clients(self) -> Dict[str, int]:
        """
        Obtener número de clientes activos por modelo

        Returns:
            Dict {model_id: client_count}
        """
        with self.lock:
            return {
                model_id: len(clients)
                for model_id, clients in self.client_queues.items()
            }

    def cleanup_model(self, model_id: str) -> None:
        """
        Limpiar todas las colas de un modelo

        Args:
            model_id: ID del modelo
        """
        with self.lock:
            if model_id in self.client_queues:
                # Enviar evento de cierre a todos los clientes
                for client_id in list(self.client_queues[model_id].keys()):
                    try:
                        self.client_queues[model_id][client_id].put_nowait({
                            'type': 'cleanup',
                            'data': {'message': 'Model processing cleanup'}
                        })
                    except:
                        pass

                del self.client_queues[model_id]
                logger.info(f"Cleaned up notifications for model {model_id}")

    def get_stats(self) -> dict:
        """
        Obtener estadísticas del servicio

        Returns:
            Dict con estadísticas
        """
        with self.lock:
            total_clients = sum(len(clients) for clients in self.client_queues.values())

            return {
                'active_models': len(self.client_queues),
                'total_clients': total_clients,
                'models': {
                    model_id: len(clients)
                    for model_id, clients in self.client_queues.items()
                }
            }


# Instancia global del servicio
notification_service = NotificationService()
