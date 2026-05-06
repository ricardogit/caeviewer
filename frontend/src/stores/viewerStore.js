/**
 * Viewer Store - Zustand State Management
 * ========================================
 *
 * Gestiona el estado global del visor 3D:
 * - Modelos cargados
 * - Configuración de cámara
 * - Iluminación
 * - Modo de visualización
 * - Selección de entidades
 *
 * @module stores/viewerStore
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

/**
 * Modos de visualización disponibles
 */
export const RENDER_MODES = {
  REALISTIC: 'realistic',
  WIREFRAME: 'wireframe',
  XRAY: 'xray',
  MATCAP: 'matcap',
  NORMALS: 'normals',
  DEPTH: 'depth',
};

/**
 * Presets de iluminación
 */
export const LIGHTING_PRESETS = {
  STUDIO: 'studio',
  OUTDOOR: 'outdoor',
  SOFT: 'soft',
  DRAMATIC: 'dramatic',
  CUSTOM: 'custom',
};

/**
 * Estado inicial del viewer
 */
const initialState = {
  // Modelo
  currentModel: null,
  modelUrl: null,
  modelLoading: false,
  modelError: null,
  modelMetadata: null,

  // Renderizado
  renderMode: RENDER_MODES.REALISTIC,
  showWireframe: false,
  showGrid: true,
  showAxes: true,
  backgroundColor: '#1a1a1a',

  // Cámara
  cameraPosition: [5, 5, 5],
  cameraTarget: [0, 0, 0],
  cameraFov: 50,
  cameraAutoRotate: false,
  cameraAutoRotateSpeed: 1.0,

  // Iluminación
  lightingPreset: LIGHTING_PRESETS.STUDIO,
  ambientLightIntensity: 0.5,
  directionalLightIntensity: 1.0,
  directionalLightPosition: [10, 10, 5],
  hemisphereLight: true,
  hemisphereLightSkyColor: '#ffffff',
  hemisphereLightGroundColor: '#444444',
  hemisphereLightIntensity: 0.3,

  // Selección (Legacy)
  selectedEntity: null,
  hoveredEntity: null,
  highlightedEntities: [],

  // Selección bidireccional (Nueva API)
  selectedEntityId: null,
  highlightedEntityId: null,
  selectedEntityData: null,

  // Mediciones
  measurements: [],
  measurementMode: false,

  // Performance
  enableShadows: true,
  enableAntialias: true,
  pixelRatio: window.devicePixelRatio,
  maxPixelRatio: 2,

  // UI
  showStats: false,
  showControls: true,
  fullscreen: false,
};

/**
 * Viewer Store
 */
