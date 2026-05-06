/**
 * Viewer3D Component
 * ==================
 *
 * Componente principal de visualización 3D con React Three Fiber.
 * Proporciona canvas WebGL, controles de cámara, iluminación y
 * renderizado de modelos GLB.
 *
 * @module components/Viewer3D
 */

import React, { Suspense, useRef, useEffect, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Stats } from '@react-three/drei';
import { Box, CircularProgress, Alert, IconButton, Tooltip, Paper } from '@mui/material';
import {
  Fullscreen,
  FullscreenExit,
  CameraAlt,
  WbSunny,
  Settings,
  GridOn,
  GridOff,
  ThreeDRotation,
} from '@mui/icons-material';

import Scene3D from './Scene3D';
import LightingControls from './LightingControls';
import CameraControls from './CameraControls';
import { useViewerStore } from '../stores/viewerStore';
import { useModelLoader } from '../hooks/useModelLoader';

/**
 * Loading Fallback Component
 */
function LoadingFallback({ progress }) {
  return (
    <Box
      sx={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        textAlign: 'center',
        zIndex: 1000,
      }}
    >
      <CircularProgress
        variant={progress > 0 ? 'determinate' : 'indeterminate'}
        value={progress}
        size={60}
      />
      {progress > 0 && (
        <Box sx={{ mt: 2, color: 'white' }}>
          Loading: {Math.round(progress)}%
        </Box>
      )}
    </Box>
  );
}

/**
 * Viewer3D Component
 *
 * @param {object} props - Component props
 * @param {string} props.modelId - ID del modelo a cargar
 * @param {number} props.width - Ancho del canvas (default: '100%')
 * @param {number} props.height - Alto del canvas (default: '600px')
 * @param {boolean} props.showControls - Mostrar controles UI (default: true)
 * @param {function} props.onModelLoad - Callback cuando el modelo se carga
 * @param {function} props.onSelectionChange - Callback cuando cambia la selección
 * @param {object} props.canvasProps - Props adicionales para el Canvas
 */
