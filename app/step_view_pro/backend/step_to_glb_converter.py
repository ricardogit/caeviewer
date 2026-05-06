"""
STEP to GLB Converter - Conversión de archivos STEP a GLB para visualización 3D
================================================================================

Utiliza pythonocc-core para:
- Leer archivos STEP
- Tesselar geometría
- Generar malla optimizada
- Exportar a formato GLB (glTF Binary) o STL como fallback
- Generar thumbnails
- Calcular métricas geométricas

Author: STEP-View Pro Team
Version: 1.0.0
"""

import logging
import os
import json
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict
import tempfile
import shutil

# PythonOCC imports
try:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.StlAPI import StlAPI_Writer
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_SOLID
    from OCC.Core.TopoDS import TopoDS_Shape, topods
    PYTHONOCC_AVAILABLE = True
except ImportError:
    PYTHONOCC_AVAILABLE = False

# Optional GLB export (pygltflib, trimesh)
try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ConversionConfig:
    """Configuración para conversión STEP to GLB."""

    # Calidad de tesselación
    linear_deflection: float = 0.1  # Deflexión lineal (precisión)
    angular_deflection: float = 0.5  # Deflexión angular en radianes

    # Opciones de salida
    generate_thumbnail: bool = True
    thumbnail_size: Tuple[int, int] = (400, 300)
    calculate_metrics: bool = True

    # Formato de salida
    output_format: str = 'glb'  # 'glb', 'stl', 'obj'
    binary_stl: bool = True  # Si es STL, usar formato binario

    # Optimización
    optimize_mesh: bool = True
    merge_vertices: bool = True
    remove_duplicates: bool = True

    @classmethod
    def from_quality_preset(cls, quality: str) -> 'ConversionConfig':
        """
        Crear configuración desde preset de calidad.

        Args:
            quality: 'low', 'medium', 'high', 'ultra'

        Returns:
            ConversionConfig configurado
        """
        presets = {
            'low': {
                'linear_deflection': 0.5,
                'angular_deflection': 1.0,
                'optimize_mesh': True
            },
            'medium': {
                'linear_deflection': 0.1,
                'angular_deflection': 0.5,
                'optimize_mesh': True
            },
            'high': {
                'linear_deflection': 0.05,
                'angular_deflection': 0.2,
                'optimize_mesh': False
            },
            'ultra': {
                'linear_deflection': 0.01,
                'angular_deflection': 0.1,
                'optimize_mesh': False
            }
        }

        preset = presets.get(quality.lower(), presets['medium'])

        return cls(
            linear_deflection=preset['linear_deflection'],
            angular_deflection=preset['angular_deflection'],
            optimize_mesh=preset['optimize_mesh']
        )


