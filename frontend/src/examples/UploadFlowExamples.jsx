/**
 * Upload Flow Examples
 * ====================
 *
 * Ejemplos completos del flujo de carga y procesamiento de archivos STEP.
 *
 * @module examples/UploadFlowExamples
 */

import React, { useState } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Tabs,
  Tab,
  Divider,
  Stack,
  Alert,
  Button,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';

import FileUploader from '../components/FileUploader';
import UploadProgress, {
  CompactUploadProgress,
  MultipleUploadProgress,
} from '../components/UploadProgress';

/**
 * Tab Panel Helper
 */
function TabPanel({ children, value, index }) {
  return (
    <div hidden={value !== index}>
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

/**
 * Ejemplo 1: Upload Simple
 */
function SimpleUploadExample() {
  const [modelId, setModelId] = useState(null);
  const [uploadComplete, setUploadComplete] = useState(false);

  const handleUploadComplete = (result) => {
    console.log('Upload complete:', result);
    setModelId(result.model_id);

    // Si ya está procesado, marcar como completo
    if (result.already_processed) {
      setUploadComplete(true);
    }
  };

  const handleProcessingComplete = (data) => {
    console.log('Processing complete:', data);
    setUploadComplete(true);
  };

  const handleReset = () => {
    setModelId(null);
    setUploadComplete(false);
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        1. Upload Simple
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Ejemplo básico de upload con seguimiento de progreso.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Code:
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`const [modelId, setModelId] = useState(null);

const handleUploadComplete = (result) => {
  setModelId(result.model_id);
};

<FileUploader
  onUploadComplete={handleUploadComplete}
  maxSizeMB={500}
/>

{modelId && (
  <UploadProgress
    modelId={modelId}
    onComplete={(data) => console.log('Done!', data)}
  />
)}`}
        </Box>
      </Paper>

      {/* Uploader */}
      {!modelId && (
        <FileUploader
          onUploadComplete={handleUploadComplete}
          onUploadError={(error) => console.error(error)}
          maxSizeMB={500}
        />
      )}

      {/* Progress */}
      {modelId && !uploadComplete && (
        <Box sx={{ mt: 2 }}>
          <UploadProgress
            modelId={modelId}
            onComplete={handleProcessingComplete}
            onError={(error) => console.error(error)}
          />
        </Box>
      )}

      {/* Complete */}
      {uploadComplete && (
        <Box sx={{ mt: 2 }}>
          <Alert severity="success" sx={{ mb: 2 }}>
            ¡Archivo procesado exitosamente! Modelo ID: {modelId}
          </Alert>
          <Button variant="outlined" onClick={handleReset}>
            Subir otro archivo
          </Button>
        </Box>
      )}
    </Box>
  );
}

/**
 * Ejemplo 2: Upload con Redirección Automática
 */
function UploadWithRedirectExample() {
  const navigate = useNavigate();
  const [modelId, setModelId] = useState(null);

  const handleUploadComplete = (result) => {
    setModelId(result.model_id);

    // Si ya está procesado, redirigir inmediatamente
    if (result.already_processed) {
      setTimeout(() => {
        navigate(`/viewer/${result.model_id}`);
      }, 1500);
    }
  };

  const handleProcessingComplete = (data) => {
    // Redirigir al visualizador cuando termine el procesamiento
    setTimeout(() => {
      navigate(`/viewer/${modelId}`);
    }, 1500);
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        2. Upload con Redirección Automática
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Redirige automáticamente al visualizador cuando el procesamiento termina.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Code:
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`const navigate = useNavigate();

const handleProcessingComplete = (data) => {
  // Redirigir al visualizador
  setTimeout(() => {
    navigate(\`/viewer/\${modelId}\`);
  }, 1500);
};

<FileUploader onUploadComplete={handleUploadComplete} />
<UploadProgress
  modelId={modelId}
  onComplete={handleProcessingComplete}
/>`}
        </Box>
      </Paper>

      {!modelId && (
        <FileUploader
          onUploadComplete={handleUploadComplete}
          maxSizeMB={500}
        />
      )}

      {modelId && (
        <Box sx={{ mt: 2 }}>
          <UploadProgress
            modelId={modelId}
            onComplete={handleProcessingComplete}
          />
          <Alert severity="info" sx={{ mt: 2 }}>
            Serás redirigido automáticamente al visualizador cuando termine el procesamiento...
          </Alert>
        </Box>
      )}
    </Box>
  );
}

