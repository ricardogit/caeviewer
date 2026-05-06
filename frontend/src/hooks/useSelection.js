/**
 * useSelection Hook
 * =================
 *
 * Hook para manejo de selección bidireccional entre el modelo 3D y el grafo de entidades.
 *
 * Features:
 * - Selección sincronizada entre 3D viewer y grafo
 * - Highlight temporal de entidades
 * - Estado compartido vía Zustand store
 * - Fetch de información de entidad desde API
 *
 * @module hooks/useSelection
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import axios from 'axios';
import { useViewerStore } from '../stores/viewerStore';

/**
 * Hook principal para manejo de selección de entidades
 *
 * @param {Object} options - Opciones de configuración
 * @param {Function} options.onSelectionChange - Callback cuando cambia la selección
 * @param {Function} options.onHighlight - Callback cuando se hace highlight
 * @param {boolean} options.autoFetch - Fetch automático de datos de entidad (default: true)
 *
 * @returns {Object} - API de selección
 */
export function useSelection({
  onSelectionChange,
  onHighlight,
  autoFetch = true,
} = {}) {
  // Estado local
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [entityData, setEntityData] = useState(null);

  // Store de Zustand
  const {
    selectedEntityId,
    highlightedEntityId,
    selectedEntityData,
    setSelectedEntity,
    setHighlightedEntity,
    clearSelection: clearSelectionStore,
  } = useViewerStore();

  // Ref para evitar loops infinitos
  const isSelectingRef = useRef(false);

  /**
   * Fetch de información de entidad desde API
   */
  const fetchEntityData = useCallback(async (entityId) => {
    if (!entityId) return null;

    setLoading(true);
    setError(null);

    try {
      const response = await axios.get(`/api/geometry/entity/${entityId}`);
      const data = response.data;

      // Guardar en store
      useViewerStore.getState().setSelectedEntityData(data);
      setEntityData(data);

      return data;
    } catch (err) {
      console.error('Error fetching entity data:', err);
      const errorMessage = err.response?.data?.error || err.message || 'Failed to fetch entity data';
      setError(errorMessage);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Seleccionar una entidad
   *
   * @param {string|number} entityId - ID de la entidad a seleccionar
   * @param {Object} options - Opciones adicionales
   * @param {string} options.source - Fuente de la selección ('3d', 'graph', 'properties')
   * @param {boolean} options.skipFetch - Saltar fetch de datos
   * @param {Object} options.metadata - Metadata adicional
   */
  const selectEntity = useCallback(async (entityId, options = {}) => {
    const { source = 'unknown', skipFetch = false, metadata = {} } = options;

    // Evitar loops
    if (isSelectingRef.current) return;
    isSelectingRef.current = true;

    try {
      console.log(`Selecting entity ${entityId} from ${source}`);

      // Actualizar store
      setSelectedEntity(entityId);

      // Fetch datos si es necesario
      let data = null;
      if (autoFetch && !skipFetch && entityId) {
        data = await fetchEntityData(entityId);
      }

      // Callback
      if (onSelectionChange) {
        onSelectionChange({
          entityId,
          source,
          metadata,
          data,
        });
      }
    } finally {
      isSelectingRef.current = false;
    }
  }, [autoFetch, fetchEntityData, onSelectionChange, setSelectedEntity]);

  /**
   * Highlight temporal de entidad
   *
   * @param {string|number} entityId - ID de la entidad a highlight
   * @param {Object} options - Opciones adicionales
   * @param {number} options.duration - Duración en ms (0 = permanente)
   * @param {string} options.source - Fuente del highlight
   */
  const highlightEntity = useCallback((entityId, options = {}) => {
    const { duration = 0, source = 'unknown' } = options;

    console.log(`Highlighting entity ${entityId} from ${source}`);

    // Actualizar store
    setHighlightedEntity(entityId);

    // Callback
    if (onHighlight) {
      onHighlight({
        entityId,
        source,
        duration,
      });
    }

    // Auto-clear después de duración
    if (duration > 0 && entityId) {
      setTimeout(() => {
        setHighlightedEntity(null);
      }, duration);
    }
  }, [onHighlight, setHighlightedEntity]);

  /**
   * Limpiar selección
   */
  const clearSelection = useCallback(() => {
    console.log('Clearing selection');

    clearSelectionStore();
    setEntityData(null);
    setError(null);

    if (onSelectionChange) {
      onSelectionChange({
        entityId: null,
        source: 'clear',
        metadata: {},
        data: null,
      });
    }
  }, [clearSelectionStore, onSelectionChange]);

  /**
   * Seleccionar múltiples entidades
   *
   * @param {Array<string|number>} entityIds - IDs de entidades
   * @param {Object} options - Opciones
   */
  const selectMultiple = useCallback((entityIds, options = {}) => {
    // Por ahora solo soportamos selección única
    // Seleccionar la primera
    if (entityIds && entityIds.length > 0) {
      selectEntity(entityIds[0], options);
    }
  }, [selectEntity]);

  /**
   * Toggle de selección
   *
   * @param {string|number} entityId - ID de la entidad
   * @param {Object} options - Opciones
   */
  const toggleSelection = useCallback((entityId, options = {}) => {
    if (selectedEntityId === entityId) {
      clearSelection();
    } else {
      selectEntity(entityId, options);
    }
  }, [selectedEntityId, clearSelection, selectEntity]);

  /**
   * Navegar a entidad relacionada
   *
   * @param {string|number} entityId - ID de la entidad relacionada
   * @param {string} relationType - Tipo de relación ('reference', 'referenced_by')
   */
  const navigateToRelated = useCallback((entityId, relationType) => {
    selectEntity(entityId, {
      source: 'navigation',
      metadata: { relationType },
    });
  }, [selectEntity]);

  /**
   * Refresh de datos de entidad actual
   */
  const refreshEntityData = useCallback(async () => {
    if (selectedEntityId) {
      return await fetchEntityData(selectedEntityId);
    }
    return null;
  }, [selectedEntityId, fetchEntityData]);

  return {
    // Estado
    selectedEntityId,
    highlightedEntityId,
    entityData: entityData || selectedEntityData,
    loading,
    error,
    isSelected: (entityId) => selectedEntityId === entityId,
    isHighlighted: (entityId) => highlightedEntityId === entityId,

    // Acciones
    selectEntity,
    highlightEntity,
    clearSelection,
    selectMultiple,
    toggleSelection,
    navigateToRelated,
    refreshEntityData,
  };
}

/**
 * Hook simplificado para verificar si una entidad está seleccionada
 *
 * @param {string|number} entityId - ID de la entidad
 * @returns {boolean} - True si está seleccionada
 */
export function useIsSelected(entityId) {
  const selectedEntityId = useViewerStore((state) => state.selectedEntityId);
  return selectedEntityId === entityId;
}

/**
 * Hook simplificado para verificar si una entidad está highlighted
 *
 * @param {string|number} entityId - ID de la entidad
 * @returns {boolean} - True si está highlighted
 */
export function useIsHighlighted(entityId) {
  const highlightedEntityId = useViewerStore((state) => state.highlightedEntityId);
  return highlightedEntityId === entityId;
}

/**
 * Hook para obtener datos de la entidad seleccionada
 *
 * @returns {Object|null} - Datos de la entidad o null
 */
export function useSelectedEntityData() {
  return useViewerStore((state) => state.selectedEntityData);
}

/**
 * Hook para manejo de selección en el grafo
 *
 * @param {Object} cytoscapeInstance - Instancia de Cytoscape
 */
export function useGraphSelection(cytoscapeInstance) {
  const { selectEntity, highlightEntity } = useSelection({
    source: 'graph',
  });

  useEffect(() => {
    if (!cytoscapeInstance) return;

    // Handler para selección de nodo
    const handleNodeTap = (event) => {
      const node = event.target;
      const entityId = node.data('id');

      if (entityId) {
        selectEntity(entityId, {
          source: 'graph',
          metadata: {
            nodeType: node.data('type'),
            nodeLabel: node.data('label'),
          },
        });
      }
    };

    // Handler para hover
    const handleNodeMouseOver = (event) => {
      const node = event.target;
      const entityId = node.data('id');

      if (entityId) {
        highlightEntity(entityId, {
          source: 'graph',
          duration: 0, // Permanente hasta mouseout
        });
      }
    };

    const handleNodeMouseOut = () => {
      highlightEntity(null, { source: 'graph' });
    };

    // Registrar event listeners
    cytoscapeInstance.on('tap', 'node', handleNodeTap);
    cytoscapeInstance.on('mouseover', 'node', handleNodeMouseOver);
    cytoscapeInstance.on('mouseout', 'node', handleNodeMouseOut);

    // Cleanup
    return () => {
      cytoscapeInstance.off('tap', 'node', handleNodeTap);
      cytoscapeInstance.off('mouseover', 'node', handleNodeMouseOver);
      cytoscapeInstance.off('mouseout', 'node', handleNodeMouseOut);
    };
  }, [cytoscapeInstance, selectEntity, highlightEntity]);
}

/**
 * Hook para manejo de selección en el viewer 3D
 *
 * @param {Function} onMeshClick - Callback cuando se hace click en mesh
 */
export function use3DSelection(onMeshClick) {
  const { selectEntity, highlightEntity } = useSelection({
    source: '3d',
  });

  const handleMeshClick = useCallback((mesh) => {
    // Extraer entity ID del mesh
    const entityId = mesh.userData?.entityId || mesh.name;

    if (entityId) {
      selectEntity(entityId, {
        source: '3d',
        metadata: {
          meshName: mesh.name,
          meshType: mesh.type,
          position: mesh.position.toArray(),
        },
      });
    }

    if (onMeshClick) {
      onMeshClick(mesh);
    }
  }, [selectEntity, onMeshClick]);

  const handleMeshHover = useCallback((mesh) => {
    const entityId = mesh?.userData?.entityId || mesh?.name;

    if (entityId) {
      highlightEntity(entityId, {
        source: '3d',
        duration: 0,
      });
    }
  }, [highlightEntity]);

  const handleMeshUnhover = useCallback(() => {
    highlightEntity(null, { source: '3d' });
  }, [highlightEntity]);

  return {
    handleMeshClick,
    handleMeshHover,
    handleMeshUnhover,
  };
}

export default useSelection;
