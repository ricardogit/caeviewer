/**
 * EntityProperties Component
 * =========================
 *
 * Displays detailed information about a selected STEP entity including:
 * - Basic entity information (type, ID, label)
 * - Entity attributes
 * - Relationships (references and referenced_by)
 * - Geometric properties
 * - Manufacturing information
 * - Navigation to related entities
 *
 * @module components/EntityProperties
 */

import React, { useEffect, useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Divider,
  Chip,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  IconButton,
  Collapse,
  CircularProgress,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Stack,
  Tooltip,
  Button,
  Paper,
} from '@mui/material';
import {
  ExpandMore as ExpandMoreIcon,
  Close as CloseIcon,
  AccountTree as GraphIcon,
  Refresh as RefreshIcon,
  ContentCopy as CopyIcon,
  OpenInNew as OpenInNewIcon,
  Category as CategoryIcon,
  Build as ManufacturingIcon,
  Insights as PropertiesIcon,
} from '@mui/icons-material';
import { useSelection } from '../hooks/useSelection';

/**
 * Main EntityProperties component
 *
 * @param {Object} props - Component props
 * @param {string|null} props.entityId - ID of the selected entity (UUID or STEP ID)
 * @param {Function} props.onClose - Callback when close button is clicked
 * @param {Function} props.onNavigateToEntity - Callback when navigating to related entity
 * @param {boolean} props.showCloseButton - Whether to show close button (default: true)
 */