/**
 * Ejemplo 3: Upload Múltiple
 */
function MultipleUploadExample() {
  const [modelIds, setModelIds] = useState([]);
  const [allComplete, setAllComplete] = useState(false);

  const handleUploadComplete = (result) => {
    setModelIds((prev) => [...prev, result.model_id]);
  };

  const handleAllComplete = () => {
    setAllComplete(true);
  };

  const handleReset = () => {
    setModelIds([]);
    setAllComplete(false);
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        3. Upload Múltiple
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Cargar y procesar múltiples archivos simultáneamente.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Code:
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`const [modelIds, setModelIds] = useState([]);

<FileUploader
  multiple={true}
  onUploadComplete={(result) => {
    setModelIds(prev => [...prev, result.model_id]);
  }}
/>

{modelIds.length > 0 && (
  <MultipleUploadProgress
    modelIds={modelIds}
    onAllComplete={() => console.log('All done!')}
  />
)}`}
        </Box>
      </Paper>

      {!allComplete && (
        <FileUploader
          multiple={true}
          onUploadComplete={handleUploadComplete}
          maxSizeMB={500}
        />
      )}

      {modelIds.length > 0 && !allComplete && (
        <Box sx={{ mt: 2 }}>
          <MultipleUploadProgress
            modelIds={modelIds}
            onAllComplete={handleAllComplete}
          />
        </Box>
      )}

      {allComplete && (
        <Box sx={{ mt: 2 }}>
          <Alert severity="success" sx={{ mb: 2 }}>
            ¡Todos los archivos procesados exitosamente! ({modelIds.length} archivos)
          </Alert>
          <Button variant="outlined" onClick={handleReset}>
            Subir más archivos
          </Button>
        </Box>
      )}
    </Box>
  );
}

/**
 * Ejemplo 4: Upload con Manejo de Errores
 */
function UploadWithErrorHandlingExample() {
  const [modelId, setModelId] = useState(null);
  const [error, setError] = useState(null);

  const handleUploadComplete = (result) => {
    setModelId(result.model_id);
    setError(null);
  };

  const handleUploadError = (err) => {
    setError(err);
  };

  const handleProcessingError = (err) => {
    setError(`Error en procesamiento: ${err}`);
  };

  const handleRetry = () => {
    setError(null);
    setModelId(null);
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        4. Upload con Manejo de Errores
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Manejo robusto de errores con opción de reintentar.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Code:
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`const [error, setError] = useState(null);

<FileUploader
  onUploadComplete={handleUploadComplete}
  onUploadError={(err) => setError(err)}
/>

<UploadProgress
  modelId={modelId}
  onError={(err) => setError(\`Processing error: \${err}\`)}
  onRetry={() => {
    setError(null);
    // Retry logic
  }}
/>

{error && (
  <Alert severity="error">
    {error}
    <Button onClick={handleRetry}>Retry</Button>
  </Alert>
)}`}
        </Box>
      </Paper>

      {!modelId && (
        <FileUploader
          onUploadComplete={handleUploadComplete}
          onUploadError={handleUploadError}
          maxSizeMB={500}
        />
      )}

      {modelId && (
        <Box sx={{ mt: 2 }}>
          <UploadProgress
            modelId={modelId}
            onError={handleProcessingError}
            onRetry={handleRetry}
          />
        </Box>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
    </Box>
  );
}

/**
 * Ejemplo 5: Upload Compacto
 */
function CompactUploadExample() {
  const [modelIds, setModelIds] = useState([]);

  const handleUploadComplete = (result) => {
    setModelIds((prev) => [...prev, result.model_id]);
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        5. Upload Compacto
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Vista compacta para mostrar múltiples uploads en menos espacio.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Code:
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`import { CompactUploadProgress } from './UploadProgress';

{modelIds.map((modelId) => (
  <CompactUploadProgress
    key={modelId}
    modelId={modelId}
    filename={\`Model \${modelId}\`}
  />
))}`}
        </Box>
      </Paper>

      <FileUploader
        multiple={true}
        onUploadComplete={handleUploadComplete}
        maxSizeMB={500}
      />

      {modelIds.length > 0 && (
        <Stack spacing={1} sx={{ mt: 2 }}>
          <Typography variant="subtitle2">
            Archivos en Procesamiento ({modelIds.length})
          </Typography>
          {modelIds.map((modelId) => (
            <CompactUploadProgress
              key={modelId}
              modelId={modelId}
              filename={`Model ${modelId}`}
            />
          ))}
        </Stack>
      )}
    </Box>
  );
}

