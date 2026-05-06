import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Divider,
  Chip,
  List,
  ListItem,
  ListItemText,
  CircularProgress,
  Alert,
  IconButton,
  Tooltip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import {
  ExpandMore,
  Code,
  Link as LinkIcon,
  Category,
  Build,
  Close,
} from '@mui/icons-material';
import axios from 'axios';

/**
 * EntityDetails - Panel de detalles de una entidad STEP
 *
 * Props:
 * - headerId: UUID del STEP file header
 * - entityId: ID de la entidad a mostrar
 * - onClose: Callback para cerrar el panel
 * - onEntityClick: Callback(entityId) al hacer click en una referencia
 */
export default function EntityDetails({ headerId, entityId, onClose, onEntityClick }) {
  const [entity, setEntity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!headerId || !entityId) return;
    loadEntityDetails();
  }, [headerId, entityId]);

  async function loadEntityDetails() {
    setLoading(true);
    setError(null);

    try {
      const response = await axios.get(
        `/api/step-view/graph/${headerId}/entity/${entityId}`
      );
      setEntity(response.data);
    } catch (err) {
      console.error('Error loading entity details:', err);
      setError(err.response?.data?.error || err.message || 'Failed to load entity');
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'center' }}>
          <CircularProgress size={30} />
        </Box>
      </Paper>
    );
  }

  if (error) {
    return (
      <Paper sx={{ p: 2 }}>
        <Alert severity="error">{error}</Alert>
      </Paper>
    );
  }

  if (!entity) {
    return null;
  }

  return (
    <Paper sx={{ p: 2, height: '100%', overflow: 'auto' }}>
      {/* Header con botón cerrar */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6">Entity #{entity.entity_id}</Typography>
        {onClose && (
          <IconButton size="small" onClick={onClose}>
            <Close />
          </IconButton>
        )}
      </Box>

      <Divider sx={{ mb: 2 }} />

      {/* Información básica */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Type
        </Typography>
        <Chip label={entity.entity_type} color="primary" sx={{ mb: 1 }} />

        {entity.entity_label && (
          <>
            <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>
              Label
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {entity.entity_label}
            </Typography>
          </>
        )}

        {entity.entity_category && (
          <>
            <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>
              Category
            </Typography>
            <Chip label={entity.entity_category} size="small" icon={<Category />} />
          </>
        )}

        {entity.manufacturing_feature && (
          <>
            <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>
              Manufacturing Feature
            </Typography>
            <Chip
              label={entity.manufacturing_feature}
              size="small"
              color="secondary"
              icon={<Build />}
            />
          </>
        )}
      </Box>

      <Divider sx={{ my: 2 }} />

      {/* Propiedades del grafo */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Graph Properties
        </Typography>
        <List dense>
          <ListItem>
            <ListItemText
              primary="Depth Level"
              secondary={entity.depth_level || 'N/A'}
            />
          </ListItem>
          <ListItem>
            <ListItemText
              primary="Is Root"
              secondary={entity.is_root ? 'Yes' : 'No'}
            />
          </ListItem>
          <ListItem>
            <ListItemText
              primary="Is Leaf"
              secondary={entity.is_leaf ? 'Yes' : 'No'}
            />
          </ListItem>
        </List>
      </Box>

      {/* Referencias (outgoing) */}
      {entity.references_to && entity.references_to.length > 0 && (
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <LinkIcon fontSize="small" />
              <Typography variant="body2">
                References To ({entity.references_to.length})
              </Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails>
            <List dense>
              {entity.references_to.map((refId) => (
                <ListItem
                  key={refId}
                  button
                  onClick={() => onEntityClick && onEntityClick(refId)}
                >
                  <ListItemText primary={`Entity #${refId}`} />
                  <IconButton size="small">
                    <LinkIcon fontSize="small" />
                  </IconButton>
                </ListItem>
              ))}
            </List>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Referencias (incoming) */}
      {entity.referenced_by && entity.referenced_by.length > 0 && (
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <LinkIcon fontSize="small" />
              <Typography variant="body2">
                Referenced By ({entity.referenced_by.length})
              </Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails>
            <List dense>
              {entity.referenced_by.map((refId) => (
                <ListItem
                  key={refId}
                  button
                  onClick={() => onEntityClick && onEntityClick(refId)}
                >
                  <ListItemText primary={`Entity #${refId}`} />
                  <IconButton size="small">
                    <LinkIcon fontSize="small" />
                  </IconButton>
                </ListItem>
              ))}
            </List>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Atributos STEP */}
      {entity.attributes && Object.keys(entity.attributes).length > 0 && (
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Code fontSize="small" />
              <Typography variant="body2">STEP Attributes</Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails>
            <Box
              component="pre"
              sx={{
                fontSize: '0.75rem',
                overflow: 'auto',
                backgroundColor: 'background.default',
                p: 1,
                borderRadius: 1,
              }}
            >
              {JSON.stringify(entity.attributes, null, 2)}
            </Box>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Línea STEP raw */}
      {entity.raw_line && (
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Code fontSize="small" />
              <Typography variant="body2">Raw STEP Line</Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails>
            <Box
              component="pre"
              sx={{
                fontSize: '0.7rem',
                overflow: 'auto',
                backgroundColor: 'background.default',
                p: 1,
                borderRadius: 1,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {entity.raw_line}
            </Box>
          </AccordionDetails>
        </Accordion>
      )}
    </Paper>
  );
}
