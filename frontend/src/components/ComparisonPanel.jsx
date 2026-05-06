import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  CircularProgress,
  Alert,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  LinearProgress,
  Divider,
  List,
  ListItem,
  ListItemText,
} from '@mui/material';
import {
  ExpandMore,
  Compare,
  TrendingUp,
  TrendingDown,
  Remove,
  CheckCircle,
  Error,
} from '@mui/icons-material';
import axios from 'axios';

export default function ComparisonPanel({ fileList, onComparisonComplete }) {
  const [file1Id, setFile1Id] = useState('');
  const [file2Id, setFile2Id] = useState('');
  const [comparing, setComparing] = useState(false);
  const [comparisonResult, setComparisonResult] = useState(null);
  const [error, setError] = useState(null);
  const [versions, setVersions] = useState([]);

  async function handleCompare() {
    if (!file1Id || !file2Id) {
      setError('Please select two files to compare');
      return;
    }

    if (file1Id === file2Id) {
      setError('Please select different files');
      return;
    }

    setComparing(true);
    setError(null);
    setComparisonResult(null);

    try {
      const response = await axios.post('/api/step-view/comparison/compare', {
        file1_id: file1Id,
        file2_id: file2Id,
        include_geometry: true,
        save_result: true,
      });

      setComparisonResult(response.data);

      if (onComparisonComplete) {
        onComparisonComplete(response.data);
      }
    } catch (err) {
      console.error('Error comparing files:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setComparing(false);
    }
  }

  async function handleCalculateSimilarity() {
    if (!file1Id || !file2Id) {
      setError('Please select two files');
      return;
    }

    setComparing(true);
    setError(null);

    try {
      const response = await axios.post('/api/step-view/comparison/similarity', {
        file1_id: file1Id,
        file2_id: file2Id,
        include_geometry: true,
      });

      alert(`Similarity: ${(response.data.similarity_score * 100).toFixed(1)}%`);
    } catch (err) {
      console.error('Error calculating similarity:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setComparing(false);
    }
  }

  function renderSimilarityBar(score) {
    const percent = score * 100;
    const color = percent >= 90 ? 'success' : percent >= 70 ? 'warning' : 'error';

    return (
      <Box sx={{ width: '100%', mt: 2 }}>
        <Typography variant="caption" gutterBottom>
          Similarity Score: {percent.toFixed(1)}%
        </Typography>
        <LinearProgress
          variant="determinate"
          value={percent}
          color={color}
          sx={{ height: 8, borderRadius: 1 }}
        />
      </Box>
    );
  }

  function renderChangeSummary(summary) {
    if (!summary) return null;

    return (
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Change Summary
        </Typography>

        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
          {summary.has_changes ? (
            <Chip
              icon={<Error />}
              label="Changes Detected"
              color="warning"
              size="small"
            />
          ) : (
            <Chip
              icon={<CheckCircle />}
              label="No Changes"
              color="success"
              size="small"
            />
          )}

          {summary.metadata_changes > 0 && (
            <Chip
              label={`${summary.metadata_changes} Metadata Changes`}
              size="small"
              variant="outlined"
            />
          )}

          {summary.structure_changed && (
            <Chip label="Structure Changed" size="small" color="info" />
          )}

          {summary.geometry_changed && (
            <Chip label="Geometry Changed" size="small" color="secondary" />
          )}

          {summary.entities_added > 0 && (
            <Chip
              icon={<TrendingUp fontSize="small" />}
              label={`+${summary.entities_added} Entities`}
              size="small"
              color="success"
            />
          )}

          {summary.entities_removed > 0 && (
            <Chip
              icon={<TrendingDown fontSize="small" />}
              label={`-${summary.entities_removed} Entities`}
              size="small"
              color="error"
            />
          )}
        </Box>
      </Box>
    );
  }

  function renderMetadataDiff(metadataDiff) {
    if (!metadataDiff || !metadataDiff.differences) return null;

    const changedFields = Object.entries(metadataDiff.differences).filter(
      ([_, value]) => value.changed
    );

    if (changedFields.length === 0) {
      return (
        <Alert severity="success" sx={{ mt: 2 }}>
          No metadata changes
        </Alert>
      );
    }

    return (
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Field</TableCell>
              <TableCell>File 1</TableCell>
              <TableCell>File 2</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {changedFields.map(([field, value]) => (
              <TableRow key={field}>
                <TableCell>
                  <strong>{field}</strong>
                </TableCell>
                <TableCell>{String(value.old || 'N/A')}</TableCell>
                <TableCell>{String(value.new || 'N/A')}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    );
  }

  function renderStructureDiff(structureDiff) {
    if (!structureDiff || !structureDiff.metric_differences) return null;

    const metrics = Object.entries(structureDiff.metric_differences);

    return (
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Metric</TableCell>
              <TableCell align="right">File 1</TableCell>
              <TableCell align="right">File 2</TableCell>
              <TableCell align="right">Delta</TableCell>
              <TableCell align="right">% Change</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {metrics.map(([metric, data]) => (
              <TableRow key={metric}>
                <TableCell>{metric.replace(/_/g, ' ')}</TableCell>
                <TableCell align="right">{data.old}</TableCell>
                <TableCell align="right">{data.new}</TableCell>
                <TableCell
                  align="right"
                  sx={{
                    color: data.delta > 0 ? 'success.main' : data.delta < 0 ? 'error.main' : 'text.primary',
                  }}
                >
                  {data.delta > 0 ? '+' : ''}
                  {data.delta}
                </TableCell>
                <TableCell
                  align="right"
                  sx={{
                    color: data.percent_change > 0 ? 'success.main' : data.percent_change < 0 ? 'error.main' : 'text.primary',
                  }}
                >
                  {data.percent_change > 0 ? '+' : ''}
                  {data.percent_change.toFixed(1)}%
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    );
  }

  function renderGeometryDiff(geometryDiff) {
    if (!geometryDiff || geometryDiff.error) {
      return (
        <Alert severity="info" sx={{ mt: 2 }}>
          {geometryDiff?.error || 'No geometry comparison available'}
        </Alert>
      );
    }

    const { volume, center_of_mass } = geometryDiff;

    return (
      <Box sx={{ mt: 2 }}>
        {volume && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              Volume Comparison
            </Typography>
            <TableContainer component={Paper}>
              <Table size="small">
                <TableBody>
                  <TableRow>
                    <TableCell>File 1 Volume</TableCell>
                    <TableCell align="right">{volume.old.toFixed(2)} mm³</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>File 2 Volume</TableCell>
                    <TableCell align="right">{volume.new.toFixed(2)} mm³</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>
                      <strong>Delta</strong>
                    </TableCell>
                    <TableCell
                      align="right"
                      sx={{
                        color: volume.delta > 0 ? 'success.main' : volume.delta < 0 ? 'error.main' : 'text.primary',
                        fontWeight: 'bold',
                      }}
                    >
                      {volume.delta > 0 ? '+' : ''}
                      {volume.delta.toFixed(2)} mm³ ({volume.percent_change.toFixed(1)}%)
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}

        {center_of_mass && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              Center of Mass
            </Typography>
            <TableContainer component={Paper}>
              <Table size="small">
                <TableBody>
                  <TableRow>
                    <TableCell>File 1 CoM</TableCell>
                    <TableCell align="right">
                      ({center_of_mass.old[0].toFixed(2)}, {center_of_mass.old[1].toFixed(2)}, {center_of_mass.old[2].toFixed(2)})
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>File 2 CoM</TableCell>
                    <TableCell align="right">
                      ({center_of_mass.new[0].toFixed(2)}, {center_of_mass.new[1].toFixed(2)}, {center_of_mass.new[2].toFixed(2)})
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>
                      <strong>Distance</strong>
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 'bold' }}>
                      {center_of_mass.distance.toFixed(2)} mm
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}
      </Box>
    );
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="subtitle2" gutterBottom>
          Version Comparison
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Compare two STEP files to detect changes
        </Typography>
      </Box>

      {/* File Selection */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <FormControl fullWidth size="small" sx={{ mb: 2 }}>
          <InputLabel>File 1 (Base)</InputLabel>
          <Select
            value={file1Id}
            label="File 1 (Base)"
            onChange={(e) => setFile1Id(e.target.value)}
          >
            {fileList.map((file) => (
              <MenuItem key={file.header_id} value={file.header_id}>
                {file.file_name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl fullWidth size="small" sx={{ mb: 2 }}>
          <InputLabel>File 2 (Compare)</InputLabel>
          <Select
            value={file2Id}
            label="File 2 (Compare)"
            onChange={(e) => setFile2Id(e.target.value)}
          >
            {fileList.map((file) => (
              <MenuItem key={file.header_id} value={file.header_id}>
                {file.file_name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="contained"
            fullWidth
            startIcon={<Compare />}
            onClick={handleCompare}
            disabled={comparing || !file1Id || !file2Id}
          >
            {comparing ? <CircularProgress size={20} /> : 'Compare'}
          </Button>

          <Button
            variant="outlined"
            onClick={handleCalculateSimilarity}
            disabled={comparing || !file1Id || !file2Id}
          >
            Similarity
          </Button>
        </Box>
      </Box>

      {/* Comparison Results */}
      <Box sx={{ flexGrow: 1, overflow: 'auto', p: 2 }}>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {comparisonResult && (
          <>
            {/* Similarity Score */}
            {renderSimilarityBar(comparisonResult.similarity_score)}

            <Divider sx={{ my: 2 }} />

            {/* Change Summary */}
            {renderChangeSummary(comparisonResult.change_summary)}

            {/* Metadata Diff */}
            <Accordion>
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Typography variant="subtitle2">Metadata Changes</Typography>
                {comparisonResult.metadata_diff?.change_count > 0 && (
                  <Chip
                    label={comparisonResult.metadata_diff.change_count}
                    size="small"
                    color="warning"
                    sx={{ ml: 1 }}
                  />
                )}
              </AccordionSummary>
              <AccordionDetails>
                {renderMetadataDiff(comparisonResult.metadata_diff)}
              </AccordionDetails>
            </Accordion>

            {/* Structure Diff */}
            <Accordion>
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Typography variant="subtitle2">Structure Changes</Typography>
                {comparisonResult.structure_diff?.structure_changed && (
                  <Chip label="Changed" size="small" color="info" sx={{ ml: 1 }} />
                )}
              </AccordionSummary>
              <AccordionDetails>
                {renderStructureDiff(comparisonResult.structure_diff)}
              </AccordionDetails>
            </Accordion>

            {/* Geometry Diff */}
            <Accordion>
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Typography variant="subtitle2">Geometry Changes</Typography>
                {comparisonResult.geometry_diff?.geometry_changed && (
                  <Chip label="Changed" size="small" color="secondary" sx={{ ml: 1 }} />
                )}
              </AccordionSummary>
              <AccordionDetails>
                {renderGeometryDiff(comparisonResult.geometry_diff)}
              </AccordionDetails>
            </Accordion>
          </>
        )}
      </Box>
    </Box>
  );
}
