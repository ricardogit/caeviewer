/**
 * Raycasting utilities for 3D point selection
 * Used for measurement tool interaction
 */

import * as THREE from 'three';

/**
 * Inicializa raycaster para picking de puntos
 *
 * @param {THREE.Camera} camera - Cámara de la escena
 * @param {HTMLElement} domElement - Elemento DOM del renderer
 * @returns {object} Raycaster y funciones helper
 */
export function createRaycaster(camera, domElement) {
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  /**
   * Actualiza posición del mouse en coordenadas normalizadas
   */
  function updateMousePosition(event) {
    const rect = domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  }

  /**
   * Intersecta el ray con la escena
   *
   * @param {THREE.Scene} scene - Escena 3D
   * @param {boolean} recursive - Buscar recursivamente en hijos
   * @returns {Array} Array de intersecciones
   */
  function intersect(scene, recursive = true) {
    raycaster.setFromCamera(mouse, camera);
    return raycaster.intersectObjects(scene.children, recursive);
  }

  /**
   * Obtiene el punto 3D más cercano en la escena
   *
   * @param {THREE.Scene} scene - Escena 3D
   * @returns {THREE.Vector3|null} Punto 3D o null
   */
  function getIntersectionPoint(scene) {
    const intersects = intersect(scene, true);

    if (intersects.length > 0) {
      // Filtrar overlay y helpers
      const validIntersects = intersects.filter(
        i => !i.object.name.includes('Overlay') &&
             !i.object.name.includes('Helper') &&
             i.object.visible
      );

      if (validIntersects.length > 0) {
        return validIntersects[0].point.clone();
      }
    }

    return null;
  }

  /**
   * Obtiene el objeto intersectado más cercano
   *
   * @param {THREE.Scene} scene - Escena 3D
   * @returns {THREE.Object3D|null} Objeto o null
   */
  function getIntersectedObject(scene) {
    const intersects = intersect(scene, true);

    if (intersects.length > 0) {
      const validIntersects = intersects.filter(
        i => !i.object.name.includes('Overlay') &&
             !i.object.name.includes('Helper') &&
             i.object.visible
      );

      if (validIntersects.length > 0) {
        return validIntersects[0].object;
      }
    }

    return null;
  }

  /**
   * Obtiene información detallada de la intersección
   *
   * @param {THREE.Scene} scene - Escena 3D
   * @returns {object|null} Info de intersección o null
   */
  function getIntersectionInfo(scene) {
    const intersects = intersect(scene, true);

    if (intersects.length > 0) {
      const validIntersects = intersects.filter(
        i => !i.object.name.includes('Overlay') &&
             !i.object.name.includes('Helper') &&
             i.object.visible
      );

      if (validIntersects.length > 0) {
        const intersection = validIntersects[0];

        return {
          point: intersection.point.clone(),
          normal: intersection.face ? intersection.face.normal.clone() : null,
          distance: intersection.distance,
          object: intersection.object,
          uv: intersection.uv,
          faceIndex: intersection.faceIndex
        };
      }
    }

    return null;
  }

  return {
    raycaster,
    mouse,
    updateMousePosition,
    intersect,
    getIntersectionPoint,
    getIntersectedObject,
    getIntersectionInfo
  };
}

/**
 * Crea un marcador visual para puntos seleccionados
 *
 * @param {THREE.Vector3} position - Posición del marcador
 * @param {number} color - Color del marcador (hex)
 * @returns {THREE.Mesh} Marcador mesh
 */
export function createPointMarker(position, color = 0xff0000) {
  const geometry = new THREE.SphereGeometry(0.5, 16, 16);
  const material = new THREE.MeshBasicMaterial({
    color: color,
    depthTest: false,
    depthWrite: false
  });

  const marker = new THREE.Mesh(geometry, material);
  marker.position.copy(position);
  marker.renderOrder = 1000;
  marker.name = 'PointMarker';

  return marker;
}

/**
 * Crea un marcador de hover para feedback visual
 *
 * @param {THREE.Vector3} position - Posición del marcador
 * @returns {THREE.Mesh} Marcador mesh
 */
export function createHoverMarker(position) {
  const geometry = new THREE.SphereGeometry(0.3, 16, 16);
  const material = new THREE.MeshBasicMaterial({
    color: 0xffff00,
    opacity: 0.7,
    transparent: true,
    depthTest: false,
    depthWrite: false
  });

  const marker = new THREE.Mesh(geometry, material);
  marker.position.copy(position);
  marker.renderOrder = 999;
  marker.name = 'HoverMarker';

  return marker;
}

/**
 * Calcula el punto en un plano dado el ray
 *
 * @param {THREE.Raycaster} raycaster - Raycaster configurado
 * @param {THREE.Plane} plane - Plano de intersección
 * @returns {THREE.Vector3|null} Punto de intersección o null
 */
export function rayIntersectPlane(raycaster, plane) {
  const target = new THREE.Vector3();
  const intersection = raycaster.ray.intersectPlane(plane, target);

  return intersection;
}

/**
 * Snapping a grid para coordenadas
 *
 * @param {THREE.Vector3} point - Punto original
 * @param {number} gridSize - Tamaño del grid
 * @returns {THREE.Vector3} Punto snapeado
 */
export function snapToGrid(point, gridSize = 1.0) {
  return new THREE.Vector3(
    Math.round(point.x / gridSize) * gridSize,
    Math.round(point.y / gridSize) * gridSize,
    Math.round(point.z / gridSize) * gridSize
  );
}

/**
 * Calcula distancia de punto a plano
 *
 * @param {THREE.Vector3} point - Punto
 * @param {THREE.Plane} plane - Plano
 * @returns {number} Distancia
 */
export function distanceToPlane(point, plane) {
  return Math.abs(plane.distanceToPoint(point));
}
