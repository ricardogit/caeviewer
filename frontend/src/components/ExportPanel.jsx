import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  ButtonGroup,
  FormControl,
  FormLabel,
  FormGroup,
  FormControlLabel,
  Checkbox,
  TextField,
  Select,
  MenuItem,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  CircularProgress,
  Alert,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
} from '@mui/material';
import {
  ExpandMore,
  FileDownload,
  Description,
  ThreeDRotation,
  Settings,
  CheckCircle,
} from '@mui/icons-material';
import axios from 'axios';

export default function ExportPanel({ headerId, fileName }) {
  const [formats, setFormats] = useState([]);
  const [selectedFormats, setSelectedFormats] = useState({
    stl: false,
    obj: false,
    iges: false,
    step: false,
    json: false,
    csv: false,
  });

  const [options, setOptions] = useState({
    shapeIndex: 0,
    stl: {
      asciiMode: false,
      linearDeflection: 0.1,
      angularDeflection: 0.5,
    },
    obj: {
      linearDeflection: 0.1,
      angularDeflection: 0.5,
    },
    step: {
      schema: 'AP214CD',
    },
    json: {
      includeTree: true,
      includeFeatures: false,
      includePmi: true,
      includeMeasurements: true,
    },
  });

  const [exporting, setExporting] = useState(false);
  const [exportResults, setExportResults] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadSupportedFormats();
  }, []);

  async function loadSupportedFormats() {
    try {
      const response = await axios.get('/api/step-view/export/formats');
      setFormats(response.data.formats || []);
    } catch (err) {
      console.error('Error loading formats:', err);
    }
  }

  function handleFormatToggle(format) {
    setSelectedFormats({
      ...selectedFormats,
      [format]: !selectedFormats[format],
    });
  }

  function handleOptionChange(format, option, value) {
    setOptions({
      ...options,
      [format]: {
        ...options[format],
        [option]: value,
      },
    });
  }

  async function handleExportSingle(format) {
    setExporting(true);
    setError(null);

    try {
      let endpoint = '';
      let body = { shape_index: options.shapeIndex, download: true };

      if (format === 'stl') {
        endpoint = `/api/step-view/export/${headerId}/stl`;
        body = { ...body, ...options.stl };
      } else if (format === 'obj') {
        endpoint = `/api/step-view/export/${headerId}/obj`;
        body = { ...body, ...options.obj };
      } else if (format === 'iges') {
        endpoint = `/api/step-view/export/${headerId}/iges`;
      } else if (format === 'step') {
        endpoint = `/api/step-view/export/${headerId}/step`;
        body = { ...body, ...options.step };
      } else if (format === 'json') {
        endpoint = `/api/step-view/export/${headerId}/metadata`;
        body = { ...options.json, download: true };
      }

      const response = await axios.post(endpoint, body, {
        responseType: 'blob',
      });

      // Descargar archivo
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${fileName || 'export'}.${format}`);
      document.body.appendChild(link);
      link.click();
      link.remove();

      setExportResults([
        ...exportResults,
        {
          format,
          success: true,
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      console.error(`Error exporting ${format}:`, err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setExporting(false);
    }
  }

  async function handleBatchExport() {
    setExporting(true);
    setError(null);

    try {
      const formatsToExport = Object.keys(selectedFormats).filter(
        (f) => selectedFormats[f]
      );

      if (formatsToExport.length === 0) {
        setError('Please select at least one format');
        setExporting(false);
        return;
      }

      const body = {
        shape_index: options.shapeIndex,
        formats: formatsToExport,
        options: {
          stl: options.stl,
          obj: options.obj,
          step: options.step,
        },
      };

      const response = await axios.post(
        `/api/step-view/export/${headerId}/batch`,
        body
      );

      if (response.data.batch_export) {
        setExportResults([
          {
            type: 'batch',
            formatsRequested: response.data.formats_requested,
            formatsSucceeded: response.data.formats_succeeded,
            totalSize: response.data.total_size_bytes,
            results: response.data.results,
            timestamp: new Date().toISOString(),
          },
        ]);
      }
    } catch (err) {
      console.error('Error in batch export:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setExporting(false);
    }
  }

  async function handleExportMeasurements() {
    setExporting(true);
    setError(null);

    try {
      const response = await axios.post(
        `/api/step-view/export/${headerId}/measurements/csv`,
        { download: true },
        { responseType: 'blob' }
      );

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${fileName || 'export'}_measurements.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();

      setExportResults([
        ...exportResults,
        {
          format: 'measurements_csv',
          success: true,
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      console.error('Error exporting measurements:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setExporting(false);
    }
  }

  async function handleExportPMI() {
    setExporting(true);
    setError(null);

    try {
      const response = await axios.post(
        `/api/step-view/export/${headerId}/pmi/csv`,
        { download: true },
        { responseType: 'blob' }
      );

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${fileName || 'export'}_pmi.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();

      setExportResults([
        ...exportResults,
        {
          format: 'pmi_csv',
          success: true,
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      console.error('Error exporting PMI:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setExporting(false);
    }
  }

  function getFormatColor(format) {
    const colors = {
      stl: 'primary',
      obj: 'secondary',
      iges: 'success',
      step: 'warning',
      json: 'info',
      csv: 'default',
    };
    return colors[format] || 'default';
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="subtitle2" gutterBottom>
          Export Tools
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Export geometry to multiple formats
        </Typography>
      </Box>

      {/* Shape Index */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <TextField
          size="small"
          fullWidth
          type="number"
          label="Shape Index"
          value={options.shapeIndex}
          onChange={(e) =>
            setOptions({ ...options, shapeIndex: parseInt(e.target.value) })
          }
          helperText="0 = first shape in assembly"
        />
      </Box>

      {/* Format Selection */}
      <Box sx={{ flexGrow: 1, overflow: 'auto', p: 2 }}>
        {/* 3D Formats */}
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <ThreeDRotation sx={{ mr: 1 }} />
            <Typography variant="subtitle2">3D Geometry Formats</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <FormGroup>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={selectedFormats.stl}
                    onChange={() => handleFormatToggle('stl')}
                  />
                }
                label="STL (Stereolithography)"
              />
              {selectedFormats.stl && (
                <Box sx={{ ml: 4, mb: 2 }}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={options.stl.asciiMode}
                        onChange={(e) =>
                          handleOptionChange('stl', 'asciiMode', e.target.checked)
                        }
                      />
                    }
                    label="ASCII Mode"
                  />
                  <TextField
                    size="small"
                    fullWidth
                    type="number"
                    label="Linear Deflection"
                    value={options.stl.linearDeflection}
                    onChange={(e) =>
                      handleOptionChange('stl', 'linearDeflection', parseFloat(e.target.value))
                    }
                    sx={{ mt: 1 }}
                  />
                </Box>
              )}

              <FormControlLabel
                control={
                  <Checkbox
                    checked={selectedFormats.obj}
                    onChange={() => handleFormatToggle('obj')}
                  />
                }
                label="OBJ (Wavefront)"
              />

              <FormControlLabel
                control={
                  <Checkbox
                    checked={selectedFormats.iges}
                    onChange={() => handleFormatToggle('iges')}
                  />
                }
                label="IGES"
              />

              <FormControlLabel
                control={
                  <Checkbox
                    checked={selectedFormats.step}
                    onChange={() => handleFormatToggle('step')}
                  />
                }
                label="STEP (re-export)"
              />
              {selectedFormats.step && (
                <Box sx={{ ml: 4, mb: 2 }}>
                  <FormControl fullWidth size="small">
                    <FormLabel>Schema</FormLabel>
                    <Select
                      value={options.step.schema}
                      onChange={(e) =>
                        handleOptionChange('step', 'schema', e.target.value)
                      }
                    >
                      <MenuItem value="AP203">AP203</MenuItem>
                      <MenuItem value="AP214CD">AP214CD</MenuItem>
                    </Select>
                  </FormControl>
                </Box>
              )}
            </FormGroup>

            <Button
              variant="contained"
              fullWidth
              startIcon={<FileDownload />}
              onClick={handleBatchExport}
              disabled={exporting || Object.values(selectedFormats).every((v) => !v)}
              sx={{ mt: 2 }}
            >
              {exporting ? <CircularProgress size={20} /> : 'Batch Export'}
            </Button>
          </AccordionDetails>
        </Accordion>

        {/* Data Formats */}
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Description sx={{ mr: 1 }} />
            <Typography variant="subtitle2">Data & Reports</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <ButtonGroup orientation="vertical" fullWidth>
              <Button
                startIcon={<FileDownload />}
                onClick={() => handleExportSingle('json')}
                disabled={exporting}
              >
                Export Metadata (JSON)
              </Button>

              <Button
                startIcon={<FileDownload />}
                onClick={handleExportMeasurements}
                disabled={exporting}
              >
                Export Measurements (CSV)
              </Button>

              <Button
                startIcon={<FileDownload />}
                onClick={handleExportPMI}
                disabled={exporting}
              >
                Export PMI (CSV)
              </Button>
            </ButtonGroup>

            {/* JSON Options */}
            <Box sx={{ mt: 2 }}>
              <Typography variant="caption" gutterBottom>
                JSON Export Options:
              </Typography>
              <FormGroup>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={options.json.includeTree}
                      onChange={(e) =>
                        handleOptionChange('json', 'includeTree', e.target.checked)
                      }
                    />
                  }
                  label="Include Tree"
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={options.json.includePmi}
                      onChange={(e) =>
                        handleOptionChange('json', 'includePmi', e.target.checked)
                      }
                    />
                  }
                  label="Include PMI"
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={options.json.includeMeasurements}
                      onChange={(e) =>
                        handleOptionChange('json', 'includeMeasurements', e.target.checked)
                      }
                    />
                  }
                  label="Include Measurements"
                />
              </FormGroup>
            </Box>
          </AccordionDetails>
        </Accordion>

        {/* Quick Export */}
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Settings sx={{ mr: 1 }} />
            <Typography variant="subtitle2">Quick Export</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <ButtonGroup orientation="vertical" fullWidth>
              <Button onClick={() => handleExportSingle('stl')} disabled={exporting}>
                STL (Binary)
              </Button>
              <Button onClick={() => handleExportSingle('obj')} disabled={exporting}>
                OBJ
              </Button>
              <Button onClick={() => handleExportSingle('iges')} disabled={exporting}>
                IGES
              </Button>
            </ButtonGroup>
          </AccordionDetails>
        </Accordion>

        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}

        {/* Export Results */}
        {exportResults.length > 0 && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="caption" color="text.secondary" gutterBottom>
              Recent Exports:
            </Typography>
            <List dense>
              {exportResults.slice(-5).reverse().map((result, idx) => (
                <ListItem key={idx}>
                  <ListItemIcon>
                    <CheckCircle color="success" fontSize="small" />
                  </ListItemIcon>
                  <ListItemText
                    primary={result.format || result.type}
                    secondary={new Date(result.timestamp).toLocaleTimeString()}
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}
      </Box>
    </Box>
  );
}
