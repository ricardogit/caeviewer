/**
 * useUploadNotifications Hook
 * ============================
 *
 * Custom hook para manejar notificaciones SSE (Server-Sent Events)
 * durante el procesamiento de archivos STEP.
 *
 * Features:
 * - Conexión automática a SSE
 * - Manejo de eventos de progreso
 * - Reconexión automática en caso de error
 * - Cleanup al desmontar
 *
 * @module hooks/useUploadNotifications
 */

import { useEffect, useRef, useCallback, useState } from 'react';

/**
 * Tipos de eventos SSE
 */
export const SSE_EVENT_TYPES = {
  CONNECTED: 'connected',
  PROCESSING_STARTED: 'processing_started',
  PROCESSING: 'processing',
  PROCESSING_COMPLETE: 'processing_complete',
  PROCESSING_ERROR: 'processing_error',
  TIMEOUT: 'timeout',
  ERROR: 'error',
};

/**
 * Hook para manejar notificaciones SSE
 *
 * @param {string} modelId - ID del modelo a monitorear
 * @param {Object} callbacks - Callbacks para eventos
 * @param {Function} callbacks.onProgress - Callback para progreso (progress, stage, message)
 * @param {Function} callbacks.onComplete - Callback para completado (data)
 * @param {Function} callbacks.onError - Callback para error (error, stage)
 * @param {Function} callbacks.onConnected - Callback para conexión establecida
 * @param {Object} options - Opciones de configuración
 * @param {boolean} options.autoConnect - Conectar automáticamente (default: true)
 * @param {number} options.maxRetries - Máximo de reintentos (default: 3)
 * @param {number} options.retryDelay - Delay entre reintentos en ms (default: 2000)
 *
 * @returns {Object} - { connected, error, retry, disconnect }
 */
export function useUploadNotifications(
  modelId,
  {
    onProgress,
    onComplete,
    onError,
    onConnected,
  } = {},
  {
    autoConnect = true,
    maxRetries = 3,
    retryDelay = 2000,
  } = {}
) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);

  const eventSourceRef = useRef(null);
  const retriesRef = useRef(0);
  const retryTimeoutRef = useRef(null);

  /**
   * Conectar a SSE
   */
  const connect = useCallback(() => {
    if (!modelId) {
      console.warn('useUploadNotifications: No modelId provided');
      return;
    }

    // Limpiar conexión existente
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const url = `/api/viewer/status/${modelId}`;
    console.log(`SSE: Connecting to ${url}`);

    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    // Evento: Conectado
    eventSource.addEventListener('connected', (e) => {
      console.log('SSE: Connected', e.data);
      setConnected(true);
      setError(null);
      retriesRef.current = 0;

      try {
        const data = JSON.parse(e.data);
        if (onConnected) {
          onConnected(data);
        }
      } catch (err) {
        console.error('SSE: Error parsing connected event', err);
      }
    });

    // Evento: Procesamiento iniciado
    eventSource.addEventListener('processing_started', (e) => {
      console.log('SSE: Processing started', e.data);

      try {
        const data = JSON.parse(e.data);
        if (onProgress) {
          onProgress(data.progress || 0, data.stage || 'starting', data.message || 'Processing started');
        }
      } catch (err) {
        console.error('SSE: Error parsing processing_started event', err);
      }
    });

    // Evento: Progreso
    eventSource.addEventListener('processing', (e) => {
      console.log('SSE: Processing progress', e.data);

      try {
        const data = JSON.parse(e.data);
        if (onProgress) {
          onProgress(data.progress || 0, data.stage || 'processing', data.message || '');
        }
      } catch (err) {
        console.error('SSE: Error parsing processing event', err);
      }
    });

    // Evento: Completado
    eventSource.addEventListener('processing_complete', (e) => {
      console.log('SSE: Processing complete', e.data);

      try {
        const data = JSON.parse(e.data);
        if (onComplete) {
          onComplete(data);
        }
      } catch (err) {
        console.error('SSE: Error parsing processing_complete event', err);
      }

      // Cerrar conexión
      eventSource.close();
      setConnected(false);
    });

    // Evento: Error
    eventSource.addEventListener('processing_error', (e) => {
      console.log('SSE: Processing error', e.data);

      try {
        const data = JSON.parse(e.data);
        const errorMessage = data.error || 'Unknown error';
        const errorStage = data.stage || 'unknown';

        setError(errorMessage);

        if (onError) {
          onError(errorMessage, errorStage, data.can_retry);
        }
      } catch (err) {
        console.error('SSE: Error parsing processing_error event', err);
        setError('Error parsing error event');
      }

      // Cerrar conexión
      eventSource.close();
      setConnected(false);
    });

    // Evento: Timeout
    eventSource.addEventListener('timeout', (e) => {
      console.log('SSE: Timeout', e.data);
      setError('Connection timeout');
      eventSource.close();
      setConnected(false);
    });

    // Error de conexión
    eventSource.onerror = (err) => {
      console.error('SSE: Connection error', err);

      // Intentar reconectar
      if (retriesRef.current < maxRetries) {
        retriesRef.current += 1;
        const delay = retryDelay * retriesRef.current;

        console.log(`SSE: Reconnecting in ${delay}ms (attempt ${retriesRef.current}/${maxRetries})`);

        retryTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      } else {
        console.error('SSE: Max retries reached');
        setError('Connection failed after multiple retries');
        setConnected(false);
      }

      eventSource.close();
    };

  }, [modelId, onProgress, onComplete, onError, onConnected, maxRetries, retryDelay]);

  /**
   * Desconectar SSE
   */
  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      console.log('SSE: Disconnecting');
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }

    setConnected(false);
  }, []);

  /**
   * Reintentar conexión manualmente
   */
  const retry = useCallback(() => {
    retriesRef.current = 0;
    setError(null);
    connect();
  }, [connect]);

  /**
   * Effect: Auto-conectar
   */
  useEffect(() => {
    if (autoConnect && modelId) {
      connect();
    }

    // Cleanup al desmontar
    return () => {
      disconnect();
    };
  }, [modelId, autoConnect, connect, disconnect]);

  return {
    connected,
    error,
    retry,
    disconnect,
  };
}

