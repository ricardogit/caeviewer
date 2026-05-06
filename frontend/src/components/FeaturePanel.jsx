import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Divider,
  Chip,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  CircularProgress,
  Alert,
  IconButton,
  Tooltip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Button,
  LinearProgress,
  Badge,
} from '@mui/material';
import {
  ExpandMore,
  Build,
  Search,
  Refresh,
  FilterAlt,
  Info,
  CheckCircle,
  Error as ErrorIcon,
} from '@mui/icons-material';
import axios from 'axios';

/**
 * FeaturePanel - Panel de manufacturing features detectados automáticamente
 *
 * Props:
 * - headerId: UUID del STEP file header
 * - onFeatureSelect: Callback(entityId) al hacer click en un feature
 * - selectedFeatureId: ID del feature seleccionado (para highlight)
 */
export default function FeaturePanel({ headerId, onFeatureSelect, selectedFeatureId }) {
  const [features, setFeatures] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState(null);
  const [filterType, setFilterType] = useState(null);

  useEffect(() => {
    if (!headerId) return;
    loadFeatures();
    loadStats();
  }, [headerId]);

  async function loadFeatures() {
    setLoading(true);
    setError(null);

    try {
      const response = await axios.get(`/api/step-view/features/${headerId}/list`);
      setFeatures(response.data.features || []);
    } catch (err) {
      console.error('Error loading features:', err);
      setError(err.response?.data?.error || err.message || 'Failed to load features');
    } finally {
      setLoading(false);
    }
  }

  async function loadStats() {
    try {
      const response = await axios.get(`/api/step-view/features/${headerId}/stats`);
      setStats(response.data);
    } catch (err) {
      console.error('Error loading feature stats:', err);
    }
  }

  async function handleExtractFeatures() {
    setExtracting(true);
    setError(null);

    try {
      const response = await axios.post(`/api/step-view/features/${headerId}/extract`, {
        method: 'entity', // Usar análisis de entidades (no requiere PythonOCC)
        force_recompute: true
      });

      // Recargar features y stats
      await loadFeatures();
      await loadStats();

      console.log('Features extracted:', response.data);
    } catch (err) {
      console.error('Error extracting features:', err);
      setError(err.response?.data?.error || err.message || 'Failed to extract features');
    } finally {
      setExtracting(false);
    }
  }

  function handleFeatureClick(feature) {
    if (onFeatureSelect && feature.entity_id) {
      onFeatureSelect(feature.entity_id);
    }
  }

  function getFeatureIcon(featureType) {
    switch (featureType) {
      case 'HOLE':
        return '🔵';
      case 'POCKET':
        return '🟦';
      case 'SLOT':
        return '▬';
      case 'BOSS':
        return '🔴';
      case 'FILLET':
        return '◠';
      case 'CHAMFER':
        return '◢';
      default:
        return '⚙️';
    }
  }

  function getFeatureColor(featureType) {
    switch (featureType) {
      case 'HOLE':
        return 'primary';
      case 'POCKET':
        return 'secondary';
      case 'SLOT':
        return 'info';
      case 'BOSS':
        return 'warning';
      case 'FILLET':
        return 'success';
      case 'CHAMFER':
        return 'error';
      default:
        return 'default';
    }
  }

  function formatDimensions(dimensions) {
    if (!dimensions) return 'N/A';

    const parts = [];
    if (dimensions.diameter) {
      parts.push(`Ø${dimensions.diameter.toFixed(2)}mm`);
    }
    if (dimensions.depth) {
      parts.push(`depth: ${dimensions.depth.toFixed(2)}mm`);
    }
    if (dimensions.width) {
      parts.push(`width: ${dimensions.width.toFixed(2)}mm`);
    }
    if (dimensions.length) {
      parts.push(`length: ${dimensions.length.toFixed(2)}mm`);
    }

    return parts.join(', ') || 'N/A';
  }

  const filteredFeatures = filterType
    ? features.filter(f => f.feature_type === filterType)
    : features;

  if (loading) {
    return (
      <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress size={30} />
      </Box>
    );
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <Build fontSize="small" />
          <Typography variant="subtitle2">Manufacturing Features</Typography>
        </Box>

        {stats && (
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1 }}>
            <Chip
              label={`${stats.total_features} total`}
              size="small"
              variant="outlined"
              color="primary"
            />
            {Object.entries(stats.features_by_type || {}).map(([type, count]) => (
              <Chip
                key={type}
                label={`${count} ${type.toLowerCase()}`}
                size="small"
                onClick={() => setFilterType(filterType === type ? null : type)}
                color={filterType === type ? getFeatureColor(type) : 'default'}
                icon={<span>{getFeatureIcon(type)}</span>}
              />
            ))}
          </Box>
        )}

        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            size="small"
            startIcon={extracting ? <CircularProgress size={16} /> : <Search />}
            onClick={handleExtractFeatures}
            disabled={extracting}
            variant="contained"
            fullWidth
          >
            {extracting ? 'Extracting...' : 'Extract Features'}
          </Button>
          <IconButton size="small" onClick={loadFeatures} title="Refresh">
            <Refresh />
          </IconButton>
        </Box>
      </Box>

      {extracting && (
        <Box sx={{ px: 2 }}>
          <LinearProgress />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
            Analyzing STEP entities for manufacturing features...
          </Typography>
        </Box>
      )}

      {error && (
        <Box sx={{ p: 2 }}>
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        </Box>
      )}

      {/* Feature List */}
      {features.length === 0 && !loading && !extracting ? (
        <Box sx={{ p: 2 }}>
          <Alert severity="info">
            No features detected yet. Click "Extract Features" to analyze this file.
          </Alert>
        </Box>
      ) : (
        <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
          <List dense>
            {filteredFeatures.map((feature, index) => {
              const isSelected = feature.feature_id === selectedFeatureId;
              const dimensions = feature.dimensions || {};

              return (
                <ListItem
                  key={feature.feature_id || index}
                  disablePadding
                  sx={{
                    borderLeft: isSelected ? 3 : 0,
                    borderColor: 'primary.main',
                  }}
                >
                  <ListItemButton
                    onClick={() => handleFeatureClick(feature)}
                    selected={isSelected}
                  >
                    <Box sx={{ width: '100%' }}>
                      {/* Header */}
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                        <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                          {getFeatureIcon(feature.feature_type)} {feature.feature_id}
                        </Typography>
                        <Chip
                          label={feature.feature_type}
                          size="small"
                          color={getFeatureColor(feature.feature_type)}
                          sx={{ fontSize: '0.7rem', height: 20 }}
                        />
                        {feature.feature_subtype && (
                          <Chip
                            label={feature.feature_subtype}
                            size="small"
                            variant="outlined"
                            sx={{ fontSize: '0.65rem', height: 18 }}
                          />
                        )}
                      </Box>

                      {/* Dimensions */}
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                        {formatDimensions(dimensions)}
                      </Typography>

                      {/* Confidence */}
                      {feature.confidence && (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5 }}>
                          <LinearProgress
                            variant="determinate"
                            value={feature.confidence * 100}
                            sx={{ flexGrow: 1, height: 4, borderRadius: 2 }}
                            color={feature.confidence > 0.8 ? 'success' : 'warning'}
                          />
                          <Typography variant="caption" color="text.secondary">
                            {(feature.confidence * 100).toFixed(0)}%
                          </Typography>
                        </Box>
                      )}

                      {/* Entity reference */}
                      {feature.entity_id && (
                        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                          Entity #{feature.entity_id}
                        </Typography>
                      )}
                    </Box>
                  </ListItemButton>
                </ListItem>
              );
            })}
          </List>
        </Box>
      )}

      {/* Statistics Accordion */}
      {stats && stats.average_dimensions && (
        <Accordion sx={{ mt: 'auto' }}>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Info fontSize="small" />
              <Typography variant="body2">Average Dimensions</Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails>
            <List dense>
              {Object.entries(stats.average_dimensions).map(([type, dims]) => (
                <ListItem key={type}>
                  <ListItemText
                    primary={type}
                    secondary={formatDimensions(dims)}
                    primaryTypographyProps={{ variant: 'caption', fontWeight: 'bold' }}
                    secondaryTypographyProps={{ variant: 'caption' }}
                  />
                </ListItem>
              ))}
            </List>
          </AccordionDetails>
        </Accordion>
      )}
    </Box>
  );
}