export default function Viewer3D({
  modelId,
  width = '100%',
  height = '600px',
  showControls: showControlsProp = true,
  onModelLoad,
  onSelectionChange,
  canvasProps = {},
}) {
  const containerRef = useRef(null);
  const [controlsOpen, setControlsOpen] = useState({
    lighting: false,
    camera: false,
  });

  // Store state
  const {
    backgroundColor,
    showGrid,
    showAxes,
    showStats,
    fullscreen,
    toggleFullscreen,
    toggleGrid,
    showControls: showControlsStore,
    enableAntialias,
    enableShadows,
    pixelRatio,
    cameraAutoRotate,
    cameraAutoRotateSpeed,
    selectedEntity,
  } = useViewerStore();

  // Cargar modelo
  const { model, loading, error, progress, metadata } = useModelLoader(modelId, {
    enableCache: true,
    enableDraco: true,
    onLoad: (gltf) => {
      console.log('Model loaded:', gltf);
      onModelLoad?.(gltf);
    },
  });

  // Notificar cambios de selección
  useEffect(() => {
    onSelectionChange?.(selectedEntity);
  }, [selectedEntity, onSelectionChange]);

  // Manejar fullscreen
  useEffect(() => {
    if (fullscreen && containerRef.current) {
      if (containerRef.current.requestFullscreen) {
        containerRef.current.requestFullscreen();
      }
    } else if (document.fullscreenElement) {
      document.exitFullscreen();
    }
  }, [fullscreen]);

  const handleToggleLightingControls = () => {
    setControlsOpen((prev) => ({ ...prev, lighting: !prev.lighting }));
  };

  const handleToggleCameraControls = () => {
    setControlsOpen((prev) => ({ ...prev, camera: !prev.camera }));
  };

  const showControlsUI = showControlsProp && showControlsStore;

  return (
    <Box
      ref={containerRef}
      sx={{
        position: 'relative',
        width,
        height: fullscreen ? '100vh' : height,
        backgroundColor: backgroundColor,
        overflow: 'hidden',
      }}
    >
      {/* Canvas 3D */}
      <Canvas
        shadows={enableShadows}
        dpr={pixelRatio}
        gl={{
          antialias: enableAntialias,
          alpha: false,
          stencil: false,
          depth: true,
          powerPreference: 'high-performance',
        }}
        camera={{
          position: [5, 5, 5],
          fov: 50,
          near: 0.1,
          far: 1000,
        }}
        {...canvasProps}
      >
        {/* Stats de rendimiento */}
        {showStats && <Stats />}

        {/* Controles de cámara orbital */}
        <OrbitControls
          makeDefault
          autoRotate={cameraAutoRotate}
          autoRotateSpeed={cameraAutoRotateSpeed}
          enableDamping
          dampingFactor={0.05}
          minDistance={1}
          maxDistance={100}
          maxPolarAngle={Math.PI / 2}
        />

        {/* Escena 3D */}
        <Suspense fallback={null}>
          <Scene3D
            model={model}
            showGrid={showGrid}
            showAxes={showAxes}
          />
        </Suspense>
      </Canvas>

      {/* Loading Overlay */}
      {loading && <LoadingFallback progress={progress} />}

      {/* Error Display */}
      {error && (
        <Box
          sx={{
            position: 'absolute',
            top: 16,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 1000,
            maxWidth: '80%',
          }}
        >
          <Alert severity="error" onClose={() => {}}>
            Error loading model: {error}
          </Alert>
        </Box>
      )}

      {/* Toolbar de controles */}
      {showControlsUI && (
        <Paper
          sx={{
            position: 'absolute',
            top: 16,
            right: 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 1,
            p: 1,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            backdropFilter: 'blur(10px)',
          }}
        >
          {/* Toggle Fullscreen */}
          <Tooltip title={fullscreen ? 'Exit Fullscreen' : 'Fullscreen'} placement="left">
            <IconButton
              onClick={toggleFullscreen}
              sx={{ color: 'white' }}
              size="small"
            >
              {fullscreen ? <FullscreenExit /> : <Fullscreen />}
            </IconButton>
          </Tooltip>

          {/* Toggle Grid */}
          <Tooltip title={showGrid ? 'Hide Grid' : 'Show Grid'} placement="left">
            <IconButton
              onClick={toggleGrid}
              sx={{ color: showGrid ? 'primary.main' : 'white' }}
              size="small"
            >
              {showGrid ? <GridOn /> : <GridOff />}
            </IconButton>
          </Tooltip>

          {/* Lighting Controls */}
          <Tooltip title="Lighting" placement="left">
            <IconButton
              onClick={handleToggleLightingControls}
              sx={{ color: controlsOpen.lighting ? 'primary.main' : 'white' }}
              size="small"
            >
              <WbSunny />
            </IconButton>
          </Tooltip>

          {/* Camera Controls */}
          <Tooltip title="Camera" placement="left">
            <IconButton
              onClick={handleToggleCameraControls}
              sx={{ color: controlsOpen.camera ? 'primary.main' : 'white' }}
              size="small"
            >
              <CameraAlt />
            </IconButton>
          </Tooltip>

          {/* Auto Rotate */}
          <Tooltip title="Auto Rotate" placement="left">
            <IconButton
              onClick={() => useViewerStore.getState().toggleAutoRotate()}
              sx={{ color: cameraAutoRotate ? 'primary.main' : 'white' }}
              size="small"
            >
              <ThreeDRotation />
            </IconButton>
          </Tooltip>
        </Paper>
      )}

      {/* Panel de controles de iluminación */}
      {controlsOpen.lighting && (
        <Box
          sx={{
            position: 'absolute',
            top: 16,
            left: 16,
            maxWidth: 320,
            maxHeight: 'calc(100% - 32px)',
            overflow: 'auto',
          }}
        >
          <LightingControls onClose={() => setControlsOpen({ ...controlsOpen, lighting: false })} />
        </Box>
      )}

      {/* Panel de controles de cámara */}
      {controlsOpen.camera && (
        <Box
          sx={{
            position: 'absolute',
            bottom: 16,
            left: 16,
            maxWidth: 320,
          }}
        >
          <CameraControls onClose={() => setControlsOpen({ ...controlsOpen, camera: false })} />
        </Box>
      )}

      {/* Información del modelo (bottom left) */}
      {metadata && showControlsUI && (
        <Paper
          sx={{
            position: 'absolute',
            bottom: 16,
            right: 16,
            p: 2,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            backdropFilter: 'blur(10px)',
            color: 'white',
            minWidth: 200,
          }}
        >
          <Box sx={{ fontSize: '0.875rem' }}>
            <Box sx={{ fontWeight: 'bold', mb: 1 }}>Model Info</Box>
            {metadata.file_name && (
              <Box>File: {metadata.file_name}</Box>
            )}
            {metadata.faces_count && (
              <Box>Faces: {metadata.faces_count.toLocaleString()}</Box>
            )}
            {metadata.vertices_count && (
              <Box>Vertices: {metadata.vertices_count.toLocaleString()}</Box>
            )}
            {model && (
              <Box>Meshes: {model.scene.children.length}</Box>
            )}
          </Box>
        </Paper>
      )}
    </Box>
  );
}

/**
 * Viewer3D con opciones por defecto para uso rápido
 */
export function SimpleViewer3D({ modelId, height = '600px' }) {
  return (
    <Viewer3D
      modelId={modelId}
      height={height}
      showControls={true}
    />
  );
}

/**
 * Viewer3D en modo fullscreen
 */
export function FullscreenViewer3D({ modelId, onClose }) {
  useEffect(() => {
    useViewerStore.getState().toggleFullscreen();

    return () => {
      if (useViewerStore.getState().fullscreen) {
        useViewerStore.getState().toggleFullscreen();
      }
    };
  }, []);

  return (
    <Viewer3D
      modelId={modelId}
      showControls={true}
    />
  );
}