/**
 * Componente principal de ejemplos
 */
export default function UploadFlowExamples() {
  const [currentTab, setCurrentTab] = useState(0);

  const handleTabChange = (event, newValue) => {
    setCurrentTab(newValue);
  };

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Typography variant="h3" gutterBottom>
        Upload Flow Examples
      </Typography>
      <Typography variant="body1" color="text.secondary" paragraph>
        Ejemplos completos del flujo de carga y procesamiento de archivos STEP.
      </Typography>

      <Divider sx={{ my: 3 }} />

      <Paper sx={{ mt: 3 }}>
        <Tabs
          value={currentTab}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
        >
          <Tab label="1. Upload Simple" />
          <Tab label="2. Con Redirección" />
          <Tab label="3. Upload Múltiple" />
          <Tab label="4. Manejo de Errores" />
          <Tab label="5. Vista Compacta" />
        </Tabs>

        <TabPanel value={currentTab} index={0}>
          <SimpleUploadExample />
        </TabPanel>
        <TabPanel value={currentTab} index={1}>
          <UploadWithRedirectExample />
        </TabPanel>
        <TabPanel value={currentTab} index={2}>
          <MultipleUploadExample />
        </TabPanel>
        <TabPanel value={currentTab} index={3}>
          <UploadWithErrorHandlingExample />
        </TabPanel>
        <TabPanel value={currentTab} index={4}>
          <CompactUploadExample />
        </TabPanel>
      </Paper>

      {/* Quick Start Guide */}
      <Paper sx={{ mt: 3, p: 3 }}>
        <Typography variant="h5" gutterBottom>
          Quick Start Guide
        </Typography>

        <Typography variant="subtitle1" gutterBottom sx={{ mt: 2 }}>
          1. Importar Componentes
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`import FileUploader from './components/FileUploader';
import UploadProgress from './components/UploadProgress';
import { useProcessingStatus } from './hooks/useUploadNotifications';`}
        </Box>

        <Typography variant="subtitle1" gutterBottom sx={{ mt: 2 }}>
          2. Uso Básico
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`function UploadPage() {
  const [modelId, setModelId] = useState(null);

  return (
    <>
      <FileUploader
        onUploadComplete={(result) => {
          setModelId(result.model_id);
        }}
      />

      {modelId && (
        <UploadProgress
          modelId={modelId}
          onComplete={(data) => {
            console.log('Processing complete!', data);
          }}
        />
      )}
    </>
  );
}`}
        </Box>

        <Typography variant="subtitle1" gutterBottom sx={{ mt: 2 }}>
          3. Con Hook Personalizado
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: 1,
            overflow: 'auto',
          }}
        >
          {`function CustomProgress({ modelId }) {
  const {
    progress,
    stage,
    message,
    completed,
    error
  } = useProcessingStatus(modelId);

  return (
    <div>
      <p>Progress: {progress}%</p>
      <p>Stage: {stage}</p>
      <p>Message: {message}</p>
      {completed && <p>✅ Complete!</p>}
      {error && <p>❌ Error: {error}</p>}
    </div>
  );
}`}
        </Box>
      </Paper>
    </Container>
  );
}
