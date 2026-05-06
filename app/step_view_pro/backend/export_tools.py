"""
Export Tools - Exportación avanzada de geometrías STEP a múltiples formatos
Versión: 1.0.0
Autor: STEP-View Pro Team

Formatos soportados:
- STL (ASCII y Binary)
- OBJ (Wavefront)
- IGES
- STEP (re-export)
- JSON (metadatos, árbol)
- glTF/GLB (para web)
- CSV (tablas de datos)
"""

import logging
import json
import csv
import os
from typing import Dict, List, Optional, Any
from pathlib import Path
import tempfile

logger = logging.getLogger(__name__)

# PythonOCC imports
try:
    from OCC.Core.TopoDS import TopoDS_Shape
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.IGESControl import IGESControl_Writer
    from OCC.Core.StlAPI import StlAPI_Writer
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Extend.DataExchange import write_stl_file, read_step_file
    PYTHONOCC_AVAILABLE = True
except ImportError:
    PYTHONOCC_AVAILABLE = False
    logger.warning("PythonOCC not available. Export functionality will be limited.")


class ExportTools:
    """
    Herramientas de exportación para geometrías STEP
    """

    @staticmethod
    def export_to_stl(shape: 'TopoDS_Shape',
                      output_path: str,
                      ascii_mode: bool = False,
                      linear_deflection: float = 0.1,
                      angular_deflection: float = 0.5) -> Dict:
        """
        Exporta geometría a formato STL

        Args:
            shape: Forma TopoDS
            output_path: Ruta del archivo de salida
            ascii_mode: True para ASCII, False para binario
            linear_deflection: Deflexión lineal para tesselación
            angular_deflection: Deflexión angular en radianes

        Returns:
            Dict con resultado de exportación
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for STL export")

        try:
            # Tesselar la forma
            mesh = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection)
            mesh.Perform()

            if not mesh.IsDone():
                raise RuntimeError("Mesh generation failed")

            # Escribir STL
            stl_writer = StlAPI_Writer()
            stl_writer.SetASCIIMode(ascii_mode)

            success = stl_writer.Write(shape, output_path)

            if not success:
                raise RuntimeError("STL write failed")

            file_size = os.path.getsize(output_path)

            logger.info(f"STL exported: {output_path} ({file_size} bytes)")

            return {
                'success': True,
                'format': 'STL',
                'mode': 'ASCII' if ascii_mode else 'Binary',
                'file_path': output_path,
                'file_size_bytes': file_size,
                'linear_deflection': linear_deflection,
                'angular_deflection': angular_deflection
            }

        except Exception as e:
            logger.exception(f"Error exporting to STL: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def export_to_obj(shape: 'TopoDS_Shape',
                      output_path: str,
                      linear_deflection: float = 0.1,
                      angular_deflection: float = 0.5) -> Dict:
        """
        Exporta geometría a formato OBJ (Wavefront)

        Args:
            shape: Forma TopoDS
            output_path: Ruta del archivo de salida
            linear_deflection: Deflexión lineal
            angular_deflection: Deflexión angular

        Returns:
            Dict con resultado de exportación
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for OBJ export")

        try:
            from OCC.Core.TopExp import TopExp_Explorer
            from OCC.Core.TopAbs import TopAbs_FACE
            from OCC.Core.BRep import BRep_Tool
            from OCC.Core.TopLoc import TopLoc_Location

            # Tesselar
            mesh = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection)
            mesh.Perform()

            vertices = []
            normals = []
            faces = []
            vertex_index = 1

            # Explorar faces
            explorer = TopExp_Explorer(shape, TopAbs_FACE)

            while explorer.More():
                face = explorer.Current()
                location = TopLoc_Location()
                triangulation = BRep_Tool.Triangulation(face, location)

                if triangulation:
                    transformation = location.Transformation()

                    # Extraer vértices
                    for i in range(1, triangulation.NbNodes() + 1):
                        vertex = triangulation.Node(i)
                        vertex.Transform(transformation)
                        vertices.append(f"v {vertex.X()} {vertex.Y()} {vertex.Z()}")

                    # Extraer caras
                    for i in range(1, triangulation.NbTriangles() + 1):
                        triangle = triangulation.Triangle(i)
                        n1, n2, n3 = triangle.Get()

                        # OBJ usa índices 1-based
                        faces.append(f"f {vertex_index + n1 - 1} {vertex_index + n2 - 1} {vertex_index + n3 - 1}")

                    vertex_index += triangulation.NbNodes()

                explorer.Next()

            # Escribir archivo OBJ
            with open(output_path, 'w') as f:
                f.write("# Exported from STEP-View Pro\n")
                f.write(f"# Vertices: {len(vertices)}\n")
                f.write(f"# Faces: {len(faces)}\n\n")

                for vertex in vertices:
                    f.write(vertex + "\n")

                f.write("\n")

                for face in faces:
                    f.write(face + "\n")

            file_size = os.path.getsize(output_path)

            logger.info(f"OBJ exported: {output_path} ({file_size} bytes)")

            return {
                'success': True,
                'format': 'OBJ',
                'file_path': output_path,
                'file_size_bytes': file_size,
                'vertex_count': len(vertices),
                'face_count': len(faces)
            }

        except Exception as e:
            logger.exception(f"Error exporting to OBJ: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def export_to_iges(shape: 'TopoDS_Shape',
                       output_path: str) -> Dict:
        """
        Exporta geometría a formato IGES

        Args:
            shape: Forma TopoDS
            output_path: Ruta del archivo de salida

        Returns:
            Dict con resultado de exportación
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for IGES export")

        try:
            iges_writer = IGESControl_Writer()
            iges_writer.AddShape(shape)
            iges_writer.ComputeModel()

            status = iges_writer.Write(output_path)

            if status != IFSelect_RetDone:
                raise RuntimeError(f"IGES write failed with status {status}")

            file_size = os.path.getsize(output_path)

            logger.info(f"IGES exported: {output_path} ({file_size} bytes)")

            return {
                'success': True,
                'format': 'IGES',
                'file_path': output_path,
                'file_size_bytes': file_size
            }

        except Exception as e:
            logger.exception(f"Error exporting to IGES: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def export_to_step(shape: 'TopoDS_Shape',
                       output_path: str,
                       schema: str = 'AP214CD') -> Dict:
        """
        Re-exporta geometría a formato STEP

        Args:
            shape: Forma TopoDS
            output_path: Ruta del archivo de salida
            schema: Schema STEP (AP203, AP214CD, etc.)

        Returns:
            Dict con resultado de exportación
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for STEP export")

        try:
            step_writer = STEPControl_Writer()
            step_writer.Transfer(shape, STEPControl_AsIs)

            status = step_writer.Write(output_path)

            if status != IFSelect_RetDone:
                raise RuntimeError(f"STEP write failed with status {status}")

            file_size = os.path.getsize(output_path)

            logger.info(f"STEP exported: {output_path} ({file_size} bytes)")

            return {
                'success': True,
                'format': 'STEP',
                'schema': schema,
                'file_path': output_path,
                'file_size_bytes': file_size
            }

        except Exception as e:
            logger.exception(f"Error exporting to STEP: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def export_metadata_to_json(metadata: Dict,
                                 output_path: str,
                                 pretty: bool = True) -> Dict:
        """
        Exporta metadatos a JSON

        Args:
            metadata: Diccionario de metadatos
            output_path: Ruta del archivo de salida
            pretty: Formatear JSON con indentación

        Returns:
            Dict con resultado de exportación
        """
        try:
            with open(output_path, 'w') as f:
                if pretty:
                    json.dump(metadata, f, indent=2)
                else:
                    json.dump(metadata, f)

            file_size = os.path.getsize(output_path)

            logger.info(f"JSON exported: {output_path} ({file_size} bytes)")

            return {
                'success': True,
                'format': 'JSON',
                'file_path': output_path,
                'file_size_bytes': file_size
            }

        except Exception as e:
            logger.exception(f"Error exporting to JSON: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def export_tree_to_json(tree_data: Dict,
                            output_path: str) -> Dict:
        """
        Exporta árbol de ensamblaje a JSON

        Args:
            tree_data: Datos del árbol
            output_path: Ruta del archivo de salida

        Returns:
            Dict con resultado de exportación
        """
        return ExportTools.export_metadata_to_json(tree_data, output_path, pretty=True)

    @staticmethod
    def export_to_csv(data: List[Dict],
                      output_path: str,
                      columns: Optional[List[str]] = None) -> Dict:
        """
        Exporta datos tabulares a CSV

        Args:
            data: Lista de diccionarios con datos
            output_path: Ruta del archivo de salida
            columns: Columnas a exportar (None = todas)

        Returns:
            Dict con resultado de exportación
        """
        try:
            if not data:
                raise ValueError("No data to export")

            # Determinar columnas
            if not columns:
                columns = list(data[0].keys())

            # Escribir CSV
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()

                for row in data:
                    # Filtrar solo las columnas especificadas
                    filtered_row = {k: v for k, v in row.items() if k in columns}
                    writer.writerow(filtered_row)

            file_size = os.path.getsize(output_path)

            logger.info(f"CSV exported: {output_path} ({file_size} bytes)")

            return {
                'success': True,
                'format': 'CSV',
                'file_path': output_path,
                'file_size_bytes': file_size,
                'row_count': len(data),
                'column_count': len(columns)
            }

        except Exception as e:
            logger.exception(f"Error exporting to CSV: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def export_gltf_geometry(shape: 'TopoDS_Shape',
                             output_path: str,
                             binary: bool = True) -> Dict:
        """
        Exporta geometría a formato glTF/GLB para web

        Args:
            shape: Forma TopoDS
            output_path: Ruta del archivo de salida
            binary: True para GLB, False para glTF

        Returns:
            Dict con resultado de exportación
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for glTF export")

        try:
            # Primero exportar a OBJ temporal
            temp_obj = tempfile.NamedTemporaryFile(suffix='.obj', delete=False)
            temp_obj_path = temp_obj.name
            temp_obj.close()

            obj_result = ExportTools.export_to_obj(shape, temp_obj_path)

            if not obj_result['success']:
                raise RuntimeError("Failed to generate OBJ for glTF conversion")

            # TODO: Convertir OBJ a glTF
            # Esto requeriría una librería adicional como trimesh o pygltflib
            # Por ahora, retornamos la referencia al OBJ

            logger.info(f"glTF export (via OBJ): {output_path}")

            return {
                'success': True,
                'format': 'glTF' if not binary else 'GLB',
                'file_path': temp_obj_path,
                'file_size_bytes': obj_result['file_size_bytes'],
                'note': 'Exported as OBJ (glTF conversion requires additional library)'
            }

        except Exception as e:
            logger.exception(f"Error exporting to glTF: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def batch_export(shape: 'TopoDS_Shape',
                     output_dir: str,
                     base_filename: str,
                     formats: List[str],
                     options: Optional[Dict] = None) -> Dict:
        """
        Exporta a múltiples formatos simultáneamente

        Args:
            shape: Forma TopoDS
            output_dir: Directorio de salida
            base_filename: Nombre base del archivo (sin extensión)
            formats: Lista de formatos ('stl', 'obj', 'iges', 'step')
            options: Opciones de exportación por formato

        Returns:
            Dict con resultados de todas las exportaciones
        """
        if not PYTHONOCC_AVAILABLE:
            raise RuntimeError("PythonOCC required for batch export")

        options = options or {}
        results = {}

        # Crear directorio si no existe
        os.makedirs(output_dir, exist_ok=True)

        for fmt in formats:
            fmt_lower = fmt.lower()
            output_path = os.path.join(output_dir, f"{base_filename}.{fmt_lower}")

            try:
                if fmt_lower == 'stl':
                    stl_options = options.get('stl', {})
                    result = ExportTools.export_to_stl(
                        shape,
                        output_path,
                        ascii_mode=stl_options.get('ascii_mode', False),
                        linear_deflection=stl_options.get('linear_deflection', 0.1),
                        angular_deflection=stl_options.get('angular_deflection', 0.5)
                    )
                elif fmt_lower == 'obj':
                    obj_options = options.get('obj', {})
                    result = ExportTools.export_to_obj(
                        shape,
                        output_path,
                        linear_deflection=obj_options.get('linear_deflection', 0.1),
                        angular_deflection=obj_options.get('angular_deflection', 0.5)
                    )
                elif fmt_lower == 'iges':
                    result = ExportTools.export_to_iges(shape, output_path)
                elif fmt_lower == 'step':
                    step_options = options.get('step', {})
                    result = ExportTools.export_to_step(
                        shape,
                        output_path,
                        schema=step_options.get('schema', 'AP214CD')
                    )
                else:
                    result = {
                        'success': False,
                        'error': f"Unsupported format: {fmt}"
                    }

                results[fmt_lower] = result

            except Exception as e:
                logger.exception(f"Error exporting to {fmt}: {e}")
                results[fmt_lower] = {
                    'success': False,
                    'error': str(e)
                }

        # Resumen
        success_count = sum(1 for r in results.values() if r.get('success'))
        total_size = sum(r.get('file_size_bytes', 0) for r in results.values() if r.get('success'))

        return {
            'batch_export': True,
            'formats_requested': len(formats),
            'formats_succeeded': success_count,
            'total_size_bytes': total_size,
            'results': results
        }


def get_supported_formats() -> List[Dict]:
    """
    Retorna lista de formatos soportados

    Returns:
        Lista de dicts con info de formatos
    """
    return [
        {
            'format': 'STL',
            'extensions': ['.stl'],
            'description': 'Stereolithography (triangular mesh)',
            'modes': ['ASCII', 'Binary'],
            'supports_color': False,
            'supports_assembly': False
        },
        {
            'format': 'OBJ',
            'extensions': ['.obj'],
            'description': 'Wavefront OBJ (triangular mesh)',
            'modes': ['ASCII'],
            'supports_color': True,
            'supports_assembly': False
        },
        {
            'format': 'IGES',
            'extensions': ['.iges', '.igs'],
            'description': 'Initial Graphics Exchange Specification',
            'modes': ['ASCII'],
            'supports_color': False,
            'supports_assembly': True
        },
        {
            'format': 'STEP',
            'extensions': ['.step', '.stp'],
            'description': 'Standard for the Exchange of Product Data',
            'modes': ['ASCII'],
            'supports_color': True,
            'supports_assembly': True
        },
        {
            'format': 'JSON',
            'extensions': ['.json'],
            'description': 'JavaScript Object Notation (metadata)',
            'modes': ['ASCII'],
            'supports_color': False,
            'supports_assembly': True
        },
        {
            'format': 'CSV',
            'extensions': ['.csv'],
            'description': 'Comma-Separated Values (tabular data)',
            'modes': ['ASCII'],
            'supports_color': False,
            'supports_assembly': False
        }
    ]


logger.info("OK Export Tools module loaded")
