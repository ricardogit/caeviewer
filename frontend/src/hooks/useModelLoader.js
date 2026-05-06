/**
 * useModelLoader Hook
 * ===================
 *
 * Hook personalizado para cargar modelos GLB/GLTF desde la API.
 * Gestiona el estado de carga, errores y cache de modelos.
 *
 * @module hooks/useModelLoader
 */

import { useState, useEffect, useCallback } from 'react';
import { useLoader } from '@react-three/fiber';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader';
import { useViewerStore } from '../stores/viewerStore';
import { configureDracoLoader } from '../config/draco';
import axios from 'axios';

/**
 * Cache de modelos en memoria
 */
const modelCache = new Map();

/**
 * Hook para cargar modelo GLB desde la API
 *
 * @param {string} modelId - ID del modelo a cargar
 * @param {object} options - Opciones de carga
 * @returns {object} Estado y funciones de carga
 *
 * @example
 * const { model, loading, error, reload } = useModelLoader('model-123');
 */
export function useModelLoader(modelId, options = {}) {
  const {
    enableCache = true,
    enableDraco = true,
    onProgress = null,
    onLoad = null,
    onError = null,
  } = options;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(0);
  const [model, setModel] = useState(null);
  const [metadata, setMetadata] = useState(null);

  const setModelInStore = useViewerStore((state) => state.setModel);

  /**
   * Cargar modelo desde la API
   */
  const loadModel = useCallback(async () => {
    if (!modelId) {
      setError('No model ID provided');
      return;
    }

    // Verificar cache
    if (enableCache && modelCache.has(modelId)) {
      const cached = modelCache.get(modelId);
      setModel(cached.model);
      setMetadata(cached.metadata);
      setModelInStore(cached.model);
      onLoad?.(cached.model);
      return;
    }

    setLoading(true);
    setError(null);
    setProgress(0);

    try {
      // 1. Obtener metadata del modelo
      const metadataResponse = await axios.get(
        `/api/step-view/viewer/model/${modelId}/metadata`
      );
      const modelMetadata = metadataResponse.data;
      setMetadata(modelMetadata);

      // 2. Construir URL del GLB
      const glbUrl = `/api/step-view/viewer/model/${modelId}/glb`;

      // 3. Configurar GLTF Loader
      const loader = new GLTFLoader();

      // Configurar Draco si está habilitado
      if (enableDraco) {
        const dracoLoader = new DRACOLoader();
        configureDracoLoader(dracoLoader);
        loader.setDRACOLoader(dracoLoader);
      }

      // 4. Cargar modelo
      loader.load(
        glbUrl,
        // onLoad
        (gltf) => {
          setModel(gltf);
          setModelInStore(gltf);
          setLoading(false);
          setProgress(100);

          // Guardar en cache
          if (enableCache) {
            modelCache.set(modelId, {
              model: gltf,
              metadata: modelMetadata,
            });
          }

          onLoad?.(gltf);
        },
        // onProgress
        (xhr) => {
          if (xhr.lengthComputable) {
            const percentComplete = (xhr.loaded / xhr.total) * 100;
            setProgress(percentComplete);
            onProgress?.(percentComplete);
          }
        },
        // onError
        (err) => {
          console.error('Error loading model:', err);
          setError(err.message || 'Failed to load model');
          setLoading(false);
          onError?.(err);
        }
      );
    } catch (err) {
      console.error('Error fetching model metadata:', err);
      setError(err.message || 'Failed to fetch model metadata');
      setLoading(false);
      onError?.(err);
    }
  }, [modelId, enableCache, enableDraco, onProgress, onLoad, onError, setModelInStore]);

  /**
   * Recargar modelo (ignora cache)
   */
  const reload = useCallback(() => {
    if (enableCache && modelId) {
      modelCache.delete(modelId);
    }
    loadModel();
  }, [modelId, enableCache, loadModel]);

  /**
   * Limpiar modelo
   */
  const clear = useCallback(() => {
    setModel(null);
    setMetadata(null);
    setError(null);
    setProgress(0);
    setModelInStore(null);
  }, [setModelInStore]);

  // Cargar modelo cuando cambia el ID
  useEffect(() => {
    if (modelId) {
      loadModel();
    }

    return () => {
      // Cleanup si es necesario
    };
  }, [modelId, loadModel]);

  return {
    model,
    metadata,
    loading,
    error,
    progress,
    reload,
    clear,
  };
}

