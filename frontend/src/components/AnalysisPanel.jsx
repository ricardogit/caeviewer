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
  Grid,
  Card,
  CardContent,
  ButtonGroup,
  Tooltip,
} from '@mui/material';
import {
  ExpandMore,
  Analytics,
  CheckCircle,
  Warning,
  Error,
  Info,
  Speed,
  VerifiedUser,
  BugReport,
  Assessment,
  TrendingUp,
  TrendingDown,
  RemoveCircle,
} from '@mui/icons-material';
import axios from 'axios';

export default function AnalysisPanel({ fileList, currentFileId, onAnalysisComplete }) {
  const [selectedFileId, setSelectedFileId] = useState(currentFileId || '');
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisType, setAnalysisType] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [validationResult, setValidationResult] = useState(null);
  const [complexityResult, setComplexityResult] = useState(null);
  const [qualityResult, setQualityResult] = useState(null);
  const [anomalyResult, setAnomalyResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (currentFileId) {
      setSelectedFileId(currentFileId);
    }
  }, [currentFileId]);

  async function handleCompleteAnalysis() {
    if (!selectedFileId) {
      setError('Please select a file to analyze');
      return;
    }

    setAnalyzing(true);
    setAnalysisType('complete');
    setError(null);
    setAnalysisResult(null);

    try {
      const response = await axios.post(`/api/step-view/analysis/${selectedFileId}/analyze`);
      setAnalysisResult(response.data);

      if (onAnalysisComplete) {
        onAnalysisComplete(response.data);
      }
    } catch (err) {
      console.error('Error analyzing file:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleValidation() {
    if (!selectedFileId) {
      setError('Please select a file to validate');
      return;
    }

    setAnalyzing(true);
    setAnalysisType('validation');
    setError(null);
    setValidationResult(null);

    try {
      const response = await axios.post(`/api/step-view/analysis/${selectedFileId}/validate`);
      setValidationResult(response.data);
    } catch (err) {
      console.error('Error validating file:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleComplexityAnalysis() {
    if (!selectedFileId) {
      setError('Please select a file');
      return;
    }

    setAnalyzing(true);
    setAnalysisType('complexity');
    setError(null);
    setComplexityResult(null);

    try {
      const response = await axios.get(`/api/step-view/analysis/${selectedFileId}/complexity`);
      setComplexityResult(response.data);
    } catch (err) {
      console.error('Error analyzing complexity:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleQualityAnalysis() {
    if (!selectedFileId) {
      setError('Please select a file');
      return;
    }

    setAnalyzing(true);
    setAnalysisType('quality');
    setError(null);
    setQualityResult(null);

    try {
      const response = await axios.get(`/api/step-view/analysis/${selectedFileId}/quality`);
      setQualityResult(response.data);
    } catch (err) {
      console.error('Error analyzing quality:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleAnomalyDetection() {
    if (!selectedFileId) {
      setError('Please select a file');
      return;
    }

    setAnalyzing(true);
    setAnalysisType('anomaly');
    setError(null);
    setAnomalyResult(null);

    try {
      const response = await axios.get(`/api/step-view/analysis/${selectedFileId}/anomalies`);
      setAnomalyResult(response.data);
    } catch (err) {
      console.error('Error detecting anomalies:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  function renderScoreCard(title, score, icon, color = 'primary') {
    return (
      <Card sx={{ height: '100%' }}>
        <CardContent>
          <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
            <Typography variant="h6" color="textSecondary">
              {title}
            </Typography>
            {icon}
          </Box>
          <Typography variant="h3" color={color}>
            {score !== null && score !== undefined ? score.toFixed(1) : 'N/A'}
          </Typography>
          <LinearProgress
            variant="determinate"
            value={score || 0}
            sx={{ mt: 2, height: 8, borderRadius: 4 }}
          />
        </CardContent>
      </Card>
    );
  }

  function renderCompleteAnalysis() {
    if (!analysisResult) return null;

    const {
      file_name,
      basic_stats,
      complexity_analysis,
      quality_metrics,
      graph_analysis,
      overall_score,
      classification
    } = analysisResult;

    return (
      <Box mt={3}>
        <Typography variant="h6" gutterBottom>
          Analysis Report: {file_name}
        </Typography>

        {/* Score Cards */}
        <Grid container spacing={2} mb={3}>
          <Grid item xs={12} md={3}>
            {renderScoreCard('Overall Score', overall_score, <Assessment color="primary" />)}
          </Grid>
          <Grid item xs={12} md={3}>
            {renderScoreCard('Quality Score', quality_metrics?.quality_score, <VerifiedUser color="success" />)}
          </Grid>
          <Grid item xs={12} md={3}>
            {renderScoreCard('Complexity', complexity_analysis?.complexity_score, <Speed color="warning" />)}
          </Grid>
          <Grid item xs={12} md={3}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="h6" color="textSecondary" gutterBottom>
                  Classification
                </Typography>
                <Chip
                  label={classification?.replace(/_/g, ' ').toUpperCase()}
                  color={
                    classification?.includes('simple') ? 'success' :
                    classification?.includes('medium') ? 'primary' :
                    classification?.includes('complex') ? 'warning' : 'error'
                  }
                  size="large"
                  sx={{ fontSize: '1rem', mt: 2 }}
                />
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {/* Basic Statistics */}
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Typography variant="h6">Basic Statistics</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <TableContainer>
              <Table size="small">
                <TableBody>
                  <TableRow>
                    <TableCell><strong>Total Entities</strong></TableCell>
                    <TableCell>{basic_stats?.total_entities || 0}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell><strong>Unique Types</strong></TableCell>
                    <TableCell>{basic_stats?.unique_types || 0}</TableCell>
                  </TableRow>
                  {basic_stats?.depth_stats && (
                    <>
                      <TableRow>
                        <TableCell><strong>Depth (Mean/Max)</strong></TableCell>
                        <TableCell>
                          {basic_stats.depth_stats.mean} / {basic_stats.depth_stats.max}
                        </TableCell>
                      </TableRow>
                    </>
                  )}
                  {basic_stats?.reference_stats && (
                    <TableRow>
                      <TableCell><strong>Total References</strong></TableCell>
                      <TableCell>{basic_stats.reference_stats.total}</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>

            {basic_stats?.entity_types && (
              <Box mt={2}>
                <Typography variant="subtitle2" gutterBottom>
                  Top Entity Types:
                </Typography>
                <Box display="flex" flexWrap="wrap" gap={1}>
                  {Object.entries(basic_stats.entity_types)
                    .slice(0, 10)
                    .map(([type, count]) => (
                      <Chip
                        key={type}
                        label={`${type}: ${count}`}
                        size="small"
                        variant="outlined"
                      />
                    ))}
                </Box>
              </Box>
            )}
          </AccordionDetails>
        </Accordion>

        {/* Complexity Analysis */}
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Typography variant="h6">Complexity Analysis</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>
                  Complexity Metrics
                </Typography>
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small">
                    <TableBody>
                      <TableRow>
                        <TableCell>Complexity Score</TableCell>
                        <TableCell align="right">
                          <strong>{complexity_analysis?.complexity_score?.toFixed(2)}</strong>
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>Cyclomatic Complexity</TableCell>
                        <TableCell align="right">
                          {complexity_analysis?.cyclomatic_complexity}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>Structural Complexity</TableCell>
                        <TableCell align="right">
                          {complexity_analysis?.structural_complexity?.toFixed(2)}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>Type Diversity</TableCell>
                        <TableCell align="right">
                          {(complexity_analysis?.type_diversity * 100)?.toFixed(2)}%
                        </TableCell>
                      </TableRow>
                    </TableBody>
                  </Table>
                </TableContainer>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>
                  Complexity Factors
                </Typography>
                <Box>
                  {complexity_analysis?.factors && Object.entries(complexity_analysis.factors).map(([key, value]) => (
                    <Box key={key} mb={1}>
                      <Box display="flex" justifyContent="space-between" mb={0.5}>
                        <Typography variant="body2">
                          {key.replace(/_/g, ' ').replace(/factor/g, '').trim()}
                        </Typography>
                        <Typography variant="body2">
                          {value?.toFixed(2)}
                        </Typography>
                      </Box>
                      <LinearProgress
                        variant="determinate"
                        value={(value / 30) * 100}
                        sx={{ height: 6, borderRadius: 3 }}
                      />
                    </Box>
                  ))}
                </Box>
              </Grid>
            </Grid>
          </AccordionDetails>
        </Accordion>

        {/* Quality Metrics */}
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Typography variant="h6">Quality Metrics</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>
                  Quality Scores
                </Typography>
                <Box>
                  <Box mb={2}>
                    <Box display="flex" justifyContent="space-between" mb={0.5}>
                      <Typography>Completeness</Typography>
                      <Typography>{quality_metrics?.completeness?.toFixed(1)}%</Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={quality_metrics?.completeness || 0}
                      color="success"
                      sx={{ height: 8, borderRadius: 4 }}
                    />
                  </Box>
                  <Box mb={2}>
                    <Box display="flex" justifyContent="space-between" mb={0.5}>
                      <Typography>Consistency</Typography>
                      <Typography>{quality_metrics?.consistency?.toFixed(1)}%</Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={quality_metrics?.consistency || 0}
                      color="info"
                      sx={{ height: 8, borderRadius: 4 }}
                    />
                  </Box>
                </Box>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>
                  Issues Summary
                </Typography>
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small">
                    <TableBody>
                      <TableRow>
                        <TableCell>Orphan Entities</TableCell>
                        <TableCell align="right">
                          {quality_metrics?.orphan_count}
                          ({quality_metrics?.orphan_percentage?.toFixed(1)}%)
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>Invalid References</TableCell>
                        <TableCell align="right">
                          {quality_metrics?.invalid_references}
                        </TableCell>
                      </TableRow>
                    </TableBody>
                  </Table>
                </TableContainer>

                {quality_metrics?.issues && quality_metrics.issues.length > 0 && (
                  <Box mt={2}>
                    <Typography variant="subtitle2" gutterBottom>
                      Detected Issues:
                    </Typography>
                    <List dense>
                      {quality_metrics.issues.map((issue, idx) => (
                        <ListItem key={idx}>
                          <Chip
                            icon={
                              issue.severity === 'high' ? <Error /> :
                              issue.severity === 'medium' ? <Warning /> : <Info />
                            }
                            label={`${issue.type}: ${issue.message}`}
                            size="small"
                            color={
                              issue.severity === 'high' ? 'error' :
                              issue.severity === 'medium' ? 'warning' : 'info'
                            }
                          />
                        </ListItem>
                      ))}
                    </List>
                  </Box>
                )}
              </Grid>
            </Grid>
          </AccordionDetails>
        </Accordion>

        {/* Graph Analysis */}
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Typography variant="h6">Graph Analysis</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small">
                    <TableBody>
                      <TableRow>
                        <TableCell>Graph Density</TableCell>
                        <TableCell align="right">
                          {graph_analysis?.graph_density?.toFixed(6)}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>Average Degree</TableCell>
                        <TableCell align="right">
                          {graph_analysis?.avg_degree?.toFixed(2)}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>Total Edges</TableCell>
                        <TableCell align="right">
                          {graph_analysis?.total_edges}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>Hub Count</TableCell>
                        <TableCell align="right">
                          {graph_analysis?.hub_count}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>Is Sparse</TableCell>
                        <TableCell align="right">
                          {graph_analysis?.is_sparse ? 'Yes' : 'No'}
                        </TableCell>
                      </TableRow>
                    </TableBody>
                  </Table>
                </TableContainer>
              </Grid>
              {graph_analysis?.in_degree_stats && (
                <Grid item xs={12} md={6}>
                  <Typography variant="subtitle2" gutterBottom>
                    In-Degree Statistics
                  </Typography>
                  <TableContainer component={Paper} variant="outlined">
                    <Table size="small">
                      <TableBody>
                        <TableRow>
                          <TableCell>Mean</TableCell>
                          <TableCell align="right">
                            {graph_analysis.in_degree_stats.mean}
                          </TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell>Median</TableCell>
                          <TableCell align="right">
                            {graph_analysis.in_degree_stats.median}
                          </TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell>Min / Max</TableCell>
                          <TableCell align="right">
                            {graph_analysis.in_degree_stats.min} / {graph_analysis.in_degree_stats.max}
                          </TableCell>
                        </TableRow>
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Grid>
              )}
            </Grid>
          </AccordionDetails>
        </Accordion>
      </Box>
    );
  }

  function renderValidationResult() {
    if (!validationResult) return null;

    const { is_valid, score, errors, warnings, info } = validationResult;

    return (
      <Box mt={3}>
        <Typography variant="h6" gutterBottom>
          Validation Report
        </Typography>

        <Card sx={{ mb: 2 }}>
          <CardContent>
            <Box display="flex" alignItems="center" justifyContent="space-between">
              <Box display="flex" alignItems="center" gap={2}>
                {is_valid ? (
                  <CheckCircle color="success" sx={{ fontSize: 40 }} />
                ) : (
                  <Error color="error" sx={{ fontSize: 40 }} />
                )}
                <Box>
                  <Typography variant="h6">
                    {is_valid ? 'Valid STEP File' : 'Invalid STEP File'}
                  </Typography>
                  <Typography variant="body2" color="textSecondary">
                    Validation Score: {score?.toFixed(1)}/100
                  </Typography>
                </Box>
              </Box>
              <LinearProgress
                variant="determinate"
                value={score || 0}
                sx={{ width: 200, height: 10, borderRadius: 5 }}
                color={score > 80 ? 'success' : score > 60 ? 'warning' : 'error'}
              />
            </Box>
          </CardContent>
        </Card>

        {errors && errors.length > 0 && (
          <Accordion defaultExpanded>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Box display="flex" alignItems="center" gap={1}>
                <Error color="error" />
                <Typography variant="h6">Errors ({errors.length})</Typography>
              </Box>
            </AccordionSummary>
            <AccordionDetails>
              <List>
                {errors.map((err, idx) => (
                  <ListItem key={idx}>
                    <Alert severity="error" sx={{ width: '100%' }}>
                      <Typography variant="subtitle2">{err.code}</Typography>
                      <Typography variant="body2">{err.message}</Typography>
                      {err.details && (
                        <Typography variant="caption" component="pre">
                          {JSON.stringify(err.details, null, 2)}
                        </Typography>
                      )}
                    </Alert>
                  </ListItem>
                ))}
              </List>
            </AccordionDetails>
          </Accordion>
        )}

        {warnings && warnings.length > 0 && (
          <Accordion defaultExpanded={errors.length === 0}>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Box display="flex" alignItems="center" gap={1}>
                <Warning color="warning" />
                <Typography variant="h6">Warnings ({warnings.length})</Typography>
              </Box>
            </AccordionSummary>
            <AccordionDetails>
              <List>
                {warnings.map((warn, idx) => (
                  <ListItem key={idx}>
                    <Alert severity="warning" sx={{ width: '100%' }}>
                      <Typography variant="subtitle2">{warn.code}</Typography>
                      <Typography variant="body2">{warn.message}</Typography>
                    </Alert>
                  </ListItem>
                ))}
              </List>
            </AccordionDetails>
          </Accordion>
        )}

        {info && info.length > 0 && (
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Box display="flex" alignItems="center" gap={1}>
                <Info color="info" />
                <Typography variant="h6">Info ({info.length})</Typography>
              </Box>
            </AccordionSummary>
            <AccordionDetails>
              <List>
                {info.map((inf, idx) => (
                  <ListItem key={idx}>
                    <Alert severity="info" sx={{ width: '100%' }}>
                      <Typography variant="subtitle2">{inf.code}</Typography>
                      <Typography variant="body2">{inf.message}</Typography>
                    </Alert>
                  </ListItem>
                ))}
              </List>
            </AccordionDetails>
          </Accordion>
        )}
      </Box>
    );
  }

  function renderComplexityResult() {
    if (!complexityResult) return null;

    return (
      <Box mt={3}>
        <Typography variant="h6" gutterBottom>
          Complexity Analysis
        </Typography>

        <Grid container spacing={2} mb={2}>
          <Grid item xs={12} md={6}>
            <Card>
              <CardContent>
                <Typography variant="h6" color="textSecondary" gutterBottom>
                  Complexity Score
                </Typography>
                <Typography variant="h3" color="warning.main">
                  {complexityResult.complexity_score?.toFixed(1)}
                </Typography>
                <LinearProgress
                  variant="determinate"
                  value={complexityResult.complexity_score || 0}
                  sx={{ mt: 2, height: 8, borderRadius: 4 }}
                />
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={6}>
            <Card>
              <CardContent>
                <Typography variant="h6" color="textSecondary" gutterBottom>
                  Classification
                </Typography>
                <Chip
                  label={complexityResult.classification?.toUpperCase()}
                  color={
                    complexityResult.classification === 'simple' ? 'success' :
                    complexityResult.classification === 'medium' ? 'primary' :
                    complexityResult.classification === 'complex' ? 'warning' : 'error'
                  }
                  sx={{ fontSize: '1.2rem', p: 2, mt: 1 }}
                />
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell><strong>Metric</strong></TableCell>
                <TableCell align="right"><strong>Value</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              <TableRow>
                <TableCell>Cyclomatic Complexity</TableCell>
                <TableCell align="right">{complexityResult.cyclomatic_complexity}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Structural Complexity</TableCell>
                <TableCell align="right">{complexityResult.structural_complexity?.toFixed(2)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Type Diversity</TableCell>
                <TableCell align="right">
                  {(complexityResult.type_diversity * 100)?.toFixed(2)}%
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
    );
  }

  function renderQualityResult() {
    if (!qualityResult) return null;

    return (
      <Box mt={3}>
        <Typography variant="h6" gutterBottom>
          Quality Metrics
        </Typography>

        <Grid container spacing={2} mb={2}>
          <Grid item xs={12} md={4}>
            {renderScoreCard('Quality Score', qualityResult.quality_score, <VerifiedUser color="success" />)}
          </Grid>
          <Grid item xs={12} md={4}>
            {renderScoreCard('Completeness', qualityResult.completeness, <CheckCircle color="success" />)}
          </Grid>
          <Grid item xs={12} md={4}>
            {renderScoreCard('Consistency', qualityResult.consistency, <CheckCircle color="info" />)}
          </Grid>
        </Grid>

        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell><strong>Metric</strong></TableCell>
                <TableCell align="right"><strong>Value</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              <TableRow>
                <TableCell>Orphan Entities</TableCell>
                <TableCell align="right">
                  {qualityResult.orphan_count} ({qualityResult.orphan_percentage?.toFixed(1)}%)
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Invalid References</TableCell>
                <TableCell align="right">{qualityResult.invalid_references}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>

        {qualityResult.issues && qualityResult.issues.length > 0 && (
          <Box mt={2}>
            <Typography variant="subtitle1" gutterBottom>
              Issues Detected:
            </Typography>
            <List>
              {qualityResult.issues.map((issue, idx) => (
                <ListItem key={idx}>
                  <Alert
                    severity={
                      issue.severity === 'high' ? 'error' :
                      issue.severity === 'medium' ? 'warning' : 'info'
                    }
                    sx={{ width: '100%' }}
                  >
                    <Typography variant="subtitle2">{issue.type}</Typography>
                    <Typography variant="body2">{issue.message}</Typography>
                  </Alert>
                </ListItem>
              ))}
            </List>
          </Box>
        )}
      </Box>
    );
  }

  function renderAnomalyResult() {
    if (!anomalyResult) return null;

    const { total_anomalies, anomalies, size_analysis, complexity_analysis } = anomalyResult;

    return (
      <Box mt={3}>
        <Typography variant="h6" gutterBottom>
          Anomaly Detection Report
        </Typography>

        <Card sx={{ mb: 2 }}>
          <CardContent>
            <Box display="flex" alignItems="center" gap={2}>
              {total_anomalies > 0 ? (
                <BugReport color="error" sx={{ fontSize: 40 }} />
              ) : (
                <CheckCircle color="success" sx={{ fontSize: 40 }} />
              )}
              <Box>
                <Typography variant="h6">
                  {total_anomalies > 0 ? `${total_anomalies} Anomalies Detected` : 'No Anomalies Detected'}
                </Typography>
                <Typography variant="body2" color="textSecondary">
                  File analyzed against historical data
                </Typography>
              </Box>
            </Box>
          </CardContent>
        </Card>

        {anomalies && anomalies.length > 0 && (
          <Accordion defaultExpanded>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Typography variant="h6">Detected Anomalies</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <List>
                {anomalies.map((anomaly, idx) => (
                  <ListItem key={idx}>
                    <Alert
                      severity={anomaly.severity === 'high' ? 'error' : 'warning'}
                      sx={{ width: '100%' }}
                    >
                      <Typography variant="subtitle2">{anomaly.type}</Typography>
                      <Typography variant="body2">{anomaly.message}</Typography>
                      <Typography variant="caption">
                        Z-Score: {anomaly.z_score} | Current: {anomaly.current} | Mean: {anomaly.mean}
                      </Typography>
                    </Alert>
                  </ListItem>
                ))}
              </List>
            </AccordionDetails>
          </Accordion>
        )}

        <Grid container spacing={2} mt={1}>
          {size_analysis?.stats && (
            <Grid item xs={12} md={6}>
              <Accordion>
                <AccordionSummary expandIcon={<ExpandMore />}>
                  <Typography variant="h6">Size Analysis</Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <TableContainer component={Paper} variant="outlined">
                    <Table size="small">
                      <TableBody>
                        <TableRow>
                          <TableCell>Current Size</TableCell>
                          <TableCell align="right">
                            {(size_analysis.stats.current / 1024 / 1024).toFixed(2)} MB
                          </TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell>Mean Size</TableCell>
                          <TableCell align="right">
                            {(size_analysis.stats.mean / 1024 / 1024).toFixed(2)} MB
                          </TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell>Std Deviation</TableCell>
                          <TableCell align="right">
                            {(size_analysis.stats.std / 1024 / 1024).toFixed(2)} MB
                          </TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell>Z-Score</TableCell>
                          <TableCell align="right">
                            <Chip
                              label={size_analysis.stats.z_score?.toFixed(2)}
                              color={size_analysis.stats.z_score > 3 ? 'error' : 'success'}
                              size="small"
                            />
                          </TableCell>
                        </TableRow>
                      </TableBody>
                    </Table>
                  </TableContainer>
                </AccordionDetails>
              </Accordion>
            </Grid>
          )}

          {complexity_analysis?.stats && (
            <Grid item xs={12} md={6}>
              <Accordion>
                <AccordionSummary expandIcon={<ExpandMore />}>
                  <Typography variant="h6">Complexity Analysis</Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <TableContainer component={Paper} variant="outlined">
                    <Table size="small">
                      <TableBody>
                        <TableRow>
                          <TableCell>Current Entity Count</TableCell>
                          <TableCell align="right">{complexity_analysis.stats.current}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell>Mean Entity Count</TableCell>
                          <TableCell align="right">{complexity_analysis.stats.mean?.toFixed(0)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell>Std Deviation</TableCell>
                          <TableCell align="right">{complexity_analysis.stats.std?.toFixed(0)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell>Z-Score</TableCell>
                          <TableCell align="right">
                            <Chip
                              label={complexity_analysis.stats.z_score?.toFixed(2)}
                              color={complexity_analysis.stats.z_score > 3 ? 'error' : 'success'}
                              size="small"
                            />
                          </TableCell>
                        </TableRow>
                      </TableBody>
                    </Table>
                  </TableContainer>
                </AccordionDetails>
              </Accordion>
            </Grid>
          )}
        </Grid>
      </Box>
    );
  }

  return (
    <Box>
      <Paper sx={{ p: 3, mb: 2 }}>
        <Typography variant="h5" gutterBottom>
          <Analytics sx={{ verticalAlign: 'middle', mr: 1 }} />
          Advanced Analysis
        </Typography>

        <Divider sx={{ my: 2 }} />

        {/* File Selector */}
        <FormControl fullWidth sx={{ mb: 2 }}>
          <InputLabel>Select File to Analyze</InputLabel>
          <Select
            value={selectedFileId}
            onChange={(e) => setSelectedFileId(e.target.value)}
            label="Select File to Analyze"
          >
            {fileList && fileList.map((file) => (
              <MenuItem key={file.id} value={file.id}>
                {file.file_name || file.id}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* Action Buttons */}
        <Typography variant="subtitle2" gutterBottom>
          Analysis Type:
        </Typography>
        <Grid container spacing={1} mb={2}>
          <Grid item xs={12} sm={6} md={4}>
            <Button
              fullWidth
              variant="contained"
              color="primary"
              startIcon={<Analytics />}
              onClick={handleCompleteAnalysis}
              disabled={analyzing || !selectedFileId}
            >
              Complete Analysis
            </Button>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Button
              fullWidth
              variant="outlined"
              startIcon={<VerifiedUser />}
              onClick={handleValidation}
              disabled={analyzing || !selectedFileId}
            >
              Validate File
            </Button>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Button
              fullWidth
              variant="outlined"
              startIcon={<Speed />}
              onClick={handleComplexityAnalysis}
              disabled={analyzing || !selectedFileId}
            >
              Complexity
            </Button>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Button
              fullWidth
              variant="outlined"
              startIcon={<Assessment />}
              onClick={handleQualityAnalysis}
              disabled={analyzing || !selectedFileId}
            >
              Quality Metrics
            </Button>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Button
              fullWidth
              variant="outlined"
              color="warning"
              startIcon={<BugReport />}
              onClick={handleAnomalyDetection}
              disabled={analyzing || !selectedFileId}
            >
              Detect Anomalies
            </Button>
          </Grid>
        </Grid>

        {/* Loading State */}
        {analyzing && (
          <Box display="flex" alignItems="center" gap={2} mb={2}>
            <CircularProgress size={24} />
            <Typography>
              {analysisType === 'complete' && 'Running complete analysis...'}
              {analysisType === 'validation' && 'Validating file...'}
              {analysisType === 'complexity' && 'Analyzing complexity...'}
              {analysisType === 'quality' && 'Calculating quality metrics...'}
              {analysisType === 'anomaly' && 'Detecting anomalies...'}
            </Typography>
          </Box>
        )}

        {/* Error Display */}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
      </Paper>

      {/* Results Display */}
      {analysisType === 'complete' && renderCompleteAnalysis()}
      {analysisType === 'validation' && renderValidationResult()}
      {analysisType === 'complexity' && renderComplexityResult()}
      {analysisType === 'quality' && renderQualityResult()}
      {analysisType === 'anomaly' && renderAnomalyResult()}
    </Box>
  );
}
