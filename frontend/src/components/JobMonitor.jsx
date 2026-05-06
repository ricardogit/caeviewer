import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Paper,
  Typography,
  LinearProgress,
  Chip,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Collapse,
  Alert,
  Tooltip,
  CircularProgress,
} from '@mui/material';
import {
  CheckCircle,
  Error as ErrorIcon,
  Cancel,
  Refresh,
  ExpandMore,
  ExpandLess,
  Close,
  PlayArrow,
  Pause,
} from '@mui/icons-material';
import axios from 'axios';

/**
 * JobMonitor - Monitor de trabajos asíncronos en tiempo real
 *
 * Props:
 * - jobId: UUID del job a monitorear (opcional, si no se proporciona muestra lista)
 * - onComplete: Callback cuando el job se completa
 * - autoClose: Cerrar automáticamente cuando complete (default: false)
 */
export default function JobMonitor({ jobId, onComplete, autoClose = false }) {
  const [job, setJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(true);
  const eventSourceRef = useRef(null);

  // Monitorear job específico con SSE
  useEffect(() => {
    if (!jobId) {
      loadJobs();
      return;
    }

    loadJob();
    setupSSE();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [jobId]);

  async function loadJob() {
    try {
      const response = await axios.get(`/api/jobs/${jobId}`);
      setJob(response.data);
      setLoading(false);
    } catch (err) {
      console.error('Error loading job:', err);
      setError(err.response?.data?.error || err.message);
      setLoading(false);
    }
  }

  async function loadJobs() {
    setLoading(true);
    try {
      const response = await axios.get('/api/jobs?include_completed=false&limit=10');
      setJobs(response.data.jobs || []);
      setLoading(false);
    } catch (err) {
      console.error('Error loading jobs:', err);
      setError(err.response?.data?.error || err.message);
      setLoading(false);
    }
  }

  function setupSSE() {
    // Server-Sent Events para updates en tiempo real
    const eventSource = new EventSource(`/api/jobs/${jobId}/stream`);
    eventSourceRef.current = eventSource;

    eventSource.addEventListener('progress', (event) => {
      const data = JSON.parse(event.data);
      setJob(data);
    });

    eventSource.addEventListener('complete', (event) => {
      const data = JSON.parse(event.data);
      setJob(data);
      eventSource.close();

      if (onComplete) {
        onComplete(data);
      }

      if (autoClose) {
        setTimeout(() => {
          // Cerrar después de 2 segundos
        }, 2000);
      }
    });

    eventSource.addEventListener('error', (event) => {
      console.error('SSE error:', event);
      eventSource.close();
    });

    eventSource.onerror = (err) => {
      console.error('EventSource error:', err);
      eventSource.close();

      // Fallback a polling
      startPolling();
    };
  }

  function startPolling() {
    const interval = setInterval(async () => {
      try {
        const response = await axios.get(`/api/jobs/${jobId}`);
        setJob(response.data);

        if (['completed', 'failed', 'cancelled'].includes(response.data.status)) {
          clearInterval(interval);
          if (onComplete) {
            onComplete(response.data);
          }
        }
      } catch (err) {
        console.error('Polling error:', err);
        clearInterval(interval);
      }
    }, 2000); // Poll cada 2 segundos

    return () => clearInterval(interval);
  }

  async function handleCancelJob() {
    if (!jobId) return;

    try {
      await axios.post(`/api/jobs/${jobId}/cancel`);
      loadJob();
    } catch (err) {
      console.error('Error cancelling job:', err);
      setError(err.response?.data?.error || 'Failed to cancel job');
    }
  }

  function getStatusColor(status) {
    switch (status) {
      case 'completed':
        return 'success';
      case 'failed':
        return 'error';
      case 'cancelled':
        return 'warning';
      case 'processing':
        return 'primary';
      case 'pending':
        return 'default';
      default:
        return 'default';
    }
  }

  function getStatusIcon(status) {
    switch (status) {
      case 'completed':
        return <CheckCircle fontSize="small" />;
      case 'failed':
        return <ErrorIcon fontSize="small" />;
      case 'cancelled':
        return <Cancel fontSize="small" />;
      case 'processing':
        return <CircularProgress size={16} />;
      case 'pending':
        return <Pause fontSize="small" />;
      default:
        return null;
    }
  }

  function formatDuration(job) {
    if (!job.started_at) return 'Not started';

    const start = new Date(job.started_at);
    const end = job.completed_at ? new Date(job.completed_at) : new Date();
    const duration = Math.floor((end - start) / 1000);

    if (duration < 60) return `${duration}s`;
    if (duration < 3600) return `${Math.floor(duration / 60)}m ${duration % 60}s`;
    return `${Math.floor(duration / 3600)}h ${Math.floor((duration % 3600) / 60)}m`;
  }

  function formatJobType(type) {
    const types = {
      'import': 'Import',
      'geometry': 'Geometry',
      'features': 'Features',
      'analysis': 'Analysis',
      'batch_import': 'Batch Import'
    };
    return types[type] || type;
  }

  if (loading && !job) {
    return (
      <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress size={30} />
      </Box>
    );
  }

  // Vista de job individual
  if (jobId && job) {
    const isActive = ['pending', 'processing'].includes(job.status);

    return (
      <Paper sx={{ p: 2, mb: 2 }} elevation={3}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {getStatusIcon(job.status)}
            <Typography variant="subtitle2">
              {formatJobType(job.job_type)}
            </Typography>
            <Chip
              label={job.status}
              color={getStatusColor(job.status)}
              size="small"
            />
          </Box>

          {isActive && (
            <Tooltip title="Cancel Job">
              <IconButton size="small" onClick={handleCancelJob}>
                <Cancel fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Box>

        {/* Progress Bar */}
        {isActive && (
          <Box sx={{ mb: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="caption" color="text.secondary">
                {job.status_message || 'Processing...'}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {job.progress}%
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={job.progress}
              sx={{ height: 6, borderRadius: 3 }}
            />
          </Box>
        )}

        {/* Status Message */}
        {job.status_message && !isActive && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {job.status_message}
          </Typography>
        )}

        {/* Error Message */}
        {job.error_message && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {job.error_message}
          </Alert>
        )}

        {/* Duration */}
        <Typography variant="caption" color="text.secondary">
          Duration: {formatDuration(job)}
        </Typography>

        {/* Result Preview */}
        {job.result && (
          <Box sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              Result:
            </Typography>
            <Box
              component="pre"
              sx={{
                fontSize: '0.7rem',
                backgroundColor: 'background.default',
                p: 1,
                borderRadius: 1,
                overflow: 'auto',
                maxHeight: 100,
              }}
            >
              {JSON.stringify(job.result, null, 2)}
            </Box>
          </Box>
        )}
      </Paper>
    );
  }

  // Vista de lista de jobs
  return (
    <Paper sx={{ mb: 2 }}>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          p: 2,
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <PlayArrow fontSize="small" />
          <Typography variant="subtitle2">
            Active Jobs ({jobs.length})
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <IconButton size="small" onClick={(e) => { e.stopPropagation(); loadJobs(); }}>
            <Refresh fontSize="small" />
          </IconButton>
          <IconButton size="small">
            {expanded ? <ExpandLess /> : <ExpandMore />}
          </IconButton>
        </Box>
      </Box>

      <Collapse in={expanded}>
        {error && (
          <Box sx={{ px: 2, pb: 2 }}>
            <Alert severity="error">{error}</Alert>
          </Box>
        )}

        {jobs.length === 0 ? (
          <Box sx={{ p: 2 }}>
            <Typography variant="body2" color="text.secondary" align="center">
              No active jobs
            </Typography>
          </Box>
        ) : (
          <List dense>
            {jobs.map((jobItem) => (
              <ListItem
                key={jobItem.id}
                sx={{
                  borderLeft: 3,
                  borderColor: `${getStatusColor(jobItem.status)}.main`,
                }}
              >
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {getStatusIcon(jobItem.status)}
                      <Typography variant="body2">
                        {formatJobType(jobItem.job_type)}
                      </Typography>
                      <Chip
                        label={jobItem.status}
                        size="small"
                        color={getStatusColor(jobItem.status)}
                        sx={{ height: 20, fontSize: '0.7rem' }}
                      />
                    </Box>
                  }
                  secondary={
                    <Box>
                      <Typography variant="caption" color="text.secondary">
                        {jobItem.status_message || 'Processing...'}
                      </Typography>
                      {['pending', 'processing'].includes(jobItem.status) && (
                        <LinearProgress
                          variant="determinate"
                          value={jobItem.progress}
                          sx={{ mt: 0.5, height: 4, borderRadius: 2 }}
                        />
                      )}
                    </Box>
                  }
                />
              </ListItem>
            ))}
          </List>
        )}
      </Collapse>
    </Paper>
  );
}
