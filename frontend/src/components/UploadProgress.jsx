/**
 * UploadProgress Component
 * =========================
 *
 * Componente para mostrar progreso detallado del procesamiento de archivos STEP.
 *
 * Features:
 * - Progress bar con etapas
 * - Indicador visual de etapa actual
 * - Mensajes de estado
 * - Tiempo estimado
 * - Manejo de errores
 * - Acción de reintentar
 *
 * @module components/UploadProgress
 */

import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  LinearProgress,
  Stepper,
  Step,
  StepLabel,
  Alert,
  Button,
  Stack,
  Chip,
  CircularProgress,
  Divider,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import {
  CheckCircle,
  Error,
  HourglassEmpty,
  Refresh,
  Visibility,
  Description,
  Transform,
  Analytics,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { useProcessingStatus } from '../hooks/useUploadNotifications';

/**
 * Configuración de etapas del procesamiento
 */
const PROCESSING_STAGES = [
  {
    key: 'parsing',
    label: 'Parsing',
    description: 'Analizando estructura del archivo STEP',
    icon: <Description />,
    progressRange: [0, 33],
  },
  {
    key: 'converting',
    label: 'Conversión',
    description: 'Convirtiendo STEP a GLB',
    icon: <Transform />,
    progressRange: [33, 66],
  },
  {
    key: 'extracting',
    label: 'Extracción',
    description: 'Extrayendo características',
    icon: <Analytics />,
    progressRange: [66, 100],
  },
];

/**
 * UploadProgress Component
 */
export default function UploadProgress({
  modelId,
  filename,
  onComplete,
  onError,
  showViewer = true,
  onRetry,
}) {
  const navigate = useNavigate();

  const {
    progress,
    stage,
    message,
    completed,
    error,
    completionData,
    connected,
    retry,
  } = useProcessingStatus(modelId);

  const [startTime] = useState(Date.now());
  const [elapsedTime, setElapsedTime] = useState(0);

  /**
   * Actualizar tiempo transcurrido
   */
  useEffect(() => {
    if (!completed && !error) {
      const interval = setInterval(() => {
        setElapsedTime(Math.floor((Date.now() - startTime) / 1000));
      }, 1000);

      return () => clearInterval(interval);
    }
  }, [completed, error, startTime]);

  /**
   * Notificar completado
   */
  useEffect(() => {
    if (completed && onComplete) {
      onComplete(completionData);
    }
  }, [completed, completionData, onComplete]);

  /**
   * Notificar error
   */
  useEffect(() => {
    if (error && onError) {
      onError(error);
    }
  }, [error, onError]);

  /**
   * Obtener etapa activa actual
   */
  const getActiveStep = () => {
    return PROCESSING_STAGES.findIndex((s) => s.key === stage);
  };

  /**
   * Ver modelo en el visualizador
   */
  const handleViewModel = () => {
    if (completionData?.glb_url) {
      navigate(`/viewer/${modelId}`);
    }
  };

  /**
   * Manejar reintentar
   */
  const handleRetry = () => {
    if (onRetry) {
      onRetry(modelId);
    } else {
      retry();
    }
  };

  /**
   * Formatear tiempo
   */
  const formatTime = (seconds) => {
    if (seconds < 60) {
      return `${seconds}s`;
    }
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  return (
    <Paper sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ mb: 3 }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            {completed ? 'Procesamiento Completado' : 'Procesando Archivo'}
          </Typography>

          {!completed && !error && (
            <Chip
              icon={<HourglassEmpty />}
              label={formatTime(elapsedTime)}
              size="small"
              color="primary"
            />
          )}

          {connected && !completed && !error && (
            <Chip label="Conectado" size="small" color="success" />
          )}
        </Stack>

        <Typography variant="body2" color="text.secondary">
          {filename || `Modelo ${modelId}`}
        </Typography>
      </Box>

      <Divider sx={{ mb: 3 }} />

      {/* Estado: Procesando */}
      {!completed && !error && (
        <>
          {/* Progress bar principal */}
          <Box sx={{ mb: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <CircularProgress size={20} sx={{ mr: 1 }} />
              <Typography variant="body2" color="text.secondary">
                {message || 'Procesando...'}
              </Typography>
              <Box sx={{ ml: 'auto' }}>
                <Typography variant="body2" fontWeight="bold">
                  {progress}%
                </Typography>
              </Box>
            </Box>

            <LinearProgress
              variant="determinate"
              value={progress}
              sx={{
                height: 8,
                borderRadius: 4,
              }}
            />
          </Box>

          {/* Stepper de etapas */}
          <Stepper activeStep={getActiveStep()} sx={{ mb: 3 }}>
            {PROCESSING_STAGES.map((stageInfo, index) => (
              <Step key={stageInfo.key}>
                <StepLabel
                  optional={
                    <Typography variant="caption">
                      {stageInfo.description}
                    </Typography>
                  }
                  icon={stageInfo.icon}
                >
                  {stageInfo.label}
                </StepLabel>
              </Step>
            ))}
          </Stepper>

          {/* Detalles de etapa actual */}
          <Paper variant="outlined" sx={{ p: 2, backgroundColor: 'action.hover' }}>
            <Stack direction="row" spacing={2} alignItems="center">
              <Box sx={{ color: 'primary.main' }}>
                {PROCESSING_STAGES[getActiveStep()]?.icon || <HourglassEmpty />}
              </Box>
              <Box sx={{ flexGrow: 1 }}>
                <Typography variant="subtitle2">
                  {PROCESSING_STAGES[getActiveStep()]?.label || 'Procesando...'}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {message || PROCESSING_STAGES[getActiveStep()]?.description}
                </Typography>
              </Box>
            </Stack>
          </Paper>
        </>
      )}

      {/* Estado: Completado */}
      {completed && (
        <>
          <Alert severity="success" sx={{ mb: 3 }} icon={<CheckCircle />}>
            <Typography variant="subtitle2" gutterBottom>
              ¡Archivo procesado exitosamente!
            </Typography>
            <Typography variant="body2">
              El modelo está listo para visualizar.
            </Typography>
          </Alert>

          {/* Métricas del modelo */}
          {completionData?.metrics && (
            <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
              <Typography variant="subtitle2" gutterBottom>
                Información del Modelo
              </Typography>

              <List dense>
                {completionData.metrics.entity_count && (
                  <ListItem>
                    <ListItemText
                      primary="Entidades"
                      secondary={completionData.metrics.entity_count.toLocaleString()}
                    />
                  </ListItem>
                )}

                {completionData.metrics.file_size_mb && (
                  <ListItem>
                    <ListItemText
                      primary="Tamaño"
                      secondary={`${completionData.metrics.file_size_mb.toFixed(2)} MB`}
                    />
                  </ListItem>
                )}

                {completionData.metrics.processing_time_seconds && (
                  <ListItem>
                    <ListItemText
                      primary="Tiempo de procesamiento"
                      secondary={formatTime(completionData.metrics.processing_time_seconds)}
                    />
                  </ListItem>
                )}
              </List>
            </Paper>
          )}

          {/* Acciones */}
          {showViewer && (
            <Button
              variant="contained"
              fullWidth
              size="large"
              startIcon={<Visibility />}
              onClick={handleViewModel}
            >
              Ver Modelo 3D
            </Button>
          )}
        </>
      )}

      {/* Estado: Error */}
      {error && (
        <>
          <Alert severity="error" sx={{ mb: 3 }} icon={<Error />}>
            <Typography variant="subtitle2" gutterBottom>
              Error en el procesamiento
            </Typography>
            <Typography variant="body2">
              {error}
            </Typography>
          </Alert>

          {/* Acciones de error */}
          <Stack direction="row" spacing={2}>
            <Button
              variant="outlined"
              startIcon={<Refresh />}
              onClick={handleRetry}
              fullWidth
            >
              Reintentar
            </Button>
          </Stack>
        </>
      )}
    </Paper>
  );
}

/**
 * Componente compacto de progreso
 */
export function CompactUploadProgress({ modelId, filename }) {
  const { progress, stage, completed, error } = useProcessingStatus(modelId);

  return (
    <Paper sx={{ p: 2 }}>
      <Stack spacing={1}>
        <Stack direction="row" spacing={1} alignItems="center">
          {!completed && !error && <CircularProgress size={16} />}
          {completed && <CheckCircle color="success" fontSize="small" />}
          {error && <Error color="error" fontSize="small" />}

          <Typography variant="body2" sx={{ flexGrow: 1 }}>
            {filename || `Modelo ${modelId}`}
          </Typography>

          <Typography variant="caption" color="text.secondary">
            {completed ? 'Listo' : error ? 'Error' : `${progress}%`}
          </Typography>
        </Stack>

        {!completed && !error && (
          <LinearProgress variant="determinate" value={progress} size="small" />
        )}
      </Stack>
    </Paper>
  );
}

/**
 * Componente para múltiples uploads en progreso
 */
export function MultipleUploadProgress({ modelIds, onAllComplete }) {
  const [completedCount, setCompletedCount] = useState(0);

  const handleComplete = () => {
    setCompletedCount((prev) => {
      const newCount = prev + 1;
      if (newCount === modelIds.length && onAllComplete) {
        onAllComplete();
      }
      return newCount;
    });
  };

  return (
    <Stack spacing={2}>
      <Typography variant="h6">
        Procesando {modelIds.length} archivo{modelIds.length !== 1 ? 's' : ''}
      </Typography>

      <Typography variant="body2" color="text.secondary">
        Completados: {completedCount} / {modelIds.length}
      </Typography>

      <LinearProgress
        variant="determinate"
        value={(completedCount / modelIds.length) * 100}
      />

      {modelIds.map((modelId) => (
        <CompactUploadProgress key={modelId} modelId={modelId} />
      ))}
    </Stack>
  );
}
