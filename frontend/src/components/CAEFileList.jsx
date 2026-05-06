import React, { useState, useEffect, useRef } from 'react';
import {
  Box, List, ListItem, ListItemButton, ListItemText,
  Typography, CircularProgress, Chip, Button,
  IconButton, Tooltip, Dialog, DialogTitle,
  DialogContent, DialogActions, LinearProgress, Alert,
} from '@mui/material';
import { UploadFile, Refresh, GridOn, DeleteOutline } from '@mui/icons-material';
import axios from 'axios';

const SUPPORTED = '.vtu, .vtk, .inp, .bdf, .msh, .med, .exo, .cdb';

export default function CAEFileList({ onSelectMesh, selectedMeshId }) {
  const [meshes, setMeshes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState(null);
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const fileInputRef = useRef();

  useEffect(() => { loadMeshes(); }, []);

  async function loadMeshes() {
    setLoading(true);
    try {
      const res = await axios.get('/api/cae/meshes');
      setMeshes(res.data.meshes || []);
    } catch (e) {
      console.error('Error loading meshes:', e);
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload() {
    if (!selectedFile) return;
    setUploadError(null);
    setUploadSuccess(null);
    setUploading(true);
    const form = new FormData();
    form.append('file', selectedFile);
    try {
      await axios.post('/api/cae/meshes/upload', form, {
        onUploadProgress: (e) => { if (e.total) setUploadProgress(Math.round(e.loaded * 100 / e.total)); },
        timeout: 600000,
      });
      setUploadSuccess(`"${selectedFile.name}" cargado correctamente.`);
      await loadMeshes();
    } catch (err) {
      const data = err.response?.data;
      setUploadError((typeof data === 'object' ? data?.error : data) || err.message);
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(meshId) {
    setDeletingId(meshId);
    try {
      await axios.delete(`/api/cae/meshes/${meshId}`);
      setDeleteConfirmId(null);
      await loadMeshes();
    } catch (e) { console.error(e); }
    finally { setDeletingId(null); }
  }

  if (loading) return <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}><CircularProgress /></Box>;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="h6">Mallas CAE</Typography>
          <Tooltip title="Actualizar"><IconButton size="small" onClick={loadMeshes}><Refresh fontSize="small" /></IconButton></Tooltip>
        </Box>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {meshes.length} malla{meshes.length !== 1 ? 's' : ''} disponible{meshes.length !== 1 ? 's' : ''}
        </Typography>
        <Button variant="contained" fullWidth size="small" startIcon={<UploadFile />} onClick={() => { setSelectedFile(null); setUploadError(null); setUploadSuccess(null); setUploadProgress(0); setUploadOpen(true); }}>
          Cargar malla FEA
        </Button>
      </Box>

      <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
        <List dense>
          {meshes.map((m) => (
            <ListItem key={m.id} disablePadding secondaryAction={
              <Tooltip title="Eliminar">
                <IconButton edge="end" size="small" onClick={(e) => { e.stopPropagation(); setDeleteConfirmId(m.id); }} sx={{ opacity: 0.4, '&:hover': { opacity: 1, color: 'error.main' } }}>
                  <DeleteOutline fontSize="small" />
                </IconButton>
              </Tooltip>
            }>
              <ListItemButton selected={m.id === selectedMeshId} onClick={() => onSelectMesh(m)} sx={{ pr: 5 }}>
                <GridOn sx={{ mr: 1, fontSize: 18, color: 'info.main', flexShrink: 0 }} />
                <ListItemText
                  primary={m.original_filename}
                  primaryTypographyProps={{ noWrap: true, fontSize: '0.85rem' }}
                  secondary={
                    <Box component="span" sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                      {m.node_count > 0 && <Chip label={`${m.node_count?.toLocaleString()}n`} size="small" sx={{ height: 18, fontSize: '0.65rem' }} />}
                      {m.element_count > 0 && <Chip label={`${m.element_count?.toLocaleString()}e`} size="small" sx={{ height: 18, fontSize: '0.65rem' }} />}
                      {m.file_format && <Chip label={m.file_format.toUpperCase()} size="small" color="info" sx={{ height: 18, fontSize: '0.65rem' }} />}
                    </Box>
                  }
                />
              </ListItemButton>
            </ListItem>
          ))}
          {meshes.length === 0 && (
            <ListItem><Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>No hay mallas. Carga un archivo FEA.</Typography></ListItem>
          )}
        </List>
      </Box>

      {/* Delete confirm */}
      <Dialog open={!!deleteConfirmId} onClose={() => !deletingId && setDeleteConfirmId(null)} maxWidth="xs" fullWidth>
        <DialogTitle>¿Eliminar malla?</DialogTitle>
        <DialogContent><Typography variant="body2">Esta acción es irreversible.</Typography></DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmId(null)} disabled={!!deletingId}>Cancelar</Button>
          <Button color="error" variant="contained" onClick={() => handleDelete(deleteConfirmId)} disabled={!!deletingId}
            startIcon={deletingId ? <CircularProgress size={14} /> : null}>
            {deletingId ? 'Eliminando…' : 'Eliminar'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Upload dialog */}
      <Dialog open={uploadOpen} onClose={() => !uploading && setUploadOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Cargar malla FEA</DialogTitle>
        <DialogContent>
          <Box
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) setSelectedFile(f); }}
            onClick={() => fileInputRef.current?.click()}
            sx={{ border: 2, borderStyle: 'dashed', borderColor: dragOver ? 'info.main' : selectedFile ? 'success.main' : 'divider', borderRadius: 2, p: 3, mb: 2, textAlign: 'center', cursor: 'pointer', transition: 'all 0.2s' }}
          >
            <input ref={fileInputRef} type="file" accept=".vtu,.vtk,.inp,.bdf,.nas,.msh,.med,.exo,.cdb,.xdmf" style={{ display: 'none' }} onChange={(e) => setSelectedFile(e.target.files[0])} />
            <GridOn sx={{ fontSize: 40, color: selectedFile ? 'success.main' : 'text.secondary', mb: 1 }} />
            {selectedFile
              ? <Typography variant="body2" color="success.main" fontWeight="medium">{selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)</Typography>
              : <>
                <Typography variant="body2">Arrastra un archivo aquí o haz clic para seleccionar</Typography>
                <Typography variant="caption" color="text.secondary">{SUPPORTED}</Typography>
              </>
            }
          </Box>
          {uploading && <Box sx={{ mb: 1 }}><LinearProgress variant="determinate" value={uploadProgress} /><Typography variant="caption">{uploadProgress}%</Typography></Box>}
          {uploadError && <Alert severity="error" sx={{ mb: 1 }}>{uploadError}</Alert>}
          {uploadSuccess && <Alert severity="success" sx={{ mb: 1 }}>{uploadSuccess}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUploadOpen(false)} disabled={uploading}>Cancelar</Button>
          {uploadSuccess
            ? <Button variant="contained" onClick={() => setUploadOpen(false)}>Cerrar</Button>
            : <Button variant="contained" onClick={handleUpload} disabled={!selectedFile || uploading} startIcon={uploading ? <CircularProgress size={16} /> : <UploadFile />}>
              {uploading ? 'Cargando…' : 'Cargar'}
            </Button>
          }
        </DialogActions>
      </Dialog>
    </Box>
  );
}
