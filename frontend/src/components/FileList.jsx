import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Typography,
  CircularProgress,
  Chip,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  LinearProgress,
  Alert,
  IconButton,
  Tooltip,
} from '@mui/material';
import { UploadFile, Refresh, InsertDriveFile, DeleteOutline } from '@mui/icons-material';
import axios from 'axios';

const MATERIALS = [
  { value: 'aluminum_6061', label: 'Aluminio 6061' },
  { value: 'steel_1018', label: 'Acero 1018' },
  { value: 'stainless_steel_304', label: 'Acero Inox 304' },
  { value: 'titanium_ti6al4v', label: 'Titanio Ti-6Al-4V' },
  { value: 'brass', label: 'Latón' },
  { value: 'copper', label: 'Cobre' },
  { value: 'cast_iron', label: 'Hierro fundido' },
  { value: 'plastic_abs', label: 'Plástico ABS' },
];

export default function FileList({ onSelectFile, selectedFileId }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState(null);
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const [selectedFile, setSelectedFile] = useState(null);
  const [partName, setPartName] = useState('');
  const [material, setMaterial] = useState('aluminum_6061');

  const fileInputRef = useRef();
  const [deleteConfirmId, setDeleteConfirmId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    loadFiles();
  }, []);

  async function handleDeleteConfirm(fileId) {
    setDeletingId(fileId);
    try {
      await axios.delete(`/api/step-view/files/${fileId}`);
      setDeleteConfirmId(null);
      await loadFiles();
    } catch (err) {
      console.error('Error deleting file:', err);
    } finally {
      setDeletingId(null);
    }
  }

  async function loadFiles() {
    setLoading(true);
    try {
      const response = await axios.get('/api/step-view/files');
      setFiles(response.data.files || []);
    } catch (error) {
      console.error('Error loading files:', error);
    } finally {
      setLoading(false);
    }
  }

  function openUploadDialog() {
    setSelectedFile(null);
    setPartName('');
    setMaterial('aluminum_6061');
    setUploadError(null);
    setUploadSuccess(null);
    setUploadProgress(0);
    setUploadOpen(true);
  }

  function handleFileSelected(file) {
    if (!file) return;
    setSelectedFile(file);
    setPartName(file.name.replace(/\.(step|stp|p21)$/i, ''));
    setUploadError(null);
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelected(file);
  }

  async function handleUpload() {
    if (!selectedFile) return;
    setUploadError(null);
    setUploadSuccess(null);

    const fileMB = selectedFile.size / 1024 / 1024;
    if (fileMB > 500) {
      setUploadError(`El archivo es demasiado grande (${fileMB.toFixed(0)} MB). El límite máximo es 500 MB.`);
      return;
    }

    setUploading(true);

    const formData = new FormData();
    formData.append('file', selectedFile);
    if (partName) formData.append('name', partName);
    formData.append('material', material);

    try {
      await axios.post('/api/step-view/upload/', formData, {
        // Do NOT set Content-Type manually — the browser sets multipart/form-data + boundary automatically
        onUploadProgress: (e) => {
          if (e.total) setUploadProgress(Math.round((e.loaded * 100) / e.total));
        },
        timeout: 600000, // 10 minutes for large files
      });
      setUploadSuccess(`"${selectedFile.name}" cargado correctamente.`);
      await loadFiles();
    } catch (err) {
      const data = err.response?.data;
      const msg = (typeof data === 'object' ? data?.error || data?.message : data) || err.message;
      setUploadError(msg);
    } finally {
      setUploading(false);
    }
  }

  if (loading) {
    return (
      <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="h6">Archivos STEP</Typography>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <Tooltip title="Actualizar lista">
              <IconButton size="small" onClick={loadFiles}><Refresh fontSize="small" /></IconButton>
            </Tooltip>
          </Box>
        </Box>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {files.length} archivo{files.length !== 1 ? 's' : ''} disponible{files.length !== 1 ? 's' : ''}
        </Typography>
        <Button
          variant="contained"
          fullWidth
          size="small"
          startIcon={<UploadFile />}
          onClick={openUploadDialog}
        >
          Cargar archivo STEP
        </Button>
      </Box>

      {/* File list */}
      <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
        <List dense>
          {files.map((file) => (
            <ListItem
              key={file.id}
              disablePadding
              secondaryAction={
                <Tooltip title="Eliminar archivo">
                  <IconButton
                    edge="end"
                    size="small"
                    onClick={(e) => { e.stopPropagation(); setDeleteConfirmId(file.id); }}
                    sx={{ opacity: 0.4, '&:hover': { opacity: 1, color: 'error.main' } }}
                  >
                    <DeleteOutline fontSize="small" />
                  </IconButton>
                </Tooltip>
              }
            >
              <ListItemButton
                selected={file.id === selectedFileId}
                onClick={() => onSelectFile(file)}
                sx={{ pr: 5 }}
              >
                <InsertDriveFile sx={{ mr: 1, fontSize: 18, color: 'text.secondary', flexShrink: 0 }} />
                <ListItemText
                  primary={file.original_filename || file.filename}
                  primaryTypographyProps={{ noWrap: true, fontSize: '0.85rem' }}
                  secondary={
                    <Box component="span" sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                      {file.entity_count > 0 && (
                        <Chip label={`${file.entity_count?.toLocaleString()} ent.`} size="small" sx={{ height: 18, fontSize: '0.65rem' }} />
                      )}
                      {file.file_size_mb > 0 && (
                        <Chip label={`${file.file_size_mb?.toFixed(1)} MB`} size="small" sx={{ height: 18, fontSize: '0.65rem' }} />
                      )}
                      {file.source && (
                        <Chip label={file.source} size="small" color="primary" sx={{ height: 18, fontSize: '0.65rem' }} />
                      )}
                    </Box>
                  }
                />
              </ListItemButton>
            </ListItem>
          ))}
          {files.length === 0 && (
            <ListItem>
              <Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>
                No hay archivos. Carga un archivo STEP para comenzar.
              </Typography>
            </ListItem>
          )}
        </List>
      </Box>

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteConfirmId} onClose={() => !deletingId && setDeleteConfirmId(null)} maxWidth="xs" fullWidth>
        <DialogTitle>¿Eliminar archivo?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            <strong>{files.find(f => f.id === deleteConfirmId)?.original_filename || 'Este archivo'}</strong> será eliminado permanentemente del servidor, incluyendo su caché 3D.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmId(null)} disabled={!!deletingId}>Cancelar</Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => handleDeleteConfirm(deleteConfirmId)}
            disabled={!!deletingId}
            startIcon={deletingId ? <CircularProgress size={14} /> : null}
          >
            {deletingId ? 'Eliminando…' : 'Eliminar'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Upload Dialog */}
      <Dialog open={uploadOpen} onClose={() => !uploading && setUploadOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Cargar archivo STEP</DialogTitle>
        <DialogContent>
          {/* Drop zone */}
          <Box
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            sx={{
              border: 2,
              borderStyle: 'dashed',
              borderColor: dragOver ? 'primary.main' : selectedFile ? 'success.main' : 'divider',
              borderRadius: 2,
              p: 3,
              mb: 2,
              textAlign: 'center',
              cursor: 'pointer',
              bgcolor: dragOver ? 'action.hover' : 'transparent',
              transition: 'all 0.2s',
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".step,.stp,.p21"
              style={{ display: 'none' }}
              onChange={(e) => handleFileSelected(e.target.files[0])}
            />
            <UploadFile sx={{ fontSize: 40, color: selectedFile ? 'success.main' : 'text.secondary', mb: 1 }} />
            {selectedFile ? (
              <Typography variant="body2" color="success.main" fontWeight="medium">
                {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
              </Typography>
            ) : (
              <>
                <Typography variant="body2">Arrastra un archivo aquí o haz clic para seleccionar</Typography>
                <Typography variant="caption" color="text.secondary">.step · .stp · .p21</Typography>
              </>
            )}
          </Box>

          {/* Part name */}
          <TextField
            label="Nombre de la pieza"
            value={partName}
            onChange={(e) => setPartName(e.target.value)}
            fullWidth
            size="small"
            sx={{ mb: 2 }}
            placeholder="Nombre de la pieza (opcional)"
          />

          {/* Material */}
          <FormControl fullWidth size="small" sx={{ mb: 2 }}>
            <InputLabel>Material</InputLabel>
            <Select value={material} onChange={(e) => setMaterial(e.target.value)} label="Material">
              {MATERIALS.map((m) => (
                <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
              ))}
            </Select>
          </FormControl>

          {uploading && (
            <Box sx={{ mb: 1 }}>
              <LinearProgress variant="determinate" value={uploadProgress} />
              <Typography variant="caption" color="text.secondary">{uploadProgress}%</Typography>
            </Box>
          )}

          {uploadError && <Alert severity="error" sx={{ mb: 1 }}>{uploadError}</Alert>}
          {uploadSuccess && <Alert severity="success" sx={{ mb: 1 }}>{uploadSuccess}</Alert>}
        </DialogContent>

        <DialogActions>
          <Button onClick={() => setUploadOpen(false)} disabled={uploading}>Cancelar</Button>
          {uploadSuccess ? (
            <Button variant="contained" onClick={() => setUploadOpen(false)}>Cerrar</Button>
          ) : (
            <Button
              variant="contained"
              onClick={handleUpload}
              disabled={!selectedFile || uploading}
              startIcon={uploading ? <CircularProgress size={16} /> : <UploadFile />}
            >
              {uploading ? 'Cargando...' : 'Cargar'}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