@dataclass
class ConversionResult:
    """Resultado de la conversión."""

    success: bool
    glb_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    metrics: Optional[Dict] = None
    error: Optional[str] = None
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class STEPToGLBConverter:
    """
    Conversor de STEP a GLB utilizando pythonocc-core.

    Workflow:
    1. Leer archivo STEP
    2. Tesselar geometría (crear malla triangular)
    3. Exportar a GLB (o STL como fallback)
    4. Generar thumbnail (opcional)
    5. Calcular métricas (opcional)
    """

    def __init__(self, config: Optional[ConversionConfig] = None):
        """
        Inicializar conversor.

        Args:
            config: Configuración de conversión (usa default si None)
        """
        self.config = config or ConversionConfig()
        self.shape = None
        self.warnings = []

    def convert(
        self,
        step_path: str,
        model_id: str,
        output_dir: str = 'data/processed',
        progress_callback: Optional[callable] = None,
        job_id: Optional[str] = None
    ) -> ConversionResult:
        """
        Convertir archivo STEP a GLB.

        Args:
            step_path: Ruta al archivo STEP
            model_id: ID del modelo (para nombre de salida)
            output_dir: Directorio de salida
            progress_callback: Callback para reportar progreso (job_id, progress, step)
            job_id: ID del job para tracking de progreso

        Returns:
            ConversionResult con rutas y métricas
        """
        if not PYTHONOCC_AVAILABLE:
            return ConversionResult(
                success=False,
                error="pythonocc-core not available"
            )

        try:
            step_path = Path(step_path)
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"Converting STEP to GLB: {step_path}")

            # Helper para reportar progreso
            def report_progress(progress: int, step: str):
                if progress_callback and job_id:
                    try:
                        progress_callback(job_id, progress, step)
                    except Exception as e:
                        logger.warning(f"Error reporting progress: {e}")

            # 1. Leer STEP
            report_progress(10, "Leyendo archivo STEP")
            self.shape = self._read_step_file(step_path)
            report_progress(25, "Archivo STEP leído exitosamente")

            # 2. Tesselar geometría
            report_progress(30, "Teselando geometría")
            self._tessellate_shape()
            report_progress(60, "Geometría teselada")

            # 3. Exportar a formato de salida
            report_progress(65, "Generando malla 3D")
            output_path = output_dir / f"{model_id}.{self.config.output_format}"

            if self.config.output_format == 'glb' and TRIMESH_AVAILABLE:
                # Exportar usando trimesh (vía STL intermedio)
                glb_path = self._export_via_trimesh(output_path)
            else:
                # Fallback: exportar como STL
                glb_path = self._export_stl(output_path)
                if self.config.output_format == 'glb':
                    self.warnings.append("GLB export not available, exported as STL")

            report_progress(85, "Archivo GLB generado")

            # 4. Generar thumbnail (opcional)
            thumbnail_path = None
            if self.config.generate_thumbnail:
                report_progress(90, "Generando thumbnail")
                thumbnail_path = self._generate_thumbnail(
                    output_dir / f"{model_id}_thumb.png"
                )

            # 5. Calcular métricas (opcional)
            metrics = None
            if self.config.calculate_metrics:
                report_progress(95, "Calculando métricas")
                metrics = self._calculate_metrics()

            report_progress(100, "Conversión completada")
            logger.info(f"Conversion completed: {glb_path}")

            return ConversionResult(
                success=True,
                glb_path=str(glb_path),
                thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
                metrics=metrics,
                warnings=self.warnings
            )

        except Exception as e:
            logger.error(f"Error converting STEP to GLB: {e}", exc_info=True)
            return ConversionResult(
                success=False,
                error=str(e),
                warnings=self.warnings
            )

    def _read_step_file(self, step_path: Path) -> TopoDS_Shape:
        """
        Leer archivo STEP y cargar geometría.

        Args:
            step_path: Ruta al archivo STEP

        Returns:
            TopoDS_Shape con la geometría

        Raises:
            ValueError: Si el archivo no se puede leer
        """
        if not step_path.exists():
            raise FileNotFoundError(f"STEP file not found: {step_path}")

        step_reader = STEPControl_Reader()
        status = step_reader.ReadFile(str(step_path))

        if status != IFSelect_RetDone:
            raise ValueError(f"Error reading STEP file: {status}")

        # Transfer all roots
        step_reader.TransferRoots()

        # Try OneShape first, then fall back to iterating shapes
        shape = step_reader.OneShape()

        if shape is None or shape.IsNull():
            nb = step_reader.NbShapes()
            if nb == 0:
                raise ValueError("STEP file contains no transferable shapes")
            elif nb == 1:
                shape = step_reader.Shape(1)
            else:
                from OCC.Core.TopoDS import TopoDS_Compound
                from OCC.Core.BRep import BRep_Builder
                compound = TopoDS_Compound()
                builder = BRep_Builder()
                builder.MakeCompound(compound)
                for i in range(1, nb + 1):
                    s = step_reader.Shape(i)
                    if s and not s.IsNull():
                        builder.Add(compound, s)
                shape = compound

        if shape is None or shape.IsNull():
            raise ValueError("Failed to load geometry from STEP file - shape is null after all transfer attempts")

        logger.info(f"Loaded STEP file: {step_path.name}")
        return shape

    _MAX_FACES = 500000  # faces above this are rejected immediately
    _MAX_SOLIDS_COLORED = 40  # solids above this fall back to single-mesh export

    def _count_faces(self) -> int:
        """Count faces in the loaded shape, stopping early at _MAX_FACES + 1."""
        count = 0
        exp = TopExp_Explorer(self.shape, TopAbs_FACE)
        while exp.More():
            count += 1
            if count > self._MAX_FACES:
                return count  # early exit — caller will reject
            exp.Next()
        return count

    def _tessellate_shape(self) -> None:
        """Tessellate the shape, auto-downgrading quality for very large models."""
        face_count = self._count_faces()
        logger.info(f"Shape has {face_count} faces")

        if face_count > self._MAX_FACES:
            raise ValueError(
                f"Assembly has {face_count}+ faces which exceeds the {self._MAX_FACES:,} face limit "
                "for browser visualization. "
                "Split it into smaller sub-assemblies or open it in a dedicated CAD viewer."
            )

        lin = self.config.linear_deflection
        ang = self.config.angular_deflection

        if face_count > 10000:
            lin = max(lin, 2.0)
            ang = max(ang, 1.5)
            self.warnings.append(
                f"Large model ({face_count} faces): using coarse tessellation "
                f"(linear={lin}, angular={ang})"
            )
        elif face_count > 3000:
            lin = max(lin, 1.0)
            ang = max(ang, 1.0)

        logger.info(f"Tessellating (linear={lin}, angular={ang})")
        mesh = BRepMesh_IncrementalMesh(
            self.shape, lin, False, ang, True  # parallel=True
        )
        mesh.Perform()

        if not mesh.IsDone():
            self.warnings.append("Tessellation may be incomplete")
            logger.warning("Tessellation not fully completed")

    def _export_stl(self, output_path: Path) -> Path:
        """
        Exportar shape a STL.

        Args:
            output_path: Ruta de salida

        Returns:
            Path al archivo exportado
        """
        # Si el output es .glb pero no tenemos trimesh, cambiar a .stl
        if output_path.suffix == '.glb':
            output_path = output_path.with_suffix('.stl')

        stl_writer = StlAPI_Writer()

        # Configurar modo binario/ASCII
        if self.config.binary_stl:
            stl_writer.SetASCIIMode(False)
        else:
            stl_writer.SetASCIIMode(True)

        # Escribir archivo
        stl_writer.Write(self.shape, str(output_path))

        logger.info(f"Exported STL: {output_path}")
        return output_path

    # Visually distinct colours for assembly parts (RGB 0-255)
    _PART_COLORS = [
        (120, 160, 210),  # steel blue
        (210, 140,  60),  # warm orange
        (100, 190, 130),  # muted green
        (200,  90,  90),  # brick red
        (160, 130, 200),  # soft purple
        (230, 200,  70),  # amber
        ( 80, 190, 200),  # teal
        (230, 150, 180),  # rose
        (140, 200, 100),  # lime
        (100, 120, 180),  # indigo
    ]

    def _export_via_trimesh(self, output_path: Path) -> Path:
        """Export each OCC solid as a separate trimesh node with a distinct colour.
        Falls back to single-mesh export when there are too many solids."""
        # Collect individual solid shapes (up to _MAX_SOLIDS_COLORED + 1 for cap check)
        solids = []
        exp = TopExp_Explorer(self.shape, TopAbs_SOLID)
        while exp.More():
            solids.append(exp.Current())
            if len(solids) > self._MAX_SOLIDS_COLORED:
                break  # too many — fall back to single mesh
            exp.Next()

        use_per_solid = (0 < len(solids) <= self._MAX_SOLIDS_COLORED)

        if not use_per_solid:
            # Single merged mesh (no per-part colours)
            return self._export_single_mesh_glb(output_path)

        logger.info(f"Exporting {len(solids)} solid(s) as separate GLB nodes")

        scene = trimesh.Scene()
        stl_writer = StlAPI_Writer()
        stl_writer.SetASCIIMode(False)
        tmp_files = []

        try:
            for i, solid in enumerate(solids):
                fd, tmp_stl_str = tempfile.mkstemp(suffix='.stl')
                os.close(fd)
                tmp_files.append(tmp_stl_str)

                stl_writer.Write(solid, tmp_stl_str)

                body_mesh = trimesh.load(tmp_stl_str, force='mesh')
                if body_mesh is None or not hasattr(body_mesh, 'faces') or len(body_mesh.faces) == 0:
                    continue

                if self.config.optimize_mesh:
                    try:
                        if self.config.merge_vertices:
                            body_mesh.merge_vertices()
                        body_mesh.remove_unreferenced_vertices()
                    except Exception:
                        pass

                r, g, b = self._PART_COLORS[i % len(self._PART_COLORS)]
                body_mesh.visual = trimesh.visual.ColorVisuals(
                    mesh=body_mesh,
                    vertex_colors=[r, g, b, 255],
                )

                name = f'solid_{i:03d}'
                body_mesh.metadata['name'] = name
                scene.add_geometry(body_mesh, node_name=name, geom_name=name)

            if len(scene.geometry) == 0:
                raise ValueError("All solids produced empty meshes after export")

            scene.export(str(output_path))
            logger.info(f"Exported multi-colour GLB: {len(scene.geometry)} solid(s) → {output_path}")
            return output_path

        finally:
            for p in tmp_files:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

    def _export_single_mesh_glb(self, output_path: Path) -> Path:
        """Export the full shape as one merged GLB mesh (used when solid count is too high)."""
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tmp:
            tmp_stl = Path(tmp.name)
        try:
            self._export_stl(tmp_stl)
            mesh = trimesh.load(str(tmp_stl), force='mesh')
            if self.config.optimize_mesh:
                try:
                    if self.config.merge_vertices:
                        mesh.merge_vertices()
                    mesh.remove_unreferenced_vertices()
                except Exception:
                    pass
            mesh.export(str(output_path))
            logger.info(f"Exported single-mesh GLB: {output_path}")
            return output_path
        finally:
            if tmp_stl.exists():
                tmp_stl.unlink()

    def _generate_thumbnail(self, output_path: Path) -> Optional[Path]:
        """
        Generar thumbnail del modelo.

        Args:
            output_path: Ruta para guardar thumbnail

        Returns:
            Path al thumbnail o None si falla
        """
        try:
            # Para generar thumbnail necesitaríamos un renderizador
            # Esto requiere bibliotecas adicionales como vtk, pyrender, etc.
            # Por ahora, retornamos None y logeamos un warning
            self.warnings.append("Thumbnail generation not implemented")
            logger.warning("Thumbnail generation requires additional libraries (vtk/pyrender)")
            return None

        except Exception as e:
            logger.error(f"Error generating thumbnail: {e}")
            return None

    def _calculate_metrics(self) -> Dict:
        """
        Calcular métricas geométricas del modelo.

        Returns:
            Dict con métricas calculadas
        """
        try:
            metrics = {}

            # 1. Bounding box
            bbox = Bnd_Box()
            brepbndlib.Add(self.shape, bbox)

            if not bbox.IsVoid():
                xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
                metrics['bounding_box'] = {
                    'min': [xmin, ymin, zmin],
                    'max': [xmax, ymax, zmax],
                    'dimensions': [xmax - xmin, ymax - ymin, zmax - zmin],
                    'diagonal': ((xmax - xmin)**2 + (ymax - ymin)**2 + (zmax - zmin)**2)**0.5
                }

            # 2. Propiedades geométricas
            props = GProp_GProps()
            brepgprop.VolumeProperties(self.shape, props)

            volume = props.Mass()
            if volume > 0:
                metrics['volume'] = volume

                # Centro de masa
                cog = props.CentreOfMass()
                metrics['center_of_mass'] = [cog.X(), cog.Y(), cog.Z()]

            # 3. Propiedades de superficie
            surface_props = GProp_GProps()
            brepgprop.SurfaceProperties(self.shape, surface_props)
            metrics['surface_area'] = surface_props.Mass()

            # 4. Contar elementos topológicos
            topology = self._count_topology_elements()
            metrics['topology'] = topology

            logger.info(f"Calculated metrics: {len(metrics)} properties")
            return metrics

        except Exception as e:
            logger.error(f"Error calculating metrics: {e}")
            return {}

    def _count_topology_elements(self) -> Dict:
        """
        Contar elementos topológicos (caras, aristas, vértices, sólidos).

        Returns:
            Dict con conteos
        """
        counts = {
            'solids': 0,
            'faces': 0,
            'edges': 0,
            'vertices': 0
        }

        # Contar sólidos
        exp_solid = TopExp_Explorer(self.shape, TopAbs_SOLID)
        while exp_solid.More():
            counts['solids'] += 1
            exp_solid.Next()

        # Contar caras
        exp_face = TopExp_Explorer(self.shape, TopAbs_FACE)
        while exp_face.More():
            counts['faces'] += 1
            exp_face.Next()

        # Contar aristas
        exp_edge = TopExp_Explorer(self.shape, TopAbs_EDGE)
        while exp_edge.More():
            counts['edges'] += 1
            exp_edge.Next()

        # Contar vértices
        exp_vertex = TopExp_Explorer(self.shape, TopAbs_VERTEX)
        while exp_vertex.More():
            counts['vertices'] += 1
            exp_vertex.Next()

        return counts


