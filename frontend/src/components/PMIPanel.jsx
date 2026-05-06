import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Chip,
  List,
  ListItem,
  ListItemText,
  CircularProgress,
  Alert,
  Button,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import { ExpandMore, Straighten, Build, Comment } from '@mui/icons-material';
import axios from 'axios';

export default function PMIPanel({ headerId, onAnnotationSelect, onAnnotationsLoaded }) {
  const [annotations, setAnnotations] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!headerId) return;
    loadPMI();
    loadStats();
  }, [headerId]);

  async function loadPMI() {
    setLoading(true);
    try {
      const response = await axios.get(`/api/step-view/pmi/${headerId}/list`);
      const data = response.data.annotations || [];
      setAnnotations(data);
      onAnnotationsLoaded?.(data);
    } catch (err) {
      console.error('Error loading PMI:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadStats() {
    try {
      const response = await axios.get(`/api/step-view/pmi/${headerId}/stats`);
      setStats(response.data);
    } catch (err) {
      console.error('Error loading PMI stats:', err);
    }
  }

  async function handleExtractPMI() {
    setExtracting(true);
    try {
      await axios.post(`/api/step-view/pmi/${headerId}/extract`);
      await loadPMI();
      await loadStats();
    } catch (err) {
      setError(err.message);
    } finally {
      setExtracting(false);
    }
  }

  function getPMIIcon(type) {
    switch (type) {
      case 'DIMENSION': return <Straighten fontSize="small" />;
      case 'GD&T': return '⊕';
      case 'SURFACE_FINISH': return '✓';
      case 'NOTE': return <Comment fontSize="small" />;
      case 'DATUM': return '▲';
      default: return <Build fontSize="small" />;
    }
  }

  function getPMIColor(type) {
    switch (type) {
      case 'DIMENSION': return 'primary';
      case 'GD&T': return 'secondary';
      case 'SURFACE_FINISH': return 'success';
      case 'NOTE': return 'info';
      case 'DATUM': return 'warning';
      default: return 'default';
    }
  }

  function formatValue(annotation) {
    if (!annotation.value) return annotation.text || 'N/A';

    const val = annotation.value;
    const unit = annotation.unit || 'mm';

    if (annotation.subtype === 'DIAMETER') {
      return `Ø${val.toFixed(2)} ${unit}`;
    } else if (annotation.subtype === 'RADIUS') {
      return `R${val.toFixed(2)} ${unit}`;
    } else if (annotation.subtype === 'ANGULAR') {
      return `${val.toFixed(1)}°`;
    }

    return `${val.toFixed(2)} ${unit}`;
  }

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
        <Typography variant="subtitle2" gutterBottom>
          PMI Annotations
        </Typography>

        {stats && (
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1 }}>
            <Chip
              label={`${stats.total_annotations} total`}
              size="small"
              variant="outlined"
            />
            {Object.entries(stats.annotations_by_type || {}).map(([type, count]) => (
              <Chip
                key={type}
                label={`${count} ${type}`}
                size="small"
                color={getPMIColor(type)}
              />
            ))}
          </Box>
        )}

        <Button
          size="small"
          onClick={handleExtractPMI}
          disabled={extracting}
          variant="contained"
          fullWidth
        >
          {extracting ? 'Extracting...' : 'Extract PMI'}
        </Button>
      </Box>

      {error && (
        <Box sx={{ p: 2 }}>
          <Alert severity="error">{error}</Alert>
        </Box>
      )}

      {/* Annotations List */}
      {annotations.length === 0 ? (
        <Box sx={{ p: 2 }}>
          <Alert severity="info">
            No PMI annotations found. Click "Extract PMI" to analyze.
          </Alert>
        </Box>
      ) : (
        <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
          <List dense>
            {annotations.map((ann, idx) => (
              <ListItem key={idx}>
                <Box sx={{ width: '100%' }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                    {getPMIIcon(ann.pmi_type)}
                    <Chip
                      label={ann.pmi_type}
                      size="small"
                      color={getPMIColor(ann.pmi_type)}
                      sx={{ fontSize: '0.7rem', height: 20 }}
                    />
                    {ann.subtype && (
                      <Chip
                        label={ann.subtype}
                        size="small"
                        variant="outlined"
                        sx={{ fontSize: '0.65rem', height: 18 }}
                      />
                    )}
                  </Box>

                  <Typography variant="body2">
                    {formatValue(ann)}
                  </Typography>

                  {ann.datum_references && ann.datum_references.length > 0 && (
                    <Typography variant="caption" color="text.secondary">
                      Datums: {ann.datum_references.join(', ')}
                    </Typography>
                  )}
                </Box>
              </ListItem>
            ))}
          </List>
        </Box>
      )}
    </Box>
  );
}