/**
 * Hook para cargar modelo desde URL directa
 *
 * @param {string} url - URL del archivo GLB/GLTF
 * @param {object} options - Opciones de carga
 * @returns {object} Estado de carga
 *
 * @example
 * const { scene, loading, error } = useModelFromUrl('/models/part.glb');
 */
export function useModelFromUrl(url, options = {}) {
  const { enableDraco = true } = options;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  try {
    // Usar el loader de R3F
    const gltf = useLoader(
      GLTFLoader,
      url,
      (loader) => {
        if (enableDraco) {
          const dracoLoader = new DRACOLoader();
          configureDracoLoader(dracoLoader);
          loader.setDRACOLoader(dracoLoader);
        }
      }
    );

    setLoading(false);

    return {
      scene: gltf.scene,
      gltf,
      loading: false,
      error: null,
    };
  } catch (err) {
    setError(err);
    setLoading(false);

    return {
      scene: null,
      gltf: null,
      loading: false,
      error: err,
    };
  }
}

/**
 * Hook para precarga de múltiples modelos
 *
 * @param {Array<string>} modelIds - Array de IDs de modelos
 * @returns {object} Estado de precarga
 *
 * @example
 * const { loaded, total, progress } = usePreloadModels(['model-1', 'model-2']);
 */
export function usePreloadModels(modelIds = []) {
  const [loaded, setLoaded] = useState(0);
  const [total, setTotal] = useState(modelIds.length);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (modelIds.length === 0) return;

    setTotal(modelIds.length);
    setLoaded(0);

    let loadedCount = 0;

    const loadPromises = modelIds.map(async (modelId) => {
      try {
        // Verificar si ya está en cache
        if (modelCache.has(modelId)) {
          loadedCount++;
          setLoaded(loadedCount);
          setProgress((loadedCount / modelIds.length) * 100);
          return;
        }

        // Cargar modelo
        const glbUrl = `/api/step-view/viewer/model/${modelId}/glb`;
        const loader = new GLTFLoader();

        await new Promise((resolve, reject) => {
          loader.load(
            glbUrl,
            (gltf) => {
              modelCache.set(modelId, { model: gltf, metadata: null });
              loadedCount++;
              setLoaded(loadedCount);
              setProgress((loadedCount / modelIds.length) * 100);
              resolve(gltf);
            },
            undefined,
            reject
          );
        });
      } catch (err) {
        console.error(`Error preloading model ${modelId}:`, err);
      }
    });

    Promise.all(loadPromises);
  }, [modelIds]);

  return {
    loaded,
    total,
    progress,
    isComplete: loaded === total,
  };
}

/**
 * Hook para obtener información del modelo sin cargarlo
 *
 * @param {string} modelId - ID del modelo
 * @returns {object} Metadata del modelo
 *
 * @example
 * const { metadata, loading, error } = useModelMetadata('model-123');
 */
export function useModelMetadata(modelId) {
  const [metadata, setMetadata] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!modelId) return;

    setLoading(true);
    setError(null);

    axios
      .get(`/api/step-view/viewer/model/${modelId}/metadata`)
      .then((response) => {
        setMetadata(response.data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [modelId]);

  return { metadata, loading, error };
}

/**
 * Limpiar cache de modelos
 */
export function clearModelCache() {
  modelCache.clear();
}

/**
 * Obtener tamaño del cache
 */
export function getModelCacheSize() {
  return modelCache.size;
}

/**
 * Verificar si un modelo está en cache
 */
export function isModelCached(modelId) {
  return modelCache.has(modelId);
}
