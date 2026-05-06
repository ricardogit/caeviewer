/**
 * Scene3D Component
 * =================
 *
 * Componente que renderiza la escena 3D incluyendo:
 * - Modelo GLB cargado
 * - Iluminación
 * - Grid y ejes de referencia
 * - Efectos de post-procesamiento
 *
 * @module components/Scene3D
 */

import React, { useRef, useEffect, useMemo } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import {
  Grid,
  GizmoHelper,
  GizmoViewport,
  Environment,
  ContactShadows,
  BakeShadows,
  MeshReflectorMaterial,
  useHelper,
} from '@react-three/drei';
import * as THREE from 'three';

import { useViewerStore, RENDER_MODES } from '../stores/viewerStore';

/**
 * Componente del modelo 3D
 */
function Model({ gltf, renderMode }) {
  const groupRef = useRef();
  const { scene: threeScene } = useThree();

  // Centrar y escalar modelo
  useEffect(() => {
    if (!gltf || !groupRef.current) return;

    const box = new THREE.Box3().setFromObject(groupRef.current);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());

    // Centrar
    groupRef.current.position.x = -center.x;
    groupRef.current.position.y = -center.y;
    groupRef.current.position.z = -center.z;

    // Escalar para que quepa en vista
    const maxDim = Math.max(size.x, size.y, size.z);
    const scale = 5 / maxDim;
    groupRef.current.scale.setScalar(scale);
  }, [gltf]);

  // Aplicar modo de renderizado
  useEffect(() => {
    if (!gltf || !gltf.scene) return;

    gltf.scene.traverse((child) => {
      if (child && child.isMesh) {
        // Guardar material original
        if (child.material && !child.userData.originalMaterial) {
          child.userData.originalMaterial = child.material.clone();
        }

        switch (renderMode) {
          case RENDER_MODES.WIREFRAME:
            if (child.material) {
              child.material = new THREE.MeshBasicMaterial({
                color: 0x00ff00,
                wireframe: true,
              });
            }
            break;

          case RENDER_MODES.XRAY:
            if (child.material) {
              child.material = new THREE.MeshPhysicalMaterial({
                color: 0x00aaff,
                transparent: true,
                opacity: 0.3,
                side: THREE.DoubleSide,
                depthWrite: false,
              });
            }
            break;

          case RENDER_MODES.NORMALS:
            if (child.material) {
              child.material = new THREE.MeshNormalMaterial();
            }
            break;

          case RENDER_MODES.DEPTH:
            if (child.material) {
              child.material = new THREE.MeshDepthMaterial();
            }
            break;

          case RENDER_MODES.MATCAP:
            if (child.material) {
              child.material = new THREE.MeshMatcapMaterial({
                color: 0xffffff,
              });
            }
            break;

          case RENDER_MODES.REALISTIC:
          default:
            // Restaurar material original con mejoras
            if (child.userData.originalMaterial) {
              child.material = child.userData.originalMaterial.clone();
              if (child.material) {
                child.material.roughness = 0.5;
                child.material.metalness = 0.2;
                child.castShadow = true;
                child.receiveShadow = true;
              }
            }
            break;
        }
      }
    });
  }, [gltf, renderMode]);

  if (!gltf) return null;

  return (
    <group ref={groupRef}>
      <primitive object={gltf.scene} />
    </group>
  );
}

/**
 * Componente de iluminación
 */
function Lighting() {
  const {
    ambientLightIntensity,
    directionalLightIntensity,
    directionalLightPosition,
    hemisphereLight,
    hemisphereLightIntensity,
    hemisphereLightSkyColor,
    hemisphereLightGroundColor,
    enableShadows,
  } = useViewerStore();

  const directionalLightRef = useRef();

  // Helper para debug (opcional)
  // useHelper(directionalLightRef, THREE.DirectionalLightHelper, 1);

  return (
    <>
      {/* Luz Ambiente */}
      <ambientLight intensity={ambientLightIntensity} />

      {/* Luz Direccional (sol) */}
      <directionalLight
        ref={directionalLightRef}
        position={directionalLightPosition}
        intensity={directionalLightIntensity}
        castShadow={enableShadows}
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-far={50}
        shadow-camera-left={-10}
        shadow-camera-right={10}
        shadow-camera-top={10}
        shadow-camera-bottom={-10}
      />

      {/* Luz Hemisférica (cielo/suelo) */}
      {hemisphereLight && (
        <hemisphereLight
          skyColor={hemisphereLightSkyColor}
          groundColor={hemisphereLightGroundColor}
          intensity={hemisphereLightIntensity}
        />
      )}

      {/* Luz de relleno */}
      <pointLight position={[-10, 5, -10]} intensity={0.3} />
      <pointLight position={[10, 5, 10]} intensity={0.3} />
    </>
  );
}