/**
 * Hook simplificado para una sola notificación
 *
 * @param {string} modelId - ID del modelo
 *
 * @returns {Object} - { progress, stage, message, completed, error }
 */
export function useProcessingStatus(modelId) {
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
  const [message, setMessage] = useState('');
  const [completed, setCompleted] = useState(false);
  const [error, setError] = useState(null);
  const [completionData, setCompletionData] = useState(null);

  const handleProgress = useCallback((prog, stg, msg) => {
    setProgress(prog);
    setStage(stg);
    setMessage(msg);
  }, []);

  const handleComplete = useCallback((data) => {
    setProgress(100);
    setCompleted(true);
    setCompletionData(data);
  }, []);

  const handleError = useCallback((err) => {
    setError(err);
  }, []);

  const { connected, retry } = useUploadNotifications(
    modelId,
    {
      onProgress: handleProgress,
      onComplete: handleComplete,
      onError: handleError,
    }
  );

  return {
    progress,
    stage,
    message,
    completed,
    error,
    completionData,
    connected,
    retry,
  };
}

/**
 * Hook para monitorear múltiples modelos
 *
 * @param {Array<string>} modelIds - Array de IDs de modelos
 * @param {Function} onModelComplete - Callback cuando un modelo se completa
 * @param {Function} onModelError - Callback cuando un modelo falla
 *
 * @returns {Object} - { statuses, allCompleted, anyError }
 */
export function useMultipleProcessingStatus(modelIds, onModelComplete, onModelError) {
  const [statuses, setStatuses] = useState({});

  useEffect(() => {
    // Inicializar statuses
    const initialStatuses = {};
    modelIds.forEach((id) => {
      initialStatuses[id] = {
        progress: 0,
        stage: '',
        completed: false,
        error: null,
      };
    });
    setStatuses(initialStatuses);
  }, [modelIds]);

  // Crear hooks para cada modelo
  modelIds.forEach((modelId) => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useUploadNotifications(
      modelId,
      {
        onProgress: (progress, stage) => {
          setStatuses((prev) => ({
            ...prev,
            [modelId]: {
              ...prev[modelId],
              progress,
              stage,
            },
          }));
        },
        onComplete: (data) => {
          setStatuses((prev) => ({
            ...prev,
            [modelId]: {
              ...prev[modelId],
              progress: 100,
              completed: true,
            },
          }));

          if (onModelComplete) {
            onModelComplete(modelId, data);
          }
        },
        onError: (error) => {
          setStatuses((prev) => ({
            ...prev,
            [modelId]: {
              ...prev[modelId],
              error,
            },
          }));

          if (onModelError) {
            onModelError(modelId, error);
          }
        },
      }
    );
  });

  const allCompleted = Object.values(statuses).every((s) => s.completed);
  const anyError = Object.values(statuses).some((s) => s.error);

  return {
    statuses,
    allCompleted,
    anyError,
  };
}

export default useUploadNotifications;
