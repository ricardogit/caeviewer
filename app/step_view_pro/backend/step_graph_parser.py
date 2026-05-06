"""
STEP Graph Parser - Parser de archivos STEP para extracción de grafo de entidades
===================================================================================

Utiliza pythonocc-core para parsear archivos STEP y extraer:
- Entidades y sus relaciones
- Metadata del archivo
- Categorización de entidades

Author: STEP-View Pro Team
Version: 1.0.0
"""

import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import re

# PythonOCC imports
try:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.Interface import Interface_Static
    from OCC.Core.TCollection import TCollection_AsciiString
    from OCC.Core.STEPConstruct import stepconstruct_FindEntity
    from OCC.Core.TopoDS import TopoDS_Shape
    PYTHONOCC_AVAILABLE = True
except ImportError:
    PYTHONOCC_AVAILABLE = False

logger = logging.getLogger(__name__)


class STEPGraphParser:
    """
    Parser de archivos STEP que extrae el grafo completo de entidades.

    Funcionalidades:
    - Parse de archivo STEP
    - Extracción de entidades y referencias
    - Categorización automática de entidades
    - Cálculo de métricas del grafo
    """

    # Categorías de entidades STEP
    GEOMETRY_ENTITIES = {
        'CARTESIAN_POINT', 'DIRECTION', 'VECTOR',
        'AXIS1_PLACEMENT', 'AXIS2_PLACEMENT_3D',
        'LINE', 'CIRCLE', 'ELLIPSE', 'PARABOLA', 'HYPERBOLA',
        'B_SPLINE_CURVE', 'B_SPLINE_CURVE_WITH_KNOTS',
        'RATIONAL_B_SPLINE_CURVE', 'COMPOSITE_CURVE',
        'TRIMMED_CURVE', 'BOUNDED_CURVE', 'CONIC'
    }

    SURFACE_ENTITIES = {
        'PLANE', 'CYLINDRICAL_SURFACE', 'CONICAL_SURFACE',
        'SPHERICAL_SURFACE', 'TOROIDAL_SURFACE',
        'B_SPLINE_SURFACE', 'B_SPLINE_SURFACE_WITH_KNOTS',
        'RATIONAL_B_SPLINE_SURFACE', 'SURFACE_OF_REVOLUTION',
        'SURFACE_OF_LINEAR_EXTRUSION'
    }

    TOPOLOGY_ENTITIES = {
        'VERTEX_POINT', 'EDGE_CURVE', 'ORIENTED_EDGE',
        'FACE_SURFACE', 'FACE_BOUND', 'FACE_OUTER_BOUND',
        'ADVANCED_FACE', 'CLOSED_SHELL', 'OPEN_SHELL',
        'SHELL_BASED_SURFACE_MODEL', 'MANIFOLD_SOLID_BREP',
        'BREP_WITH_VOIDS', 'FACETED_BREP', 'ORIENTED_CLOSED_SHELL'
    }

    SHAPE_ENTITIES = {
        'ADVANCED_BREP_SHAPE_REPRESENTATION',
        'MANIFOLD_SURFACE_SHAPE_REPRESENTATION',
        'GEOMETRICALLY_BOUNDED_SURFACE_SHAPE_REPRESENTATION',
        'SHAPE_REPRESENTATION', 'SHAPE_DEFINITION_REPRESENTATION'
    }

    PRODUCT_ENTITIES = {
        'PRODUCT', 'PRODUCT_DEFINITION', 'PRODUCT_DEFINITION_FORMATION',
        'PRODUCT_DEFINITION_SHAPE', 'NEXT_ASSEMBLY_USAGE_OCCURRENCE',
        'PRODUCT_RELATED_PRODUCT_CATEGORY'
    }

    def __init__(self):
        """Inicializar parser."""
        self.entities = []
        self.entity_count = 0
        self.metadata = {}

    def parse(self, file_path: str) -> Dict:
        """
        Parsear archivo STEP y extraer grafo de entidades.

        Args:
            file_path: Ruta al archivo STEP

        Returns:
            Dict con:
            - entity_count: Número total de entidades
            - entities: Lista de entidades con metadata
            - metadata: Metadata del archivo STEP
            - graph_metrics: Métricas del grafo
        """
        if not PYTHONOCC_AVAILABLE:
            logger.warning("pythonocc-core not available, using fallback text parser")
            return self._parse_text_fallback(file_path)

        try:
            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            logger.info(f"Parsing STEP file: {file_path}")

            # Crear reader
            step_reader = STEPControl_Reader()

            # Leer archivo
            status = step_reader.ReadFile(str(file_path))

            if status != IFSelect_RetDone:
                raise ValueError(f"Error reading STEP file: {status}")

            # Transferir entidades
            step_reader.TransferRoots()

            # Obtener metadata del header
            self.metadata = self._extract_header_metadata(file_path)

            # Parsear entidades del archivo de texto
            self.entities = self._parse_entities_from_text(file_path)
            self.entity_count = len(self.entities)

            # Calcular métricas del grafo
            graph_metrics = self._calculate_graph_metrics()

            logger.info(f"Parsed {self.entity_count} entities from {file_path.name}")

            return {
                'entity_count': self.entity_count,
                'entities': self.entities,
                'metadata': self.metadata,
                'graph_metrics': graph_metrics,
                'success': True
            }

        except Exception as e:
            logger.error(f"Error parsing STEP file: {e}", exc_info=True)
            return {
                'entity_count': 0,
                'entities': [],
                'metadata': {},
                'graph_metrics': {},
                'success': False,
                'error': str(e)
            }

    def _extract_header_metadata(self, file_path: Path) -> Dict:
        """
        Extraer metadata del HEADER section.

        Args:
            file_path: Ruta al archivo

        Returns:
            Dict con metadata del header
        """
        metadata = {
            'file_description': None,
            'file_name': None,
            'file_schema': None,
            'timestamp': None,
            'author': None,
            'organization': None,
            'preprocessor_version': None,
            'originating_system': None
        }

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

                # Extraer HEADER section
                header_match = re.search(r'HEADER;(.*?)ENDSEC;', content, re.DOTALL)
                if not header_match:
                    return metadata

                header = header_match.group(1)

                # FILE_DESCRIPTION
                desc_match = re.search(r"FILE_DESCRIPTION\s*\(\s*\('([^']+)'\)", header)
                if desc_match:
                    metadata['file_description'] = desc_match.group(1)

                # FILE_NAME
                name_match = re.search(r"FILE_NAME\s*\(\s*'([^']+)'", header)
                if name_match:
                    metadata['file_name'] = name_match.group(1)

                # FILE_SCHEMA
                schema_match = re.search(r"FILE_SCHEMA\s*\(\s*\('([^']+)'\)", header)
                if schema_match:
                    metadata['file_schema'] = schema_match.group(1)

        except Exception as e:
            logger.warning(f"Error extracting header metadata: {e}")

        return metadata

    def _parse_entities_from_text(self, file_path: Path) -> List[Dict]:
        """
        Parsear entidades desde el archivo de texto.

        Args:
            file_path: Ruta al archivo

        Returns:
            Lista de diccionarios con información de entidades
        """
        entities = []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

                # Extraer DATA section
                data_match = re.search(r'DATA;(.*?)ENDSEC;', content, re.DOTALL)
                if not data_match:
                    return entities

                data_section = data_match.group(1)

                # Pattern para entidades: #123 = ENTITY_TYPE(...)
                entity_pattern = r'#(\d+)\s*=\s*([A-Z_][A-Z0-9_]*)\s*\((.*?)\)\s*;'

                matches = re.finditer(entity_pattern, data_section, re.DOTALL)

                for match in matches:
                    entity_id = int(match.group(1))
                    entity_type = match.group(2)
                    params = match.group(3)

                    # Extraer referencias a otras entidades
                    references = self._extract_references(params)

                    # Categorizar entidad
                    category = self._categorize_entity(entity_type)

                    entities.append({
                        'entity_id': entity_id,
                        'entity_type': entity_type,
                        'entity_category': category,
                        'references': references,
                        'param_count': len(params.split(','))
                    })

        except Exception as e:
            logger.error(f"Error parsing entities from text: {e}", exc_info=True)

        return entities

    def _extract_references(self, params: str) -> List[int]:
        """
        Extraer referencias a otras entidades (#123).

        Args:
            params: String de parámetros

        Returns:
            Lista de IDs de entidades referenciadas
        """
        references = []
        ref_pattern = r'#(\d+)'

        for match in re.finditer(ref_pattern, params):
            ref_id = int(match.group(1))
            references.append(ref_id)

        return references

    def _categorize_entity(self, entity_type: str) -> str:
        """
        Categorizar entidad según su tipo.

        Args:
            entity_type: Tipo de entidad STEP

        Returns:
            Categoría de la entidad
        """
        if entity_type in self.GEOMETRY_ENTITIES:
            return 'GEOMETRY'
        elif entity_type in self.SURFACE_ENTITIES:
            return 'SURFACE'
        elif entity_type in self.TOPOLOGY_ENTITIES:
            return 'TOPOLOGY'
        elif entity_type in self.SHAPE_ENTITIES:
            return 'SHAPE'
        elif entity_type in self.PRODUCT_ENTITIES:
            return 'PRODUCT'
        else:
            return 'OTHER'

    def _calculate_graph_metrics(self) -> Dict:
        """
        Calcular métricas del grafo de entidades.

        Returns:
            Dict con métricas del grafo
        """
        if not self.entities:
            return {}

        # Contar por categoría
        category_counts = {}
        total_references = 0

        for entity in self.entities:
            category = entity['entity_category']
            category_counts[category] = category_counts.get(category, 0) + 1
            total_references += len(entity.get('references', []))

        # Calcular densidad del grafo
        max_possible_edges = self.entity_count * (self.entity_count - 1)
        graph_density = total_references / max_possible_edges if max_possible_edges > 0 else 0

        return {
            'total_entities': self.entity_count,
            'category_distribution': category_counts,
            'total_references': total_references,
            'avg_references_per_entity': total_references / self.entity_count if self.entity_count > 0 else 0,
            'graph_density': graph_density
        }

    def _parse_text_fallback(self, file_path: str) -> Dict:
        """
        Parser de texto simple como fallback cuando pythonocc no está disponible.

        Args:
            file_path: Ruta al archivo

        Returns:
            Dict con información básica del archivo
        """
        try:
            file_path = Path(file_path)

            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Contar entidades básicas
            entity_pattern = r'#(\d+)\s*=\s*([A-Z_][A-Z0-9_]*)'
            matches = re.findall(entity_pattern, content)

            entity_count = len(matches)

            return {
                'entity_count': entity_count,
                'entities': [],
                'metadata': self._extract_header_metadata(file_path),
                'graph_metrics': {},
                'success': True,
                'fallback_mode': True
            }

        except Exception as e:
            logger.error(f"Error in fallback parser: {e}", exc_info=True)
            return {
                'entity_count': 0,
                'entities': [],
                'metadata': {},
                'graph_metrics': {},
                'success': False,
                'error': str(e)
            }


# Instancia global para uso conveniente
_parser = None

def get_parser() -> STEPGraphParser:
    """Obtener instancia global del parser."""
    global _parser
    if _parser is None:
        _parser = STEPGraphParser()
    return _parser