/**
 * Grid de referencia
 */
function ReferenceGrid({ show }) {
  if (!show) return null;

  return (
    <>
      <Grid
        args={[20, 20]}
        cellSize={1}
        cellThickness={0.5}
        cellColor="#6e6e6e"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#9d9d9d"
        fadeDistance={30}
        fadeStrength={1}
        followCamera={false}
        infiniteGrid={true}
      />
    </>
  );
}

/**
 * Ejes de coordenadas
 */
function CoordinateAxes({ show }) {
  if (!show) return null;

  return (
    <GizmoHelper alignment="bottom-right" margin={[80, 80]}>
      <GizmoViewport
        axisColors={['red', 'green', 'blue']}
        labelColor="white"
      />
    </GizmoHelper>
  );
}

/**
 * Sombras de contacto
 */
function Shadows({ enabled }) {
  if (!enabled) return null;

  return (
    <ContactShadows
      position={[0, -0.01, 0]}
      opacity={0.5}
      scale={20}
      blur={2}
      far={10}
    />
  );
}

/**
 * Plano reflectante (opcional)
 */
function ReflectivePlane({ show }) {
  if (!show) return null;

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]} receiveShadow>
      <planeGeometry args={[50, 50]} />
      <MeshReflectorMaterial
        blur={[300, 100]}
        resolution={2048}
        mixBlur={1}
        mixStrength={40}
        roughness={1}
        depthScale={1.2}
        minDepthThreshold={0.4}
        maxDepthThreshold={1.4}
        color="#101010"
        metalness={0.5}
      />
    </mesh>
  );
}

/**
 * Componente Scene3D principal
 */
export default function Scene3D({ model, showGrid, showAxes }) {
  const { renderMode, enableShadows, backgroundColor } = useViewerStore();
  const { scene } = useThree();

  // Actualizar color de fondo
  useEffect(() => {
    scene.background = new THREE.Color(backgroundColor);
  }, [backgroundColor, scene]);

  return (
    <>
      {/* Iluminación */}
      <Lighting />

      {/* Grid de referencia */}
      <ReferenceGrid show={showGrid} />

      {/* Ejes de coordenadas */}
      <CoordinateAxes show={showAxes} />

      {/* Sombras de contacto */}
      <Shadows enabled={enableShadows} />

      {/* Modelo 3D */}
      {model && <Model gltf={model} renderMode={renderMode} />}

      {/* Environment (HDRI opcional) */}
      {renderMode === RENDER_MODES.REALISTIC && (
        <Environment preset="studio" />
      )}
    </>
  );
}

/**
 * Componente auxiliar para selección
 */
export function SelectableModel({ gltf, onSelect, onHover }) {
  const [hovered, setHovered] = React.useState(false);
  const groupRef = useRef();

  useEffect(() => {
    if (hovered) {
      document.body.style.cursor = 'pointer';
    } else {
      document.body.style.cursor = 'default';
    }
  }, [hovered]);

  const handlePointerOver = (event) => {
    event.stopPropagation();
    setHovered(true);
    onHover?.(event.object);
  };

  const handlePointerOut = (event) => {
    event.stopPropagation();
    setHovered(false);
    onHover?.(null);
  };

  const handleClick = (event) => {
    event.stopPropagation();
    onSelect?.(event.object);
  };

  if (!gltf) return null;

  return (
    <group
      ref={groupRef}
      onPointerOver={handlePointerOver}
      onPointerOut={handlePointerOut}
      onClick={handleClick}
    >
      <primitive object={gltf.scene} />
    </group>
  );
}