export const useViewerStore = create(
  devtools(
    persist(
      (set, get) => ({
        ...initialState,

        // ============================================================
        // ACTIONS: Modelo
        // ============================================================

        /**
         * Cargar modelo desde URL
         */
        loadModel: async (url, metadata = null) => {
          set({ modelLoading: true, modelError: null });

          try {
            // La carga real se hace en el componente con useLoader
            set({
              modelUrl: url,
              modelMetadata: metadata,
              modelLoading: false,
              modelError: null,
            });
          } catch (error) {
            set({
              modelError: error.message,
              modelLoading: false,
            });
          }
        },

        /**
         * Establecer modelo cargado
         */
        setModel: (model) => {
          set({ currentModel: model, modelLoading: false });
        },

        /**
         * Limpiar modelo
         */
        clearModel: () => {
          set({
            currentModel: null,
            modelUrl: null,
            modelMetadata: null,
            selectedEntity: null,
            hoveredEntity: null,
            highlightedEntities: [],
            measurements: [],
          });
        },

        // ============================================================
        // ACTIONS: Renderizado
        // ============================================================

        /**
         * Cambiar modo de renderizado
         */
        setRenderMode: (mode) => {
          if (Object.values(RENDER_MODES).includes(mode)) {
            set({ renderMode: mode });
          }
        },

        /**
         * Toggle wireframe
         */
        toggleWireframe: () => {
          set((state) => ({ showWireframe: !state.showWireframe }));
        },

        /**
         * Toggle grid
         */
        toggleGrid: () => {
          set((state) => ({ showGrid: !state.showGrid }));
        },

        /**
         * Toggle axes
         */
        toggleAxes: () => {
          set((state) => ({ showAxes: !state.showAxes }));
        },

        /**
         * Cambiar color de fondo
         */
        setBackgroundColor: (color) => {
          set({ backgroundColor: color });
        },

        // ============================================================
        // ACTIONS: Cámara
        // ============================================================

        /**
         * Establecer posición de cámara
         */
        setCameraPosition: (position) => {
          set({ cameraPosition: position });
        },

        /**
         * Establecer target de cámara
         */
        setCameraTarget: (target) => {
          set({ cameraTarget: target });
        },

        /**
         * Cambiar FOV
         */
        setCameraFov: (fov) => {
          set({ cameraFov: Math.max(10, Math.min(120, fov)) });
        },

        /**
         * Toggle auto-rotate
         */
        toggleAutoRotate: () => {
          set((state) => ({ cameraAutoRotate: !state.cameraAutoRotate }));
        },

        /**
         * Establecer velocidad de auto-rotate
         */
        setAutoRotateSpeed: (speed) => {
          set({ cameraAutoRotateSpeed: speed });
        },

        /**
         * Reset cámara a posición inicial
         */
        resetCamera: () => {
          set({
            cameraPosition: initialState.cameraPosition,
            cameraTarget: initialState.cameraTarget,
            cameraFov: initialState.cameraFov,
            cameraAutoRotate: false,
          });
        },

        // ============================================================
        // ACTIONS: Iluminación
        // ============================================================

        /**
         * Aplicar preset de iluminación
         */
        applyLightingPreset: (preset) => {
          const presets = {
            studio: {
              ambientLightIntensity: 0.5,
              directionalLightIntensity: 1.0,
              directionalLightPosition: [10, 10, 5],
              hemisphereLight: true,
              hemisphereLightIntensity: 0.3,
            },
            outdoor: {
              ambientLightIntensity: 0.8,
              directionalLightIntensity: 1.5,
              directionalLightPosition: [20, 30, 10],
              hemisphereLight: true,
              hemisphereLightIntensity: 0.5,
            },
            soft: {
              ambientLightIntensity: 0.7,
              directionalLightIntensity: 0.5,
              directionalLightPosition: [5, 10, 5],
              hemisphereLight: true,
              hemisphereLightIntensity: 0.4,
            },
            dramatic: {
              ambientLightIntensity: 0.2,
              directionalLightIntensity: 2.0,
              directionalLightPosition: [15, 5, 10],
              hemisphereLight: false,
              hemisphereLightIntensity: 0.0,
            },
          };

          if (presets[preset]) {
            set({ ...presets[preset], lightingPreset: preset });
          }
        },

        /**
         * Establecer intensidad de luz ambiente
         */
        setAmbientLightIntensity: (intensity) => {
          set({
            ambientLightIntensity: intensity,
            lightingPreset: LIGHTING_PRESETS.CUSTOM,
          });
        },

        /**
         * Establecer intensidad de luz direccional
         */
        setDirectionalLightIntensity: (intensity) => {
          set({
            directionalLightIntensity: intensity,
            lightingPreset: LIGHTING_PRESETS.CUSTOM,
          });
        },

        /**
         * Establecer posición de luz direccional
         */
        setDirectionalLightPosition: (position) => {
          set({
            directionalLightPosition: position,
            lightingPreset: LIGHTING_PRESETS.CUSTOM,
          });
        },

        /**
         * Toggle hemisphere light
         */
        toggleHemisphereLight: () => {
          set((state) => ({
            hemisphereLight: !state.hemisphereLight,
            lightingPreset: LIGHTING_PRESETS.CUSTOM,
          }));
        },

        /**
         * Establecer intensidad de hemisphere light
         */
        setHemisphereLightIntensity: (intensity) => {
          set({
            hemisphereLightIntensity: intensity,
            lightingPreset: LIGHTING_PRESETS.CUSTOM,
          });
        },

        // ============================================================
        // ACTIONS: Selección
        // ============================================================

        /**
         * Seleccionar entidad
         */
        selectEntity: (entity) => {
          set({ selectedEntity: entity });
        },

        /**
         * Hover sobre entidad
         */
        hoverEntity: (entity) => {
          set({ hoveredEntity: entity });
        },

        /**
         * Añadir entidad a destacados
         */
        highlightEntity: (entityId) => {
          set((state) => {
            if (!state.highlightedEntities.includes(entityId)) {
              return {
                highlightedEntities: [...state.highlightedEntities, entityId],
              };
            }
            return state;
          });
        },

        /**
         * Quitar entidad de destacados
         */
        unhighlightEntity: (entityId) => {
          set((state) => ({
            highlightedEntities: state.highlightedEntities.filter(
              (id) => id !== entityId
            ),
          }));
        },

        /**
         * Limpiar selección (limpia tanto legacy como nueva API)
         */
        clearSelection: () => {
          set({
            // Legacy
            selectedEntity: null,
            hoveredEntity: null,
            // Nueva API bidireccional
            selectedEntityId: null,
            highlightedEntityId: null,
            selectedEntityData: null,
          });
        },

        /**
         * Limpiar destacados
         */
        clearHighlights: () => {
          set({ highlightedEntities: [] });
        },

        // ============================================================
        // ACTIONS: Selección Bidireccional (Nueva API)
        // ============================================================

        /**
         * Establecer entidad seleccionada por ID
         * @param {string|number|null} entityId - ID de la entidad
         */
        setSelectedEntity: (entityId) => {
          set({
            selectedEntityId: entityId,
            // Sincronizar con la API legacy
            selectedEntity: entityId ? { id: entityId } : null,
          });
        },

        /**
         * Establecer entidad destacada por ID
         * @param {string|number|null} entityId - ID de la entidad
         */
        setHighlightedEntity: (entityId) => {
          set({
            highlightedEntityId: entityId,
          });
        },

        /**
         * Establecer datos de la entidad seleccionada
         * @param {Object|null} data - Datos de la entidad desde la API
         */
        setSelectedEntityData: (data) => {
          set({ selectedEntityData: data });
        },

        /**
         * Limpiar selección bidireccional
         */
        clearSelectionBidirectional: () => {
          set({
            selectedEntityId: null,
            highlightedEntityId: null,
            selectedEntityData: null,
            // También limpiar legacy
            selectedEntity: null,
            hoveredEntity: null,
          });
        },

        // ============================================================
        // ACTIONS: Mediciones
        // ============================================================

        /**
         * Añadir medición
         */
        addMeasurement: (measurement) => {
          set((state) => ({
            measurements: [...state.measurements, measurement],
          }));
        },

        /**
         * Eliminar medición
         */
        removeMeasurement: (measurementId) => {
          set((state) => ({
            measurements: state.measurements.filter((m) => m.id !== measurementId),
          }));
        },

        /**
         * Limpiar todas las mediciones
         */
        clearMeasurements: () => {
          set({ measurements: [] });
        },

        /**
         * Toggle modo medición
         */
        toggleMeasurementMode: () => {
          set((state) => ({ measurementMode: !state.measurementMode }));
        },

        // ============================================================
        // ACTIONS: Performance
        // ============================================================

        /**
         * Toggle shadows
         */
        toggleShadows: () => {
          set((state) => ({ enableShadows: !state.enableShadows }));
        },

        /**
         * Toggle antialiasing
         */
        toggleAntialias: () => {
          set((state) => ({ enableAntialias: !state.enableAntialias }));
        },

        /**
         * Establecer pixel ratio
         */
        setPixelRatio: (ratio) => {
          set({ pixelRatio: Math.min(ratio, get().maxPixelRatio) });
        },

        // ============================================================
        // ACTIONS: UI
        // ============================================================

        /**
         * Toggle stats
         */
        toggleStats: () => {
          set((state) => ({ showStats: !state.showStats }));
        },

        /**
         * Toggle controls
         */
        toggleControls: () => {
          set((state) => ({ showControls: !state.showControls }));
        },

        /**
         * Toggle fullscreen
         */
        toggleFullscreen: () => {
          set((state) => ({ fullscreen: !state.fullscreen }));
        },

        /**
         * Reset a configuración inicial
         */
        reset: () => {
          set(initialState);
        },
      }),
      {
        name: 'viewer-storage',
        // Solo persistir configuraciones, no el modelo cargado
        partialize: (state) => ({
          renderMode: state.renderMode,
          showGrid: state.showGrid,
          showAxes: state.showAxes,
          backgroundColor: state.backgroundColor,
          cameraFov: state.cameraFov,
          lightingPreset: state.lightingPreset,
          enableShadows: state.enableShadows,
          enableAntialias: state.enableAntialias,
          showStats: state.showStats,
        }),
      }
    ),
    { name: 'ViewerStore' }
  )
);

/**
 * Selectores útiles
 */
export const selectModel = (state) => state.currentModel;
export const selectRenderMode = (state) => state.renderMode;
export const selectCameraSettings = (state) => ({
  position: state.cameraPosition,
  target: state.cameraTarget,
  fov: state.cameraFov,
  autoRotate: state.cameraAutoRotate,
  autoRotateSpeed: state.cameraAutoRotateSpeed,
});
export const selectLightingSettings = (state) => ({
  preset: state.lightingPreset,
  ambient: state.ambientLightIntensity,
  directional: state.directionalLightIntensity,
  directionalPosition: state.directionalLightPosition,
  hemisphere: state.hemisphereLight,
  hemisphereIntensity: state.hemisphereLightIntensity,
});
export const selectSelectedEntity = (state) => state.selectedEntity;
export const selectHighlightedEntities = (state) => state.highlightedEntities;

// Selectores para la nueva API bidireccional
export const selectSelectedEntityId = (state) => state.selectedEntityId;
export const selectHighlightedEntityId = (state) => state.highlightedEntityId;
export const selectSelectedEntityData = (state) => state.selectedEntityData;
