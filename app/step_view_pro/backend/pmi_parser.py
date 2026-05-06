"""
PMI Parser - Extracción de Product Manufacturing Information desde STEP files
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Dimensions (length, diameter, radius, angle)
- GD&T (Geometric Dimensioning and Tolerancing)
- Surface finish specifications
- Notes and annotations
- Datum reference frames
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import re

from app.step_view_pro.models import STEPEntity, STEPFileHeader
from app.extensions import db

logger = logging.getLogger(__name__)


@dataclass
class PMIAnnotation:
    """Representación de una anotación PMI"""
    pmi_id: str  # UUID único
    pmi_type: str  # DIMENSION, GD&T, SURFACE_FINISH, NOTE, DATUM
    subtype: Optional[str] = None  # LINEAR, ANGULAR, DIAMETER, FLATNESS, etc.

    # Valor y unidades
    value: Optional[float] = None
    nominal_value: Optional[float] = None
    upper_tolerance: Optional[float] = None
    lower_tolerance: Optional[float] = None
    unit: Optional[str] = 'mm'

    # Texto de la anotación
    text: Optional[str] = None
    label: Optional[str] = None

    # GD&T específico
    tolerance_zone_shape: Optional[str] = None  # CYLINDRICAL, SPHERICAL, etc.
    datum_references: Optional[List[str]] = None  # ['A', 'B', 'C']
    material_condition: Optional[str] = None  # MMC, LMC, RFS

    # Posición en 3D
    position: Optional[Tuple[float, float, float]] = None
    leader_line: Optional[List[Tuple[float, float, float]]] = None

    # Entidades relacionadas
    entity_ids: List[int] = None
    target_entity_id: Optional[int] = None

    # Metadata
    confidence: float = 1.0
    extraction_method: str = "pmi_parser"
    notes: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class PMIParser:
    """
    Parser de Product Manufacturing Information desde archivos STEP
    """

    def __init__(self, header_id: str):
        """
        Args:
            header_id: UUID del STEP file header
        """
        self.header_id = header_id
        self.annotations: List[PMIAnnotation] = []

        # GD&T symbols mapping
        self.gdt_symbols = {
            'STRAIGHTNESS': '⏤',
            'FLATNESS': '⏥',
            'CIRCULARITY': '○',
            'CYLINDRICITY': '⌭',
            'PROFILE_OF_LINE': '⌓',
            'PROFILE_OF_SURFACE': '⌔',
            'PERPENDICULARITY': '⊥',
            'ANGULARITY': '∠',
            'PARALLELISM': '∥',
            'POSITION': '⌖',
            'CONCENTRICITY': '◎',
            'SYMMETRY': '⌯',
            'CIRCULAR_RUNOUT': '↗',
            'TOTAL_RUNOUT': '↗↗'
        }

    def parse_pmi_from_entities(self) -> List[PMIAnnotation]:
        """
        Extrae PMI desde entidades STEP ya parseadas.
        Si no hay entidades en BD, cae al parser de texto directo.
        """
        logger.info(f"Parsing PMI for header {self.header_id}")

        entities = STEPEntity.query.filter_by(header_id=self.header_id).all()

        if entities:
            entities_by_type = {}
            for entity in entities:
                etype = entity.entity_type
                if etype not in entities_by_type:
                    entities_by_type[etype] = []
                entities_by_type[etype].append(entity)

            self._parse_dimensions(entities_by_type)
            self._parse_geometric_tolerances(entities_by_type)
            self._parse_surface_finish(entities_by_type)
            self._parse_datums(entities_by_type)
            self._parse_notes(entities_by_type)
        else:
            logger.info(f"No STEPEntity records found for {self.header_id}, trying direct file parse")
            self._parse_from_step_file()

        logger.info(f"Extracted {len(self.annotations)} PMI annotations")
        return self.annotations

    def _parse_from_step_file(self):
        """
        Fallback: extrae PMI leyendo directamente el texto del archivo STEP.
        Usado cuando los archivos CAPP no tienen STEPEntity en BD.
        """
        header = STEPFileHeader.query.get(self.header_id)
        if not header or not header.part:
            logger.warning(f"Cannot find STEP file path for header {self.header_id}")
            return

        file_path = header.part.file_path
        if not file_path:
            logger.warning(f"Part has no file_path for header {self.header_id}")
            return

        import os
        if not os.path.exists(file_path):
            logger.warning(f"STEP file not found on disk: {file_path}")
            return

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Could not read STEP file {file_path}: {e}")
            return

        self._extract_dimensions_from_text(content)
        self._extract_tolerances_from_text(content)
        self._extract_datums_from_text(content)
        self._extract_notes_from_text(content)

    def _extract_dimensions_from_text(self, content: str):
        """Extrae dimensiones buscando entidades de dimensión en texto STEP."""
        patterns = [
            (r'#(\d+)\s*=\s*LENGTH_DIMENSION\s*\(([^)]*)\)', 'LINEAR'),
            (r'#(\d+)\s*=\s*DIAMETER_DIMENSION\s*\(([^)]*)\)', 'DIAMETER'),
            (r'#(\d+)\s*=\s*RADIUS_DIMENSION\s*\(([^)]*)\)', 'RADIUS'),
            (r'#(\d+)\s*=\s*ANGULAR_DIMENSION\s*\(([^)]*)\)', 'ANGULAR'),
            (r'#(\d+)\s*=\s*DIMENSION_CURVE_DIRECTED_CALLOUT\s*\(([^)]*)\)', 'LINEAR'),
        ]
        import re
        for pattern, dim_type in patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                entity_id = match.group(1)
                args = match.group(2)
                value = self._extract_numeric_value(args)
                if value:
                    self.annotations.append(PMIAnnotation(
                        pmi_id=f"DIM_{entity_id}",
                        pmi_type='DIMENSION',
                        subtype=dim_type,
                        value=value,
                        nominal_value=value,
                        entity_ids=[int(entity_id)],
                        confidence=0.8,
                        extraction_method="direct_text"
                    ))

    def _extract_tolerances_from_text(self, content: str):
        """Extrae GD&T buscando entidades de tolerancia en texto STEP."""
        import re
        tol_types = [
            'FLATNESS_TOLERANCE', 'STRAIGHTNESS_TOLERANCE',
            'PERPENDICULARITY_TOLERANCE', 'PARALLELISM_TOLERANCE',
            'ANGULARITY_TOLERANCE', 'POSITION_TOLERANCE',
            'CONCENTRICITY_TOLERANCE', 'CIRCULARITY_TOLERANCE',
            'CYLINDRICITY_TOLERANCE', 'GEOMETRIC_TOLERANCE',
        ]
        for tol_name in tol_types:
            pattern = rf'#(\d+)\s*=\s*{tol_name}\s*\(([^)]*)\)'
            for match in re.finditer(pattern, content, re.IGNORECASE):
                entity_id = match.group(1)
                args = match.group(2)
                value = self._extract_numeric_value(args)
                base_type = tol_name.replace('_TOLERANCE', '')
                self.annotations.append(PMIAnnotation(
                    pmi_id=f"GDT_{entity_id}",
                    pmi_type='GD&T',
                    subtype=base_type,
                    value=value,
                    text=f"{self.gdt_symbols.get(base_type, '')} {value or ''}",
                    entity_ids=[int(entity_id)],
                    confidence=0.85,
                    extraction_method="direct_text"
                ))

    def _extract_datums_from_text(self, content: str):
        """Extrae datums desde texto STEP."""
        import re
        for match in re.finditer(r"#(\d+)\s*=\s*DATUM_FEATURE\s*\('([^']*)'", content, re.IGNORECASE):
            entity_id, label = match.group(1), match.group(2)
            self.annotations.append(PMIAnnotation(
                pmi_id=f"DATUM_{entity_id}",
                pmi_type='DATUM',
                label=label,
                text=f"Datum {label}",
                entity_ids=[int(entity_id)],
                confidence=0.9,
                extraction_method="direct_text"
            ))

    def _extract_notes_from_text(self, content: str):
        """Extrae notas/texto de anotación desde texto STEP."""
        import re
        for match in re.finditer(
            r"#(\d+)\s*=\s*(?:DRAUGHTING_TEXT_LITERAL_WITH_DELINEATION|ANNOTATION_TEXT)\s*\('([^']{3,})'",
            content, re.IGNORECASE
        ):
            entity_id, text = match.group(1), match.group(2)
            if text.strip():
                self.annotations.append(PMIAnnotation(
                    pmi_id=f"NOTE_{entity_id}",
                    pmi_type='NOTE',
                    text=text.strip(),
                    entity_ids=[int(entity_id)],
                    confidence=0.75,
                    extraction_method="direct_text"
                ))

    @staticmethod
    def _extract_numeric_value(args_str: str) -> Optional[float]:
        """Extrae el primer número flotante de una cadena de argumentos STEP."""
        import re
        match = re.search(r'[\s,](\d+\.?\d*(?:E[+-]?\d+)?)', args_str, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def _parse_dimensions(self, entities_by_type: Dict):
        """
        Parsea dimensiones (length, diameter, radius, angle)

        Busca:
        - DIMENSION_CURVE_DIRECTED_CALLOUT
        - LENGTH_DIMENSION
        - DIAMETER_DIMENSION
        - RADIUS_DIMENSION
        - ANGULAR_DIMENSION
        """
        # DIMENSION_CURVE_DIRECTED_CALLOUT
        callouts = entities_by_type.get('DIMENSION_CURVE_DIRECTED_CALLOUT', [])

        for callout in callouts:
            try:
                attrs = callout.entity_attributes or {}

                # Obtener nombre de la dimensión
                name = attrs.get('name', '')

                # Buscar el valor en entidades referenciadas
                refs = callout.references_to or []
                dimension_value = None
                dimension_type = 'LINEAR'

                for ref_id in refs:
                    ref_entity = STEPEntity.query.filter_by(
                        header_id=self.header_id,
                        entity_id=ref_id
                    ).first()

                    if not ref_entity:
                        continue

                    ref_type = ref_entity.entity_type
                    ref_attrs = ref_entity.entity_attributes or {}

                    # LENGTH_MEASURE_WITH_UNIT
                    if 'LENGTH_MEASURE' in ref_type or 'MEASURE_WITH_UNIT' in ref_type:
                        dimension_value = ref_attrs.get('value_component')
                        dimension_type = 'LINEAR'

                    # Determinar si es diameter, radius, angle
                    if 'DIAMETER' in name.upper() or 'DIA' in name.upper() or 'Ø' in name:
                        dimension_type = 'DIAMETER'
                    elif 'RADIUS' in name.upper() or 'RAD' in name.upper() or 'R' in name:
                        dimension_type = 'RADIUS'
                    elif 'ANGLE' in name.upper() or '°' in name:
                        dimension_type = 'ANGULAR'

                if dimension_value:
                    annotation = PMIAnnotation(
                        pmi_id=f"DIM_{callout.entity_id}",
                        pmi_type='DIMENSION',
                        subtype=dimension_type,
                        value=float(dimension_value) if dimension_value else None,
                        nominal_value=float(dimension_value) if dimension_value else None,
                        text=name,
                        label=name,
                        entity_ids=[callout.entity_id],
                        confidence=0.9,
                        extraction_method="dimension_callout"
                    )

                    self.annotations.append(annotation)

            except Exception as e:
                logger.debug(f"Error parsing dimension callout {callout.entity_id}: {e}")

        # LENGTH_DIMENSION, DIAMETER_DIMENSION, etc.
        for dim_type in ['LENGTH_DIMENSION', 'DIAMETER_DIMENSION', 'RADIUS_DIMENSION', 'ANGULAR_DIMENSION']:
            dimensions = entities_by_type.get(dim_type, [])

            for dim in dimensions:
                try:
                    attrs = dim.entity_attributes or {}
                    value = attrs.get('value')

                    if value:
                        subtype_map = {
                            'LENGTH_DIMENSION': 'LINEAR',
                            'DIAMETER_DIMENSION': 'DIAMETER',
                            'RADIUS_DIMENSION': 'RADIUS',
                            'ANGULAR_DIMENSION': 'ANGULAR'
                        }

                        annotation = PMIAnnotation(
                            pmi_id=f"DIM_{dim.entity_id}",
                            pmi_type='DIMENSION',
                            subtype=subtype_map.get(dim_type, 'LINEAR'),
                            value=float(value),
                            nominal_value=float(value),
                            entity_ids=[dim.entity_id],
                            confidence=0.95,
                            extraction_method="typed_dimension"
                        )

                        self.annotations.append(annotation)

                except Exception as e:
                    logger.debug(f"Error parsing {dim_type}: {e}")

    def _parse_geometric_tolerances(self, entities_by_type: Dict):
        """
        Parsea tolerancias geométricas (GD&T)

        Busca:
        - GEOMETRIC_TOLERANCE
        - GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE
        - FLATNESS_TOLERANCE
        - PERPENDICULARITY_TOLERANCE
        - POSITION_TOLERANCE
        - etc.
        """
        # GEOMETRIC_TOLERANCE
        tolerances = entities_by_type.get('GEOMETRIC_TOLERANCE', [])

        for tolerance in tolerances:
            try:
                attrs = tolerance.entity_attributes or {}

                tolerance_type = attrs.get('type', 'UNKNOWN')
                tolerance_value = attrs.get('magnitude')

                # Obtener datum references
                datum_refs = []
                refs = tolerance.references_to or []
                for ref_id in refs:
                    ref_entity = STEPEntity.query.filter_by(
                        header_id=self.header_id,
                        entity_id=ref_id
                    ).first()

                    if ref_entity and 'DATUM' in ref_entity.entity_type:
                        datum_label = ref_entity.entity_attributes.get('name', '')
                        if datum_label:
                            datum_refs.append(datum_label)

                annotation = PMIAnnotation(
                    pmi_id=f"GDT_{tolerance.entity_id}",
                    pmi_type='GD&T',
                    subtype=tolerance_type,
                    value=float(tolerance_value) if tolerance_value else None,
                    datum_references=datum_refs if datum_refs else None,
                    text=f"{self.gdt_symbols.get(tolerance_type, '')} {tolerance_value or ''}",
                    entity_ids=[tolerance.entity_id],
                    confidence=0.9,
                    extraction_method="geometric_tolerance"
                )

                self.annotations.append(annotation)

            except Exception as e:
                logger.debug(f"Error parsing geometric tolerance: {e}")

        # Tolerances específicas
        specific_tolerances = [
            'FLATNESS_TOLERANCE',
            'STRAIGHTNESS_TOLERANCE',
            'PERPENDICULARITY_TOLERANCE',
            'PARALLELISM_TOLERANCE',
            'ANGULARITY_TOLERANCE',
            'POSITION_TOLERANCE',
            'CONCENTRICITY_TOLERANCE',
            'CIRCULARITY_TOLERANCE',
            'CYLINDRICITY_TOLERANCE'
        ]

        for tol_type in specific_tolerances:
            tols = entities_by_type.get(tol_type, [])

            for tol in tols:
                try:
                    attrs = tol.entity_attributes or {}
                    value = attrs.get('magnitude') or attrs.get('value')

                    # Extraer tipo base
                    base_type = tol_type.replace('_TOLERANCE', '')

                    annotation = PMIAnnotation(
                        pmi_id=f"GDT_{tol.entity_id}",
                        pmi_type='GD&T',
                        subtype=base_type,
                        value=float(value) if value else None,
                        text=f"{self.gdt_symbols.get(base_type, '')} {value or ''}",
                        entity_ids=[tol.entity_id],
                        confidence=0.95,
                        extraction_method="specific_tolerance"
                    )

                    self.annotations.append(annotation)

                except Exception as e:
                    logger.debug(f"Error parsing {tol_type}: {e}")

    def _parse_surface_finish(self, entities_by_type: Dict):
        """
        Parsea especificaciones de acabado superficial

        Busca:
        - SURFACE_TEXTURE_PARAMETER
        - SURFACE_FINISH
        """
        surface_params = entities_by_type.get('SURFACE_TEXTURE_PARAMETER', [])

        for param in surface_params:
            try:
                attrs = param.entity_attributes or {}

                parameter_type = attrs.get('parameter_type', 'Ra')  # Ra, Rz, etc.
                value = attrs.get('parameter_value')

                annotation = PMIAnnotation(
                    pmi_id=f"SURF_{param.entity_id}",
                    pmi_type='SURFACE_FINISH',
                    subtype=parameter_type,
                    value=float(value) if value else None,
                    text=f"{parameter_type} {value or ''}",
                    unit='μm',
                    entity_ids=[param.entity_id],
                    confidence=0.85,
                    extraction_method="surface_texture"
                )

                self.annotations.append(annotation)

            except Exception as e:
                logger.debug(f"Error parsing surface texture: {e}")

    def _parse_datums(self, entities_by_type: Dict):
        """
        Parsea datum reference frames

        Busca:
        - DATUM_FEATURE
        - DATUM_TARGET
        - PLACED_DATUM_TARGET_FEATURE
        """
        datums = entities_by_type.get('DATUM_FEATURE', [])

        for datum in datums:
            try:
                attrs = datum.entity_attributes or {}

                datum_label = attrs.get('name', '') or attrs.get('identification', '')

                annotation = PMIAnnotation(
                    pmi_id=f"DATUM_{datum.entity_id}",
                    pmi_type='DATUM',
                    label=datum_label,
                    text=f"Datum {datum_label}",
                    entity_ids=[datum.entity_id],
                    confidence=0.95,
                    extraction_method="datum_feature"
                )

                self.annotations.append(annotation)

            except Exception as e:
                logger.debug(f"Error parsing datum: {e}")

    def _parse_notes(self, entities_by_type: Dict):
        """
        Parsea notas y anotaciones de texto

        Busca:
        - DRAUGHTING_TEXT_LITERAL_WITH_DELINEATION
        - ANNOTATION_TEXT
        - NOTE
        """
        text_entities = entities_by_type.get('DRAUGHTING_TEXT_LITERAL_WITH_DELINEATION', [])

        for text_ent in text_entities:
            try:
                attrs = text_ent.entity_attributes or {}

                text_content = attrs.get('literal', '') or attrs.get('text', '')

                if text_content:
                    annotation = PMIAnnotation(
                        pmi_id=f"NOTE_{text_ent.entity_id}",
                        pmi_type='NOTE',
                        text=text_content,
                        entity_ids=[text_ent.entity_id],
                        confidence=0.8,
                        extraction_method="draughting_text"
                    )

                    self.annotations.append(annotation)

            except Exception as e:
                logger.debug(f"Error parsing note: {e}")

    def save_to_database(self):
        """
        Guarda las anotaciones PMI en la base de datos

        Actualiza el campo pmi_annotations de STEPFileHeader
        """
        if not self.annotations:
            logger.warning("No PMI annotations to save")
            return 0

        try:
            header = STEPFileHeader.query.get(self.header_id)
            if not header:
                logger.error(f"Header {self.header_id} not found")
                return 0

            # Serializar anotaciones
            pmi_data = {
                'total_annotations': len(self.annotations),
                'annotations_by_type': {},
                'annotations': []
            }

            # Agrupar por tipo
            for annotation in self.annotations:
                pmi_type = annotation.pmi_type
                if pmi_type not in pmi_data['annotations_by_type']:
                    pmi_data['annotations_by_type'][pmi_type] = 0
                pmi_data['annotations_by_type'][pmi_type] += 1

                pmi_data['annotations'].append(annotation.to_dict())

            # Guardar en header
            header.pmi_annotations = pmi_data
            db.session.commit()

            logger.info(f"Saved {len(self.annotations)} PMI annotations to header {self.header_id}")
            return len(self.annotations)

        except Exception as e:
            logger.exception(f"Error saving PMI annotations: {e}")
            db.session.rollback()
            return 0


def extract_pmi_for_file(header_id: str) -> Dict:
    """
    Función de conveniencia para extraer PMI de un archivo

    Args:
        header_id: UUID del header

    Returns:
        Dict con resultados de la extracción
    """
    parser = PMIParser(header_id)
    annotations = parser.parse_pmi_from_entities()
    saved_count = parser.save_to_database()

    # Agrupar por tipo
    annotations_by_type = {}
    for annotation in annotations:
        ptype = annotation.pmi_type
        if ptype not in annotations_by_type:
            annotations_by_type[ptype] = []
        annotations_by_type[ptype].append(annotation.to_dict())

    return {
        'total_annotations': len(annotations),
        'annotations_by_type': annotations_by_type,
        'saved_to_db': saved_count,
        'annotations': [a.to_dict() for a in annotations]
    }


logger.info("OK PMI Parser module loaded")