export function EntityProperties({
  entityId,
  onClose,
  onNavigateToEntity,
  showCloseButton = true,
}) {
  const {
    entityData,
    loading,
    error,
    refreshEntityData,
  } = useSelection({ autoFetch: true });

  const [expandedSections, setExpandedSections] = useState({
    basic: true,
    attributes: false,
    references: false,
    referenced_by: false,
    geometry: false,
    manufacturing: false,
  });

  // Toggle section expansion
  const toggleSection = (section) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  // Copy text to clipboard
  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
  };

  // Handle navigation to related entity
  const handleNavigateToRelated = (relatedEntityId) => {
    if (onNavigateToEntity) {
      onNavigateToEntity(relatedEntityId);
    }
  };

  if (!entityId) {
    return (
      <Card>
        <CardContent>
          <Typography variant="body2" color="text.secondary">
            Selecciona una entidad en el modelo 3D o en el grafo para ver sus propiedades
          </Typography>
        </CardContent>
      </Card>
    );
  }

  if (loading) {
    return (
      <Card>
        <CardContent>
          <Box display="flex" alignItems="center" gap={2}>
            <CircularProgress size={24} />
            <Typography>Cargando información de entidad...</Typography>
          </Box>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent>
          <Alert severity="error">
            {error}
            <Button
              size="small"
              onClick={refreshEntityData}
              startIcon={<RefreshIcon />}
              sx={{ mt: 1 }}
            >
              Reintentar
            </Button>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  if (!entityData || !entityData.entity_info) {
    return (
      <Card>
        <CardContent>
          <Alert severity="warning">
            No se encontró información para esta entidad
          </Alert>
        </CardContent>
      </Card>
    );
  }

  const { entity_info, attributes, references, referenced_by, geometric_properties, manufacturing_info, graph_properties } = entityData;

  return (
    <Card sx={{ height: '100%', overflow: 'auto' }}>
      <CardContent>
        {/* Header */}
        <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={2}>
          <Box flex={1}>
            <Typography variant="h6" gutterBottom>
              {entity_info.entity_type}
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap">
              <Chip
                label={`#${entity_info.entity_id}`}
                size="small"
                color="primary"
                variant="outlined"
              />
              {entity_info.entity_category && (
                <Chip
                  label={entity_info.entity_category}
                  size="small"
                  color="secondary"
                  icon={<CategoryIcon />}
                />
              )}
              {entity_info.entity_label && (
                <Chip
                  label={entity_info.entity_label}
                  size="small"
                  variant="outlined"
                />
              )}
            </Stack>
          </Box>

          <Box display="flex" gap={1}>
            <Tooltip title="Refrescar">
              <IconButton size="small" onClick={refreshEntityData}>
                <RefreshIcon />
              </IconButton>
            </Tooltip>
            {showCloseButton && onClose && (
              <Tooltip title="Cerrar">
                <IconButton size="small" onClick={onClose}>
                  <CloseIcon />
                </IconButton>
              </Tooltip>
            )}
          </Box>
        </Box>

        <Divider sx={{ mb: 2 }} />

        {/* Graph Properties */}
        {graph_properties && (
          <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: 'background.default' }}>
            <Typography variant="subtitle2" gutterBottom>
              <GraphIcon sx={{ fontSize: 16, mr: 1, verticalAlign: 'middle' }} />
              Propiedades del Grafo
            </Typography>
            <Stack direction="row" spacing={2} flexWrap="wrap">
              <Chip label={`Profundidad: ${graph_properties.depth_level || 0}`} size="small" />
              <Chip label={`Grado: ${graph_properties.degree || 0}`} size="small" />
              <Chip label={`Salidas: ${graph_properties.out_degree || 0}`} size="small" />
              <Chip label={`Entradas: ${graph_properties.in_degree || 0}`} size="small" />
              {graph_properties.is_root && <Chip label="Raíz" size="small" color="success" />}
              {graph_properties.is_leaf && <Chip label="Hoja" size="small" color="info" />}
            </Stack>
          </Paper>
        )}

        {/* Entity Attributes */}
        {attributes && Object.keys(attributes).length > 0 && (
          <Accordion
            expanded={expandedSections.attributes}
            onChange={() => toggleSection('attributes')}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                <PropertiesIcon sx={{ fontSize: 16, mr: 1, verticalAlign: 'middle' }} />
                Atributos ({Object.keys(attributes).length})
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box component="pre" sx={{ fontSize: 12, overflow: 'auto', maxHeight: 200 }}>
                {JSON.stringify(attributes, null, 2)}
              </Box>
              <Button
                size="small"
                startIcon={<CopyIcon />}
                onClick={() => copyToClipboard(JSON.stringify(attributes, null, 2))}
                sx={{ mt: 1 }}
              >
                Copiar
              </Button>
            </AccordionDetails>
          </Accordion>
        )}

        {/* References (Outgoing) */}
        {references && references.length > 0 && (
          <Accordion
            expanded={expandedSections.references}
            onChange={() => toggleSection('references')}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                Referencias ({references.length})
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="caption" color="text.secondary" gutterBottom display="block">
                Entidades referenciadas por esta entidad
              </Typography>
              <List dense disablePadding>
                {references.map((ref) => (
                  <ListItem key={ref.id} disablePadding>
                    <ListItemButton onClick={() => handleNavigateToRelated(ref.id)}>
                      <ListItemText
                        primary={
                          <Box display="flex" alignItems="center" gap={1}>
                            <Chip label={`#${ref.entity_id}`} size="small" variant="outlined" />
                            <Typography variant="body2">{ref.entity_type}</Typography>
                          </Box>
                        }
                        secondary={ref.entity_label}
                      />
                      <OpenInNewIcon fontSize="small" color="action" />
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
            </AccordionDetails>
          </Accordion>
        )}

        {/* Referenced By (Incoming) */}
        {referenced_by && referenced_by.length > 0 && (
          <Accordion
            expanded={expandedSections.referenced_by}
            onChange={() => toggleSection('referenced_by')}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                Referenciado por ({referenced_by.length})
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="caption" color="text.secondary" gutterBottom display="block">
                Entidades que referencian a esta entidad
              </Typography>
              <List dense disablePadding>
                {referenced_by.map((ref) => (
                  <ListItem key={ref.id} disablePadding>
                    <ListItemButton onClick={() => handleNavigateToRelated(ref.id)}>
                      <ListItemText
                        primary={
                          <Box display="flex" alignItems="center" gap={1}>
                            <Chip label={`#${ref.entity_id}`} size="small" variant="outlined" />
                            <Typography variant="body2">{ref.entity_type}</Typography>
                          </Box>
                        }
                        secondary={ref.entity_label}
                      />
                      <OpenInNewIcon fontSize="small" color="action" />
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
            </AccordionDetails>
          </Accordion>
        )}

        {/* Geometric Properties */}
        {geometric_properties && (
          <Accordion
            expanded={expandedSections.geometry}
            onChange={() => toggleSection('geometry')}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                Propiedades Geométricas
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box component="pre" sx={{ fontSize: 12, overflow: 'auto', maxHeight: 200 }}>
                {JSON.stringify(geometric_properties, null, 2)}
              </Box>
            </AccordionDetails>
          </Accordion>
        )}

        {/* Manufacturing Information */}
        {manufacturing_info && (
          <Accordion
            expanded={expandedSections.manufacturing}
            onChange={() => toggleSection('manufacturing')}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                <ManufacturingIcon sx={{ fontSize: 16, mr: 1, verticalAlign: 'middle' }} />
                Información de Manufactura
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1}>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Tipo de Feature
                  </Typography>
                  <Typography variant="body2">{manufacturing_info.feature_type}</Typography>
                </Box>
                <Box>
                  <Stack direction="row" spacing={1}>
                    {manufacturing_info.is_geometric && (
                      <Chip label="Geométrica" size="small" color="primary" variant="outlined" />
                    )}
                    {manufacturing_info.is_topological && (
                      <Chip label="Topológica" size="small" color="secondary" variant="outlined" />
                    )}
                  </Stack>
                </Box>
                {manufacturing_info.feature_metadata && Object.keys(manufacturing_info.feature_metadata).length > 0 && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Metadata
                    </Typography>
                    <Box component="pre" sx={{ fontSize: 12, overflow: 'auto', maxHeight: 150 }}>
                      {JSON.stringify(manufacturing_info.feature_metadata, null, 2)}
                    </Box>
                  </Box>
                )}
              </Stack>
            </AccordionDetails>
          </Accordion>
        )}

        {/* Raw STEP Line */}
        {entity_info.raw_line && (
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                Línea STEP Original
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box
                component="pre"
                sx={{
                  fontSize: 11,
                  fontFamily: 'monospace',
                  overflow: 'auto',
                  bgcolor: 'grey.100',
                  p: 1,
                  borderRadius: 1,
                }}
              >
                {entity_info.raw_line}
              </Box>
              <Button
                size="small"
                startIcon={<CopyIcon />}
                onClick={() => copyToClipboard(entity_info.raw_line)}
                sx={{ mt: 1 }}
              >
                Copiar
              </Button>
            </AccordionDetails>
          </Accordion>
        )}

        {/* Metadata */}
        {entityData.metadata && (
          <Box mt={2} p={1} bgcolor="grey.50" borderRadius={1}>
            <Typography variant="caption" color="text.secondary" display="block">
              UUID: {entity_info.id}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block">
              Header: {entityData.metadata.header_id}
            </Typography>
            {entityData.metadata.neighbors_count !== undefined && (
              <Typography variant="caption" color="text.secondary" display="block">
                Vecinos: {entityData.metadata.neighbors_count}
              </Typography>
            )}
          </Box>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Compact version of EntityProperties for sidebar or drawer
 */
export function EntityPropertiesCompact({ entityId, onNavigateToEntity }) {
  const { entityData, loading, error } = useSelection({ autoFetch: true });

  if (!entityId) return null;
  if (loading) return <CircularProgress size={20} />;
  if (error) return <Alert severity="error" sx={{ fontSize: 12 }}>{error}</Alert>;
  if (!entityData?.entity_info) return null;

  const { entity_info, references, referenced_by } = entityData;

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        {entity_info.entity_type}
      </Typography>
      <Stack direction="row" spacing={1} mb={1}>
        <Chip label={`#${entity_info.entity_id}`} size="small" />
        {entity_info.entity_category && (
          <Chip label={entity_info.entity_category} size="small" color="secondary" />
        )}
      </Stack>

      {references && references.length > 0 && (
        <Box mb={1}>
          <Typography variant="caption" color="text.secondary">
            Referencias: {references.length}
          </Typography>
        </Box>
      )}

      {referenced_by && referenced_by.length > 0 && (
        <Box>
          <Typography variant="caption" color="text.secondary">
            Referenciado por: {referenced_by.length}
          </Typography>
        </Box>
      )}
    </Box>
  );
}

export default EntityProperties;
