"""
Comparison Tools - Comparación de versiones de archivos STEP
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Comparación de metadatos (header, author, org, schema)
- Comparación de estructura de entidades
- Comparación geométrica (bounding box, volumen)
- Detección de cambios (añadido, eliminado, modificado)
- Cálculo de similitud
- Reportes de diferencias
"""

import logging
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import json

logger = logging.getLogger(__name__)

# PythonOCC imports
try:
    from OCC.Core.TopoDS import TopoDS_Shape
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties
    PYTHONOCC_AVAILABLE = True
except ImportError:
    PYTHONOCC_AVAILABLE = False
    logger.warning("PythonOCC not available. Comparison tools will be limited.")


@dataclass
class ComparisonResult:
    """Resultado de una comparación entre dos archivos"""
    comparison_id: str
    file1_id: str
    file2_id: str
    file1_name: str
    file2_name: str

    # Resumen de cambios
    change_summary: Dict

    # Comparación de metadatos
    metadata_diff: Dict

    # Comparación de estructura
    structure_diff: Dict

    # Comparación geométrica
    geometry_diff: Dict

    # Métricas de similitud
    similarity_score: float  # 0.0 - 1.0

    # Timestamp
    compared_at: str

    def to_dict(self):
        return asdict(self)


class ComparisonTools:
    """
    Herramientas de comparación para archivos STEP
    """

    @staticmethod
    def compare_metadata(header1: Dict, header2: Dict) -> Dict:
        """
        Compara metadatos de dos headers STEP

        Args:
            header1: Metadatos del archivo 1
            header2: Metadatos del archivo 2

        Returns:
            Dict con diferencias
        """
        fields_to_compare = [
            'file_name',
            'file_description',
            'file_schema',
            'author',
            'organization',
            'time_stamp'
        ]

        differences = {}
        changes = []

        for field in fields_to_compare:
            val1 = header1.get(field)
            val2 = header2.get(field)

            if val1 != val2:
                differences[field] = {
                    'old': val1,
                    'new': val2,
                    'changed': True
                }
                changes.append(field)
            else:
                differences[field] = {
                    'value': val1,
                    'changed': False
                }

        return {
            'differences': differences,
            'changed_fields': changes,
            'change_count': len(changes)
        }

    @staticmethod
    def compare_structure(header1: Dict, header2: Dict) -> Dict:
        """
        Compara estructura de entidades

        Args:
            header1: Header 1 con entity counts
            header2: Header 2 con entity counts

        Returns:
            Dict con diferencias estructurales
        """
        metrics = [
            'total_entities',
            'total_references',
            'max_depth',
            'root_entities',
            'leaf_entities'
        ]

        differences = {}

        for metric in metrics:
            val1 = header1.get(metric, 0) or 0
            val2 = header2.get(metric, 0) or 0
            delta = (val2 or 0) - (val1 or 0)
            percent_change = ((delta or 0) / (val1 or 1) * 100) if (val1 or 0) > 0 else 0

            differences[metric] = {
                'old': val1,
                'new': val2,
                'delta': delta,
                'percent_change': round(percent_change, 2),
                'changed': delta != 0
            }

        # Comparar distribución de profundidad
        depth_dist1 = header1.get('depth_distribution', {})
        depth_dist2 = header2.get('depth_distribution', {})

        depth_changes = ComparisonTools._compare_distributions(
            depth_dist1,
            depth_dist2
        )

        return {
            'metric_differences': differences,
            'depth_distribution_changes': depth_changes,
            'structure_changed': any(d['changed'] for d in differences.values())
        }

    @staticmethod
    def compare_geometry(shape1: Optional['TopoDS_Shape'],
                         shape2: Optional['TopoDS_Shape']) -> Dict:
        """
        Compara geometrías de dos formas

        Args:
            shape1: Forma 1
            shape2: Forma 2

        Returns:
            Dict con diferencias geométricas
        """
        if not PYTHONOCC_AVAILABLE:
            return {'error': 'PythonOCC not available'}

        if not shape1 or not shape2:
            return {'error': 'Invalid shapes'}

        try:
            # Comparar bounding boxes
            bbox1 = ComparisonTools._get_bounding_box(shape1)
            bbox2 = ComparisonTools._get_bounding_box(shape2)

            bbox_diff = {
                'min_x': bbox2['min'][0] - bbox1['min'][0],
                'min_y': bbox2['min'][1] - bbox1['min'][1],
                'min_z': bbox2['min'][2] - bbox1['min'][2],
                'max_x': bbox2['max'][0] - bbox1['max'][0],
                'max_y': bbox2['max'][1] - bbox1['max'][1],
                'max_z': bbox2['max'][2] - bbox1['max'][2],
                'dimensions_delta': [
                    bbox2['dimensions'][i] - bbox1['dimensions'][i]
                    for i in range(3)
                ]
            }

            # Comparar volúmenes
            vol1 = ComparisonTools._get_volume(shape1)
            vol2 = ComparisonTools._get_volume(shape2)
            vol_delta = vol2 - vol1
            vol_percent_change = (vol_delta / vol1 * 100) if vol1 > 0 else 0

            # Comparar centro de masa
            com1 = ComparisonTools._get_center_of_mass(shape1)
            com2 = ComparisonTools._get_center_of_mass(shape2)

            com_distance = ((com2[0] - com1[0])**2 +
                          (com2[1] - com1[1])**2 +
                          (com2[2] - com1[2])**2)**0.5

            return {
                'bounding_box_diff': bbox_diff,
                'volume': {
                    'old': vol1,
                    'new': vol2,
                    'delta': vol_delta,
                    'percent_change': round(vol_percent_change, 2)
                },
                'center_of_mass': {
                    'old': com1,
                    'new': com2,
                    'distance': com_distance
                },
                'geometry_changed': (
                    abs(vol_percent_change) > 0.1 or
                    com_distance > 0.1
                )
            }

        except Exception as e:
            logger.exception(f"Error comparing geometry: {e}")
            return {'error': str(e)}

    @staticmethod
    def calculate_similarity(header1: Dict, header2: Dict,
                            shape1: Optional['TopoDS_Shape'] = None,
                            shape2: Optional['TopoDS_Shape'] = None) -> float:
        """
        Calcula score de similitud entre dos archivos

        Args:
            header1: Header 1
            header2: Header 2
            shape1: Shape 1 (opcional)
            shape2: Shape 2 (opcional)

        Returns:
            Score de similitud 0.0 - 1.0
        """
        scores = []

        # 1. Similitud de estructura (40%)
        total_entities1 = header1.get('total_entities', 0)
        total_entities2 = header2.get('total_entities', 0)

        if total_entities1 > 0 and total_entities2 > 0:
            entity_ratio = min(total_entities1, total_entities2) / max(total_entities1, total_entities2)
            scores.append(('structure', entity_ratio, 0.4))

        # 2. Similitud de schema (10%)
        schema1 = header1.get('file_schema', '')
        schema2 = header2.get('file_schema', '')
        schema_match = 1.0 if schema1 == schema2 else 0.5
        scores.append(('schema', schema_match, 0.1))

        # 3. Similitud geométrica (50%)
        if shape1 and shape2 and PYTHONOCC_AVAILABLE:
            try:
                vol1 = ComparisonTools._get_volume(shape1)
                vol2 = ComparisonTools._get_volume(shape2)

                if vol1 > 0 and vol2 > 0:
                    vol_ratio = min(vol1, vol2) / max(vol1, vol2)
                    scores.append(('geometry', vol_ratio, 0.5))
            except:
                pass

        # Calcular score ponderado
        if not scores:
            return 0.0

        total_weight = sum(s[2] for s in scores)
        weighted_sum = sum(s[1] * s[2] for s in scores)

        return round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.0

    @staticmethod
    def detect_entity_changes(entities1: List[Dict],
                             entities2: List[Dict]) -> Dict:
        """
        Detecta entidades añadidas, eliminadas y modificadas

        Args:
            entities1: Lista de entidades del archivo 1
            entities2: Lista de entidades del archivo 2

        Returns:
            Dict con cambios detectados
        """
        # Crear mapas por ID, con manejo de None
        map1 = {e['entity_id']: e for e in (entities1 or []) if 'entity_id' in e}
        map2 = {e['entity_id']: e for e in (entities2 or []) if 'entity_id' in e}

        ids1 = set(map1.keys())
        ids2 = set(map2.keys())

        added = ids2 - ids1
        removed = ids1 - ids2
        common = ids1 & ids2

        # Detectar modificados
        modified = []
        for entity_id in common:
            e1 = map1[entity_id]
            e2 = map2[entity_id]

            # Comparar tipo y atributos básicos
            if (e1.get('entity_type') != e2.get('entity_type') or
                e1.get('attributes') != e2.get('attributes')):
                modified.append(entity_id)

        return {
            'added': list(added),
            'removed': list(removed),
            'modified': modified,
            'unchanged': list(common - set(modified)),
            'total_changes': len(added) + len(removed) + len(modified)
        }

    @staticmethod
    def generate_change_summary(metadata_diff: Dict,
                               structure_diff: Dict,
                               geometry_diff: Dict,
                               entity_changes: Optional[Dict] = None) -> Dict:
        """
        Genera resumen de cambios

        Args:
            metadata_diff: Diferencias de metadatos
            structure_diff: Diferencias de estructura
            geometry_diff: Diferencias de geometría
            entity_changes: Cambios de entidades (opcional)

        Returns:
            Dict con resumen
        """
        summary = {
            'metadata_changes': metadata_diff.get('change_count', 0),
            'structure_changed': structure_diff.get('structure_changed', False),
            'geometry_changed': geometry_diff.get('geometry_changed', False),
            'has_changes': False
        }

        if entity_changes:
            summary['entities_added'] = len(entity_changes.get('added', []))
            summary['entities_removed'] = len(entity_changes.get('removed', []))
            summary['entities_modified'] = len(entity_changes.get('modified', []))
            summary['total_entity_changes'] = entity_changes.get('total_changes', 0)

        summary['has_changes'] = (
            summary['metadata_changes'] > 0 or
            summary['structure_changed'] or
            summary['geometry_changed'] or
            summary.get('total_entity_changes', 0) > 0
        )

        return summary

    @staticmethod
    def create_comparison_result(file1_header: Dict,
                                 file2_header: Dict,
                                 shape1: Optional['TopoDS_Shape'] = None,
                                 shape2: Optional['TopoDS_Shape'] = None) -> ComparisonResult:
        """
        Crea resultado completo de comparación

        Args:
            file1_header: Header del archivo 1
            file2_header: Header del archivo 2
            shape1: Shape 1 (opcional)
            shape2: Shape 2 (opcional)

        Returns:
            ComparisonResult object
        """
        import uuid

        # Ejecutar comparaciones
        metadata_diff = ComparisonTools.compare_metadata(file1_header, file2_header)
        structure_diff = ComparisonTools.compare_structure(file1_header, file2_header)
        geometry_diff = ComparisonTools.compare_geometry(shape1, shape2) if shape1 and shape2 else {}

        # Calcular similitud
        similarity = ComparisonTools.calculate_similarity(
            file1_header,
            file2_header,
            shape1,
            shape2
        )

        # Generar resumen
        change_summary = ComparisonTools.generate_change_summary(
            metadata_diff,
            structure_diff,
            geometry_diff
        )

        return ComparisonResult(
            comparison_id=str(uuid.uuid4()),
            file1_id=str(file1_header.get('id', '')),
            file2_id=str(file2_header.get('id', '')),
            file1_name=file1_header.get('file_name', 'File 1'),
            file2_name=file2_header.get('file_name', 'File 2'),
            change_summary=change_summary,
            metadata_diff=metadata_diff,
            structure_diff=structure_diff,
            geometry_diff=geometry_diff,
            similarity_score=similarity,
            compared_at=datetime.utcnow().isoformat()
        )

    # Helper methods

    @staticmethod
    def _compare_distributions(dist1: Dict, dist2: Dict) -> Dict:
        """Compara dos distribuciones"""
        # Manejar casos donde dist1 o dist2 pueden ser None
        dist1 = dist1 or {}
        dist2 = dist2 or {}

        all_keys = set(list(dist1.keys()) + list(dist2.keys()))

        changes = {}
        for key in all_keys:
            val1 = dist1.get(key, 0)
            val2 = dist2.get(key, 0)
            delta = val2 - val1

            if delta != 0:
                changes[key] = {
                    'old': val1,
                    'new': val2,
                    'delta': delta
                }

        return changes

    @staticmethod
    def _get_bounding_box(shape: 'TopoDS_Shape') -> Dict:
        """Obtiene bounding box de una forma"""
        bbox = Bnd_Box()
        brepbndlib_Add(shape, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        return {
            'min': [xmin, ymin, zmin],
            'max': [xmax, ymax, zmax],
            'dimensions': [xmax - xmin, ymax - ymin, zmax - zmin]
        }

    @staticmethod
    def _get_volume(shape: 'TopoDS_Shape') -> float:
        """Calcula volumen de una forma"""
        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)
        return props.Mass()

    @staticmethod
    def _get_center_of_mass(shape: 'TopoDS_Shape') -> Tuple[float, float, float]:
        """Calcula centro de masa"""
        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)
        com = props.CentreOfMass()
        return (com.X(), com.Y(), com.Z())


class VersionManager:
    """
    Gestor de versiones de archivos STEP
    """

    @staticmethod
    def create_version_hash(file_path: str) -> str:
        """
        Crea hash único para un archivo

        Args:
            file_path: Ruta al archivo

        Returns:
            Hash SHA-256
        """
        sha256 = hashlib.sha256()

        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)

        return sha256.hexdigest()

    @staticmethod
    def create_version_metadata(header: Dict, version_number: int) -> Dict:
        """
        Crea metadatos de versión

        Args:
            header: Header del archivo
            version_number: Número de versión

        Returns:
            Dict con metadatos de versión
        """
        return {
            'version_number': version_number,
            'header_id': str(header.get('id', '')),
            'file_name': header.get('file_name', ''),
            'file_hash': header.get('file_hash', ''),
            'total_entities': header.get('total_entities', 0),
            'created_at': datetime.utcnow().isoformat(),
            'author': header.get('author', ''),
            'organization': header.get('organization', '')
        }


logger.info("OK Comparison Tools module loaded")
