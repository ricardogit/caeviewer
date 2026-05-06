import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { CSS2DRenderer, CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer';

/**
 * MeasurementOverlay - Renderiza mediciones 3D en la escena
 *
 * Props:
 * - scene: THREE.Scene
 * - camera: THREE.Camera
 * - measurements: Array de mediciones
 * - container: DOM element container
 */
export default function MeasurementOverlay({ scene, camera, measurements, container }) {
  const overlayGroupRef = useRef(null);
  const labelRendererRef = useRef(null);

  useEffect(() => {
    if (!scene || !camera || !container) return;

    // Crear grupo para las mediciones
    if (!overlayGroupRef.current) {
      overlayGroupRef.current = new THREE.Group();
      overlayGroupRef.current.name = 'MeasurementOverlay';
      scene.add(overlayGroupRef.current);
    }

    // Crear CSS2D renderer para labels
    if (!labelRendererRef.current) {
      labelRendererRef.current = new CSS2DRenderer();
      labelRendererRef.current.setSize(container.clientWidth, container.clientHeight);
      labelRendererRef.current.domElement.style.position = 'absolute';
      labelRendererRef.current.domElement.style.top = '0';
      labelRendererRef.current.domElement.style.pointerEvents = 'none';
      container.appendChild(labelRendererRef.current.domElement);
    }

    // Limpiar overlay
    clearOverlay();

    // Renderizar cada medición
    measurements.forEach((measurement, idx) => {
      renderMeasurement(measurement, idx);
    });

    // Cleanup
    return () => {
      if (labelRendererRef.current && container.contains(labelRendererRef.current.domElement)) {
        container.removeChild(labelRendererRef.current.domElement);
      }
    };
  }, [scene, camera, measurements, container]);

  function clearOverlay() {
    if (!overlayGroupRef.current) return;

    // Remover todos los objetos del grupo
    while (overlayGroupRef.current.children.length > 0) {
      const child = overlayGroupRef.current.children[0];
      overlayGroupRef.current.remove(child);

      // Limpiar geometrías y materiales
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        if (Array.isArray(child.material)) {
          child.material.forEach(m => m.dispose());
        } else {
          child.material.dispose();
        }
      }
    }
  }

  function renderMeasurement(measurement, idx) {
    const type = measurement.type || measurement.measurement_type;

    if (type === 'distance' || type === 'DISTANCE') {
      renderDistanceMeasurement(measurement, idx);
    } else if (type === 'angle' || type === 'ANGLE') {
      renderAngleMeasurement(measurement, idx);
    } else if (type === 'bbox' || type === 'BBOX') {
      renderBoundingBox(measurement, idx);
    } else if (type === 'area' || type === 'AREA') {
      renderAreaMeasurement(measurement, idx);
    } else if (type === 'volume' || type === 'VOLUME') {
      renderVolumeMeasurement(measurement, idx);
    }
  }

  function renderDistanceMeasurement(measurement, idx) {
    const points = measurement.points || [];
    if (points.length < 2) return;

    const p1 = new THREE.Vector3(...points[0]);
    const p2 = new THREE.Vector3(...points[1]);

    // Línea entre puntos
    const geometry = new THREE.BufferGeometry().setFromPoints([p1, p2]);
    const material = new THREE.LineBasicMaterial({
      color: 0xff0000,
      linewidth: 2,
      depthTest: false,
      depthWrite: false
    });
    const line = new THREE.Line(geometry, material);
    line.renderOrder = 999;
    overlayGroupRef.current.add(line);

    // Esferas en los puntos
    const sphereGeometry = new THREE.SphereGeometry(0.5, 16, 16);
    const sphereMaterial = new THREE.MeshBasicMaterial({
      color: 0xff0000,
      depthTest: false,
      depthWrite: false
    });

    const sphere1 = new THREE.Mesh(sphereGeometry, sphereMaterial);
    sphere1.position.copy(p1);
    sphere1.renderOrder = 1000;
    overlayGroupRef.current.add(sphere1);

    const sphere2 = new THREE.Mesh(sphereGeometry, sphereMaterial.clone());
    sphere2.position.copy(p2);
    sphere2.renderOrder = 1000;
    overlayGroupRef.current.add(sphere2);

    // Label en el punto medio
    const midpoint = new THREE.Vector3().addVectors(p1, p2).multiplyScalar(0.5);
    const label = createLabel(
      `${measurement.value.toFixed(2)} ${measurement.unit || 'mm'}`,
      '#ff0000'
    );
    label.position.copy(midpoint);
    overlayGroupRef.current.add(label);
  }

  function renderAngleMeasurement(measurement, idx) {
    const vectors = measurement.vectors || [];
    if (vectors.length < 2) return;

    const v1 = new THREE.Vector3(...vectors[0]);
    const v2 = new THREE.Vector3(...vectors[1]);
    const origin = new THREE.Vector3(0, 0, 0);

    // Normalizar vectores para visualización
    v1.normalize().multiplyScalar(10);
    v2.normalize().multiplyScalar(10);

    // Líneas de vectores
    const geo1 = new THREE.BufferGeometry().setFromPoints([origin, v1]);
    const geo2 = new THREE.BufferGeometry().setFromPoints([origin, v2]);

    const material = new THREE.LineBasicMaterial({
      color: 0x00ff00,
      linewidth: 2,
      depthTest: false,
      depthWrite: false
    });

    const line1 = new THREE.Line(geo1, material);
    const line2 = new THREE.Line(geo2, material.clone());

    line1.renderOrder = 999;
    line2.renderOrder = 999;

    overlayGroupRef.current.add(line1);
    overlayGroupRef.current.add(line2);

    // Arco entre vectores
    const angle = v1.angleTo(v2);
    const arcGeometry = new THREE.BufferGeometry();
    const arcPoints = [];
    const radius = 5;
    const segments = 32;

    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      const currentAngle = t * angle;

      const quaternion = new THREE.Quaternion();
      quaternion.setFromAxisAngle(
        new THREE.Vector3().crossVectors(v1, v2).normalize(),
        currentAngle
      );

      const point = v1.clone().normalize().multiplyScalar(radius);
      point.applyQuaternion(quaternion);
      arcPoints.push(point);
    }

    arcGeometry.setFromPoints(arcPoints);
    const arcLine = new THREE.Line(arcGeometry, material.clone());
    arcLine.renderOrder = 999;
    overlayGroupRef.current.add(arcLine);

    // Label
    const labelPos = v1.clone().add(v2).multiplyScalar(0.5).normalize().multiplyScalar(7);
    const label = createLabel(
      `${measurement.value.toFixed(1)}°`,
      '#00ff00'
    );
    label.position.copy(labelPos);
    overlayGroupRef.current.add(label);
  }

  function renderBoundingBox(measurement, idx) {
    const min = measurement.min || [0, 0, 0];
    const max = measurement.max || [0, 0, 0];

    const box = new THREE.Box3(
      new THREE.Vector3(...min),
      new THREE.Vector3(...max)
    );

    const helper = new THREE.Box3Helper(box, 0x0000ff);
    helper.renderOrder = 999;
    overlayGroupRef.current.add(helper);

    // Label con dimensiones
    const center = new THREE.Vector3(...measurement.center || [0, 0, 0]);
    const dims = measurement.dimensions || [0, 0, 0];
    const label = createLabel(
      `${dims[0].toFixed(1)} × ${dims[1].toFixed(1)} × ${dims[2].toFixed(1)} mm`,
      '#0000ff'
    );
    label.position.copy(center);
    overlayGroupRef.current.add(label);
  }

  function renderAreaMeasurement(measurement, idx) {
    // Renderizar como un ícono simple
    const label = createLabel(
      `Area: ${measurement.value.toFixed(2)} ${measurement.unit}`,
      '#00aa00'
    );
    label.position.set(0, 0, 0);
    overlayGroupRef.current.add(label);
  }

  function renderVolumeMeasurement(measurement, idx) {
    // Renderizar como un ícono simple
    const label = createLabel(
      `Volume: ${measurement.value.toFixed(2)} ${measurement.unit}`,
      '#aa8800'
    );
    label.position.set(0, 0, 0);
    overlayGroupRef.current.add(label);
  }

  function createLabel(text, color) {
    const div = document.createElement('div');
    div.className = 'measurement-label';
    div.textContent = text;
    div.style.color = color;
    div.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
    div.style.padding = '4px 8px';
    div.style.borderRadius = '4px';
    div.style.fontSize = '12px';
    div.style.fontWeight = 'bold';
    div.style.border = `2px solid ${color}`;
    div.style.whiteSpace = 'nowrap';

    const label = new CSS2DObject(div);
    return label;
  }

  // Este componente no renderiza nada en React DOM
  // Todo se renderiza en Three.js
  return null;
}

// Helper hook para integrar con el render loop de Three.js
export function useMeasurementOverlayRender(labelRenderer, camera) {
  useEffect(() => {
    if (!labelRenderer || !camera) return;

    function animate() {
      if (labelRenderer) {
        labelRenderer.render(scene, camera);
      }
    }

    // Este hook debe llamarse en el loop de animación del viewer
    return animate;
  }, [labelRenderer, camera]);
}
