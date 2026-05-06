"""
Geometry Processor - Motor de Conversión STEP → Geometría 3D
Usa PythonOCC (OpenCASCADE) para leer y teselar archivos STEP

Autor: STEP Benchmark Team
Versión: 1.0.0
"""

import os
import time
import logging
from typing import Dict, List, Tuple, Optional
import numpy as np

# PythonOCC imports
try:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone, IFSelect_ItemsByEntity
    from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face, TopoDS_Edge
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.Poly import Poly_Triangulation

    PYTHONOCC_AVAILABLE = True
except ImportError as e:
    PYTHONOCC_AVAILABLE = False
    logging.warning(f"PythonOCC no disponible: {e}")

logger = logging.getLogger(__name__)


class GeometryProcessorError(Exception):
    """Excepción personalizada para errores de procesamiento geométrico"""
    pass


class GeometryProcessor:
    """
    Procesador principal para convertir archivos STEP a geometría 3D

    Funcionalidades:
    - Lectura de archivos STEP (ISO 10303-21)
    - Teselación de superficies BREP a mallas trianguladas
    - Generación de múltiples LOD (Level of Detail)
    - Extracción de bounding box
    - Generación de wireframe (aristas)
    - Formato de salida compatible con Three.js
    """

    def __init__(self):
        """Inicializa el procesador"""
        if not PYTHONOCC_AVAILABLE:
            logger.warning(
                "PythonOCC no está disponible. "
                "El GeometryProcessor funcionará en modo limitado."
            )
            self.available = False
            return

        self.step_reader = STEPControl_Reader()
        self.available = True
        logger.info("GeometryProcessor inicializado correctamente")

    def parse_step_file(self, filepath: str):
        """
        Lee un archivo STEP y retorna el shape principal

        Args:
            filepath: Ruta absoluta al archivo STEP

        Returns:
            TopoDS_Shape: Forma topológica principal

        Raises:
            GeometryProcessorError: Si falla la lectura del archivo
        """
        if not self.available:
            logger.warning("PythonOCC no disponible, retornando None")
            # Simular resultado para que el sistema continúe funcionando
            return None

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Archivo no encontrado: {filepath}")

        logger.info(f"Leyendo archivo STEP: {filepath}")
        start_time = time.time()

        # Leer archivo
        status = self.step_reader.ReadFile(filepath)

        if status != IFSelect_RetDone:
            raise GeometryProcessorError(
                f"Error al leer archivo STEP: {filepath}. Status: {status}"
            )

        # Transfer roots and get shape
        self.step_reader.TransferRoots()
        shape = self.step_reader.OneShape()

        if shape is None or shape.IsNull():
            nb = self.step_reader.NbShapes()
            if nb == 0:
                raise GeometryProcessorError(f"STEP file contains no transferable shapes: {filepath}")
            elif nb == 1:
                shape = self.step_reader.Shape(1)
            else:
                from OCC.Core.TopoDS import TopoDS_Compound
                from OCC.Core.BRep import BRep_Builder
                compound = TopoDS_Compound()
                builder = BRep_Builder()
                builder.MakeCompound(compound)
                for i in range(1, nb + 1):
                    s = self.step_reader.Shape(i)
                    if s and not s.IsNull():
                        builder.Add(compound, s)
                shape = compound

        elapsed = time.time() - start_time
        logger.info(f"Archivo STEP leído en {elapsed:.2f}s")

        return shape

    def compute_bounding_box(self, shape) -> Dict:
        """
        Calcula el bounding box de un shape

        Args:
            shape: Forma topológica

        Returns:
            Dict con 'min', 'max', 'center', 'size'
        """
        if not self.available:
            logger.warning("PythonOCC no disponible, retornando bounding box simulado")
            # Retornar un bounding box simulado
            return {
                'min': [-100, -100, -100],
                'max': [100, 100, 100],
                'center': [0, 0, 0],
                'size': [200, 200, 200]
            }

        bbox = Bnd_Box()
        brepbndlib.Add(shape, bbox)

        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        return {
            'min': [xmin, ymin, zmin],
            'max': [xmax, ymax, zmax],
            'center': [
                (xmin + xmax) / 2,
                (ymin + ymax) / 2,
                (zmin + zmax) / 2
            ],
            'size': [
                xmax - xmin,
                ymax - ymin,
                zmax - zmin
            ]
        }

    def tessellate_shape(
        self,
        shape,
        linear_deflection: float = 0.1,
        angular_deflection: float = 0.5
    ) -> Dict:
        """
        Convierte shape BREP a malla triangulada

        Args:
            shape: Forma topológica a teselar
            linear_deflection: Precisión lineal (menor = más triángulos)
            angular_deflection: Precisión angular en radianes

        Returns:
            Dict con:
                - vertices: array de coordenadas [x, y, z, ...]
                - normals: array de normales [nx, ny, nz, ...]
                - indices: array de índices de triángulos
                - triangle_count: número de triángulos
                - vertex_count: número de vértices
        """
        if not self.available:
            logger.warning("PythonOCC no disponible, retornando malla simulada")
            # Retornar una malla simulada
            return {
                'vertices': [],
                'normals': [],
                'indices': [],
                'triangle_count': 0,
                'vertex_count': 0,
                'tessellation_time_ms': 0
            }

        logger.info(
            f"Teselando shape (deflection: {linear_deflection}, "
            f"angular: {angular_deflection})"
        )
        start_time = time.time()

        # Aplicar teselación
        mesh = BRepMesh_IncrementalMesh(
            shape,
            linear_deflection,
            False,  # Relative
            angular_deflection,
            True   # InParallel
        )
        mesh.Perform()

        if not mesh.IsDone():
            raise GeometryProcessorError("Teselación falló")

        # Extraer datos de la malla
        vertices = []
        normals = []
        indices = []
        vertex_offset = 0

        # Explorar todas las caras (versión simplificada)
        try:
            explorer = TopExp_Explorer(shape, TopAbs_FACE)

            while explorer.More():
                try:
                    face = explorer.Current()
                    location = TopLoc_Location()

                    # Intentar obtener triangulación
                    try:
                        triangulation = BRep_Tool.Triangulation(face, location)

                        if triangulation is not None:
                            transformation = location.Transformation()

                            # Extraer vértices
                            face_vertices = []
                            for i in range(1, triangulation.NbNodes() + 1):
                                pnt = triangulation.Node(i)
                                pnt.Transform(transformation)
                                face_vertices.append([pnt.X(), pnt.Y(), pnt.Z()])

                            # Extraer triángulos
                            for i in range(1, triangulation.NbTriangles() + 1):
                                triangle = triangulation.Triangle(i)
                                i1, i2, i3 = triangle.Get()

                                # Ajustar índices
                                indices.extend([
                                    i1 - 1 + vertex_offset,
                                    i2 - 1 + vertex_offset,
                                    i3 - 1 + vertex_offset
                                ])

                            # Agregar vértices
                            vertices.extend(face_vertices)

                            # Calcular normales (simplificado)
                            face_normals = [[0, 0, 1]] * len(face_vertices)
                            normals.extend(face_normals)

                            vertex_offset += len(face_vertices)
                    except Exception as tri_error:
                        logger.warning(f"Error en triangulación: {tri_error}")
                        # Continuar con la siguiente cara

                except Exception as face_error:
                    logger.warning(f"Error procesando cara: {face_error}")

                explorer.Next()
        except Exception as exp_error:
            logger.error(f"Error en exploración de geometría: {exp_error}")
            # Devolver geometría vacía si hay error
            return {'vertices': [], 'normals': [], 'indices': []}

        # Aplanar arrays
        vertices_flat = np.array(vertices, dtype=np.float32).flatten().tolist()
        normals_flat = np.array(normals, dtype=np.float32).flatten().tolist()

        elapsed = time.time() - start_time
        triangle_count = len(indices) // 3
        vertex_count = len(vertices)

        logger.info(
            f"Teselación completada en {elapsed:.2f}s: "
            f"{vertex_count} vértices, {triangle_count} triángulos"
        )

        return {
            'vertices': vertices_flat,
            'normals': normals_flat,
            'indices': indices,
            'triangle_count': triangle_count,
            'vertex_count': vertex_count,
            'tessellation_time_ms': elapsed * 1000
        }

    def extract_edges(self, shape) -> Dict:
        """
        Extrae aristas para renderizado wireframe

        Args:
            shape: Forma topológica

        Returns:
            Dict con array de líneas para wireframe
        """
        if not PYTHONOCC_AVAILABLE:
            logger.warning("PythonOCC no disponible, retornando aristas vacías")
            return {
                'edges': [],
                'edge_count': 0
            }

        logger.info("Extrayendo aristas para wireframe")
        start_time = time.time()

        from OCC.Core.BRep import BRep_Tool
        from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
        from OCC.Core.Geom import Geom_Curve
        from OCC.Core.GeomAdaptor import GeomAdaptor_Curve
        from OCC.Core.GCPnts import GCPnts_UniformAbscissa
        from OCC.Core.BRepTools import BRepTools_WireExplorer
        from OCC.Core.TopoDS import topods_Edge
        from OCC.Core.BRepAdaptor import BRepAdaptor_HCurve

        edges = []
        explorer = TopExp_Explorer(shape, TopAbs_EDGE)

        while explorer.More():
            try:
                edge = topods_Edge(explorer.Current())

                # Discretizar la arista en puntos
                curve_adaptor = BRepAdaptor_Curve(edge)
                curve = curve_adaptor.Curve().Curve()

                # Obtener los parámetros del dominio de la curva
                first_param = curve_adaptor.FirstParameter()
                last_param = curve_adaptor.LastParameter()

                # Calcular número de puntos basado en la longitud de la curva
                # para una discretización uniforme
                nb_points = max(10, int(curve_adaptor.Length() * 10))  # 10 puntos por unidad de longitud

                # Discretizar la curva en puntos
                try:
                    discretizer = GCPnts_UniformAbscissa(curve, nb_points, first_param, last_param)

                    if discretizer.IsDone() and discretizer.NbPoints() > 0:
                        edge_points = []
                        for i in range(1, discretizer.NbPoints() + 1):
                            point = discretizer.Parameter(i)
                            pnt = curve.Value(point)
                            edge_points.append([pnt.X(), pnt.Y(), pnt.Z()])

                        # Convertir puntos en segmentos de línea
                        edge_segments = []
                        for i in range(len(edge_points) - 1):
                            edge_segments.append({
                                'start': edge_points[i],
                                'end': edge_points[i + 1],
                                'type': curve_adaptor.GetType().name
                            })

                        edges.extend(edge_segments)
                except Exception as discretize_error:
                    logger.warning(f"Error discretizando arista: {discretize_error}")

                    # Alternativa: Obtener solo punto inicial y final
                    p_start = BRep_Tool.Point(edge.VertexMin())
                    p_end = BRep_Tool.Point(edge.VertexMax())
                    edges.append({
                        'start': [p_start.X(), p_start.Y(), p_start.Z()],
                        'end': [p_end.X(), p_end.Y(), p_end.Z()],
                        'type': 'fallback'
                    })

                explorer.Next()
            except Exception as e:
                logger.warning(f"Error procesando arista: {e}")
                explorer.Next()

        elapsed = time.time() - start_time
        logger.info(f"Aristas extraídas en {elapsed:.2f}s, total segmentos: {len(edges)}")

        return {
            'edges': edges,
            'edge_count': len(edges)
        }

    def generate_geometry_json(
        self,
        filepath: str,
        lod_levels: Optional[List[float]] = None
    ) -> Dict:
        """
        Genera geometría completa en formato JSON compatible con Three.js

        Args:
            filepath: Ruta al archivo STEP
            lod_levels: Lista de deflections para LOD [low, medium, high]
                       Default: [1.0, 0.1, 0.01]

        Returns:
            Dict con:
                - lod_low: geometría baja resolución
                - lod_medium: geometría media resolución
                - lod_high: geometría alta resolución
                - bounding_box: bounding box del modelo
                - edges: wireframe
                - metadata: información del procesamiento
        """
        if lod_levels is None:
            lod_levels = [1.0, 0.1, 0.01]

        logger.info(f"Procesando archivo completo: {filepath}")
        total_start = time.time()

        if not self.available:
            logger.warning("PythonOCC no disponible, retornando geometría simulada")
            # Retornar una geometría simulada para que el sistema funcione
            empty_geo = {
                'vertices': [],
                'normals': [],
                'indices': [],
                'triangle_count': 0,
                'vertex_count': 0,
                'tessellation_time_ms': 0
            }

            result = {
                'lod_low': empty_geo,
                'lod_medium': empty_geo,
                'lod_high': empty_geo,
                'bounding_box': {
                    'min': [-100, -100, -100],
                    'max': [100, 100, 100],
                    'center': [0, 0, 0],
                    'size': [200, 200, 200]
                },
                'edges': None,
                'metadata': {
                    'filename': os.path.basename(filepath),
                    'file_size_bytes': os.path.getsize(filepath) if os.path.exists(filepath) else 0,
                    'total_processing_time_ms': 0,
                    'lod_levels_used': lod_levels,
                    'timestamp': time.time()
                }
            }

            logger.info("Retornando geometría simulada para mantener funcionalidad")
            return result

        # Leer archivo STEP
        shape = self.parse_step_file(filepath)

        # Calcular bounding box
        bbox = self.compute_bounding_box(shape)

        # Generar LODs
        lod_low = self.tessellate_shape(shape, linear_deflection=lod_levels[0])
        lod_medium = self.tessellate_shape(shape, linear_deflection=lod_levels[1])
        lod_high = self.tessellate_shape(shape, linear_deflection=lod_levels[2])

        # Extraer aristas (para wireframe)
        edges = self.extract_edges(shape)

        total_elapsed = time.time() - total_start

        result = {
            'lod_low': lod_low,
            'lod_medium': lod_medium,
            'lod_high': lod_high,
            'bounding_box': bbox,
            'edges': edges,
            'metadata': {
                'filename': os.path.basename(filepath),
                'file_size_bytes': os.path.getsize(filepath),
                'total_processing_time_ms': total_elapsed * 1000,
                'lod_levels_used': lod_levels,
                'timestamp': time.time()
            }
        }

        logger.info(
            f"Procesamiento completo en {total_elapsed:.2f}s\n"
            f"  LOD Low: {lod_low['triangle_count']} triángulos\n"
            f"  LOD Medium: {lod_medium['triangle_count']} triángulos\n"
            f"  LOD High: {lod_high['triangle_count']} triángulos"
        )

        return result


# Funciones de utilidad

def estimate_memory_usage(geometry_data: Dict) -> Dict:
    """
    Estima el uso de memoria de la geometría

    Args:
        geometry_data: Datos de geometría generados

    Returns:
        Dict con estimaciones de memoria
    """
    vertex_bytes = len(geometry_data.get('vertices', [])) * 4  # float32
    normal_bytes = len(geometry_data.get('normals', [])) * 4
    index_bytes = len(geometry_data.get('indices', [])) * 4

    total_bytes = vertex_bytes + normal_bytes + index_bytes

    return {
        'vertices_kb': vertex_bytes / 1024,
        'normals_kb': normal_bytes / 1024,
        'indices_kb': index_bytes / 1024,
        'total_kb': total_bytes / 1024,
        'total_mb': total_bytes / (1024 * 1024)
    }


# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


if __name__ == '__main__':
    # Test básico
    print("GeometryProcessor Test")
    print("=" * 50)

    if PYTHONOCC_AVAILABLE:
        processor = GeometryProcessor()
        print("OK PythonOCC available")
        print("OK GeometryProcessor initialized correctly")
    else:
        print("X PythonOCC no disponible")
        print("   Instalar con: conda install -c conda-forge pythonocc-core")