# Función de conveniencia para conversión simple
def convert_step_to_glb(
    step_path: str,
    output_path: Optional[str] = None,
    quality: str = 'medium',
    progress_callback: Optional[callable] = None,
    job_id: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Función simple para convertir STEP a GLB.

    Args:
        step_path: Ruta al archivo STEP
        output_path: Ruta de salida (opcional, auto-genera si None)
        quality: Calidad de conversión ('low', 'medium', 'high', 'ultra')
        progress_callback: Callback para reportar progreso (job_id, progress, step)
        job_id: ID del job para tracking de progreso

    Returns:
        Tupla (success: bool, output_path_or_error: str)
    """
    try:
        step_path = Path(step_path)

        if output_path is None:
            output_path = step_path.with_suffix('.glb')
        else:
            output_path = Path(output_path)

        # Crear configuración
        config = ConversionConfig.from_quality_preset(quality)
        config.generate_thumbnail = False
        config.calculate_metrics = False

        # Convertir
        converter = STEPToGLBConverter(config=config)

        # Extraer directorio y nombre base
        output_dir = output_path.parent
        model_id = output_path.stem

        result = converter.convert(
            step_path=str(step_path),
            model_id=model_id,
            output_dir=str(output_dir),
            progress_callback=progress_callback,
            job_id=job_id
        )

        if result.success:
            return True, result.glb_path
        else:
            return False, result.error or "Unknown error"

    except Exception as e:
        logger.error(f"Error in convert_step_to_glb: {e}", exc_info=True)
        return False, str(e)


# Alias para compatibilidad
STEPToGLTFConverter = STEPToGLBConverter
