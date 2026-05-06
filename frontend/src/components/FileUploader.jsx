/**
 * FileUploader Component
 * ======================
 *
 * Componente para carga de archivos STEP con drag & drop.
 *
 * Features:
 * - Drag & Drop zone
 * - Click to upload
 * - Validación de extensión y tamaño
 * - Progress bar para upload
 * - Preview de archivo
 * - Cancelación de upload
 * - Detección de duplicados
 *
 * @module components/FileUploader
 */

import React, { useState, useCallback, useRef } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  LinearProgress,
  Alert,
  Stack,
  Chip,
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  Divider,
  Tooltip,
} from '@mui/material';
import {
  CloudUpload,
  Close,
  CheckCircle,
  Error,
  Description,
  Cancel,
} from '@mui/icons-material';
import axios from 'axios';

/**
 * FileUploader Component
 */
export default function FileUploader({
  onUploadComplete,
  onUploadError,
  onUploadStart,
  maxSizeMB = 500,
  acceptedFormats = ['.step', '.stp', '.p21'],
  multiple = false,
  category = 'uploaded',
  sourceName = 'user_upload',
  disabled = false,
}) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState(null);
  const [uploadedFiles, setUploadedFiles] = useState([]);

  const fileInputRef = useRef(null);
  const cancelTokenRef = useRef(null);

  /**
   * Validar archivo
   */
  const validateFile = (file) => {
    // Validar extensión
    const fileName = file.name.toLowerCase();
    const hasValidExtension = acceptedFormats.some((ext) => fileName.endsWith(ext));

    if (!hasValidExtension) {
      return {
        valid: false,
        error: `Formato no válido. Solo se aceptan: ${acceptedFormats.join(', ')}`,
      };
    }

    // Validar tamaño
    const fileSizeMB = file.size / (1024 * 1024);
    if (fileSizeMB > maxSizeMB) {
      return {
        valid: false,
        error: `Archivo demasiado grande (${fileSizeMB.toFixed(2)}MB). Máximo: ${maxSizeMB}MB`,
      };
    }

    return { valid: true };
  };

  /**
   * Calcular hash del archivo (para detección de duplicados)
   */
  const calculateFileHash = async (file) => {
    const arrayBuffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', arrayBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    const hashHex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
    return hashHex;
  };

  /**
   * Manejar drag
   */
  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();

    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  /**
   * Manejar drop
   */
  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);

      if (disabled) return;

      const files = Array.from(e.dataTransfer.files);
      handleFiles(files);
    },
    [disabled]
  );

  /**
   * Manejar selección de archivos
   */
  const handleFileInputChange = (e) => {
    const files = Array.from(e.target.files);
    handleFiles(files);
  };

  /**
   * Procesar archivos seleccionados
   */
  const handleFiles = (files) => {
    if (files.length === 0) return;

    // Si no es multiple, tomar solo el primero
    const filesToProcess = multiple ? files : [files[0]];

    // Validar archivos
    const validatedFiles = filesToProcess.map((file) => {
      const validation = validateFile(file);
      return {
        file,
        ...validation,
      };
    });

    // Filtrar archivos válidos
    const validFiles = validatedFiles.filter((f) => f.valid);
    const invalidFiles = validatedFiles.filter((f) => !f.valid);

    // Mostrar errores de archivos inválidos
    if (invalidFiles.length > 0) {
      setError(invalidFiles.map((f) => f.error).join(', '));
    } else {
      setError(null);
    }

    // Agregar archivos válidos
    if (validFiles.length > 0) {
      setSelectedFiles((prev) => {
        if (multiple) {
          return [...prev, ...validFiles.map((f) => f.file)];
        } else {
          return [validFiles[0].file];
        }
      });
    }
  };

  /**
   * Eliminar archivo seleccionado
   */
  const removeFile = (index) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  /**
   * Abrir selector de archivos
   */
  const openFileDialog = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  /**
   * Upload de archivo
   */
  const uploadFile = async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('category', category);
    formData.append('source_name', sourceName);

    // Crear token de cancelación
    const CancelToken = axios.CancelToken;
    const source = CancelToken.source();
    cancelTokenRef.current = source;

    try {
      const response = await axios.post('/api/step-view/upload/', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total
          );
          setUploadProgress(percentCompleted);
        },
        cancelToken: source.token,
      });

      return response.data;
    } catch (error) {
      if (axios.isCancel(error)) {
        throw new Error('Upload cancelled');
      } else {
        throw error;
      }
    }
  };

  /**
   * Iniciar upload
   */
  const startUpload = async () => {
    if (selectedFiles.length === 0) {
      setError('No hay archivos seleccionados');
      return;
    }

    setUploading(true);
    setError(null);
    setUploadProgress(0);

    try {
      // Upload de archivos
      const results = [];

      for (const file of selectedFiles) {
        // Notificar inicio
        if (onUploadStart) {
          onUploadStart(file.name);
        }

        // Upload
        const result = await uploadFile(file);

        results.push({
          file: file.name,
          model_id: result.model_id,
          already_processed: result.already_processed,
          status: result.status,
        });

        // Notificar éxito individual
        if (onUploadComplete) {
          onUploadComplete(result);
        }
      }

      // Guardar resultados
      setUploadedFiles((prev) => [...prev, ...results]);

      // Limpiar archivos seleccionados
      setSelectedFiles([]);

      // Reset progress
      setUploadProgress(0);
    } catch (error) {
      console.error('Upload error:', error);

      let errorMessage = 'Error al subir archivo';
      if (error.response) {
        errorMessage = error.response.data?.error || error.response.data?.message || errorMessage;
      } else if (error.message) {
        errorMessage = error.message;
      }

      setError(errorMessage);

      if (onUploadError) {
        onUploadError(errorMessage);
      }
    } finally {
      setUploading(false);
      cancelTokenRef.current = null;
    }
  };

  /**
   * Cancelar upload
   */
  const cancelUpload = () => {
    if (cancelTokenRef.current) {
      cancelTokenRef.current.cancel('Upload cancelled by user');
    }
  };

  /**
   * Formatear tamaño de archivo
   */
  const formatFileSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <Box sx={{ width: '100%' }}>
      {/* Drop Zone */}
      <Paper
        sx={{
          p: 4,
          border: 2,
          borderStyle: 'dashed',
          borderColor: dragActive ? 'primary.main' : 'grey.300',
          backgroundColor: dragActive ? 'action.hover' : 'background.paper',
          cursor: disabled ? 'not-allowed' : 'pointer',
          transition: 'all 0.3s',
          opacity: disabled ? 0.5 : 1,
          '&:hover': {
            borderColor: disabled ? 'grey.300' : 'primary.main',
            backgroundColor: disabled ? 'background.paper' : 'action.hover',
          },
        }}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={disabled ? undefined : openFileDialog}
      >
        <Stack spacing={2} alignItems="center">
          <CloudUpload sx={{ fontSize: 64, color: 'primary.main' }} />

          <Typography variant="h6" align="center">
            {dragActive
              ? 'Suelta el archivo aquí'
              : 'Arrastra archivos STEP aquí o haz click para seleccionar'}
          </Typography>

          <Typography variant="body2" color="text.secondary" align="center">
            Formatos aceptados: {acceptedFormats.join(', ')}
            <br />
            Tamaño máximo: {maxSizeMB}MB
          </Typography>

          <Button variant="contained" startIcon={<CloudUpload />} disabled={disabled}>
            Seleccionar Archivo{multiple ? 's' : ''}
          </Button>
        </Stack>
      </Paper>

      {/* Input oculto */}
      <input
        ref={fileInputRef}
        type="file"
        accept={acceptedFormats.join(',')}
        multiple={multiple}
        onChange={handleFileInputChange}
        style={{ display: 'none' }}
      />

      {/* Archivos seleccionados */}
      {selectedFiles.length > 0 && (
        <Paper sx={{ mt: 2, p: 2 }}>
          <Typography variant="subtitle1" gutterBottom>
            Archivos Seleccionados ({selectedFiles.length})
          </Typography>

          <List>
            {selectedFiles.map((file, index) => (
              <React.Fragment key={index}>
                <ListItem>
                  <Description sx={{ mr: 2, color: 'primary.main' }} />
                  <ListItemText
                    primary={file.name}
                    secondary={formatFileSize(file.size)}
                  />
                  <ListItemSecondaryAction>
                    <IconButton
                      edge="end"
                      onClick={() => removeFile(index)}
                      disabled={uploading}
                    >
                      <Close />
                    </IconButton>
                  </ListItemSecondaryAction>
                </ListItem>
                {index < selectedFiles.length - 1 && <Divider />}
              </React.Fragment>
            ))}
          </List>

          {/* Botones de acción */}
          <Stack direction="row" spacing={2} sx={{ mt: 2 }} justifyContent="flex-end">
            <Button
              variant="outlined"
              onClick={() => setSelectedFiles([])}
              disabled={uploading}
            >
              Limpiar
            </Button>
            <Button
              variant="contained"
              startIcon={uploading ? <Cancel /> : <CloudUpload />}
              onClick={uploading ? cancelUpload : startUpload}
              disabled={selectedFiles.length === 0}
            >
              {uploading ? 'Cancelar' : 'Subir'}
            </Button>
          </Stack>
        </Paper>
      )}

      {/* Progress bar */}
      {uploading && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Subiendo... {uploadProgress}%
          </Typography>
          <LinearProgress variant="determinate" value={uploadProgress} />
        </Box>
      )}

      {/* Error */}
      {error && (
        <Alert severity="error" sx={{ mt: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Archivos subidos exitosamente */}
      {uploadedFiles.length > 0 && (
        <Paper sx={{ mt: 2, p: 2 }}>
          <Typography variant="subtitle1" gutterBottom>
            Archivos Subidos Exitosamente
          </Typography>

          <List>
            {uploadedFiles.map((item, index) => (
              <ListItem key={index}>
                <CheckCircle sx={{ mr: 2, color: 'success.main' }} />
                <ListItemText
                  primary={item.file}
                  secondary={
                    <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
                      <Chip label={item.status} size="small" color="primary" />
                      {item.already_processed && (
                        <Chip label="Ya procesado" size="small" color="success" />
                      )}
                    </Stack>
                  }
                />
              </ListItem>
            ))}
          </List>
        </Paper>
      )}
    </Box>
  );
}

/**
 * FileUploader Simple - Versión simplificada
 */
export function SimpleFileUploader({ onFileSelect, maxSizeMB = 500, acceptedFormats = ['.step', '.stp', '.p21'] }) {
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file && onFileSelect) {
      onFileSelect(file);
    }
  };

  return (
    <Box>
      <input
        ref={fileInputRef}
        type="file"
        accept={acceptedFormats.join(',')}
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />

      <Button
        variant="contained"
        startIcon={<CloudUpload />}
        onClick={() => fileInputRef.current?.click()}
        fullWidth
      >
        Seleccionar Archivo STEP
      </Button>

      <Typography variant="caption" display="block" sx={{ mt: 1 }} color="text.secondary">
        Formatos: {acceptedFormats.join(', ')} • Máx: {maxSizeMB}MB
      </Typography>
    </Box>
  );
}
