"""
Validators - Validación de calidad y detección de anomalías en archivos STEP
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Validación de estructura STEP
- Validación de referencias
- Detección de anomalías
- Checks de calidad
- Reglas de negocio
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Resultado de validación"""
    is_valid: bool
    score: float  # 0-100
    errors: List[Dict]
    warnings: List[Dict]
    info: List[Dict]

    def to_dict(self):
        return asdict(self)


class STEPValidator:
    """
    Validador de archivos STEP
    """

    # Tipos de entidades requeridas en archivos STEP válidos
    REQUIRED_ENTITY_TYPES = {
        'CARTESIAN_POINT',
        'DIRECTION',
        'AXIS2_PLACEMENT_3D'
    }

    # Tipos de entidades comunes
    COMMON_ENTITY_TYPES = {
        'MANIFOLD_SOLID_BREP',
        'ADVANCED_BREP_SHAPE_REPRESENTATION',
        'SHAPE_REPRESENTATION',
        'PRODUCT',
        'PRODUCT_DEFINITION'
    }

    @staticmethod
    def validate_structure(header: Dict, entities: List[Dict]) -> ValidationResult:
        """
        Valida estructura básica del archivo STEP

        Args:
            header: Header del archivo
            entities: Lista de entidades

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        info = []

        # Check 1: Archivo no vacío
        if not entities:
            errors.append({
                'code': 'EMPTY_FILE',
                'severity': 'error',
                'message': 'File contains no entities'
            })
            return ValidationResult(
                is_valid=False,
                score=0,
                errors=errors,
                warnings=warnings,
                info=info
            )

        # Check 2: Schema válido
        valid_schemas = {'AP203', 'AP214', 'AP214CD', 'AP242', 'AUTOMOTIVE_DESIGN'}
        file_schema = header.get('file_schema', '')

        if file_schema not in valid_schemas:
            warnings.append({
                'code': 'UNKNOWN_SCHEMA',
                'severity': 'warning',
                'message': f'Schema {file_schema} is not standard. Expected one of: {valid_schemas}'
            })

        # Check 3: Entidades requeridas
        entity_types = set(e.get('entity_type', '') for e in entities)
        missing_required = STEPValidator.REQUIRED_ENTITY_TYPES - entity_types

        if missing_required:
            warnings.append({
                'code': 'MISSING_REQUIRED_ENTITIES',
                'severity': 'warning',
                'message': f'Missing required entity types: {missing_required}'
            })

        # Check 4: Entidades comunes
        has_common = bool(entity_types & STEPValidator.COMMON_ENTITY_TYPES)

        if not has_common:
            info.append({
                'code': 'NO_COMMON_ENTITIES',
                'severity': 'info',
                'message': 'File does not contain common geometric entities'
            })

        # Check 5: IDs únicos
        entity_ids = [e.get('entity_id') for e in entities]
        duplicates = [eid for eid in entity_ids if entity_ids.count(eid) > 1]

        if duplicates:
            errors.append({
                'code': 'DUPLICATE_IDS',
                'severity': 'error',
                'message': f'Found {len(set(duplicates))} duplicate entity IDs'
            })

        # Calculate score
        error_penalty = len(errors) * 20
        warning_penalty = len(warnings) * 5
        score = max(0, 100 - error_penalty - warning_penalty)

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            score=score,
            errors=errors,
            warnings=warnings,
            info=info
        )

    @staticmethod
    def validate_references(entities: List[Dict]) -> ValidationResult:
        """
        Valida referencias entre entidades

        Args:
            entities: Lista de entidades

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        info = []

        all_ids = set(e.get('entity_id') for e in entities)

        # Validar cada entidad
        broken_refs = []
        circular_refs = []

        for entity in entities:
            entity_id = entity.get('entity_id')
            references = entity.get('references', [])

            # Check: Referencias válidas
            for ref in references:
                if ref not in all_ids:
                    broken_refs.append({
                        'from': entity_id,
                        'to': ref
                    })

                # Check: Referencia circular directa
                if ref == entity_id:
                    circular_refs.append(entity_id)

        if broken_refs:
            errors.append({
                'code': 'BROKEN_REFERENCES',
                'severity': 'error',
                'message': f'Found {len(broken_refs)} broken references',
                'details': broken_refs[:10]  # Primeros 10
            })

        if circular_refs:
            warnings.append({
                'code': 'CIRCULAR_REFERENCES',
                'severity': 'warning',
                'message': f'Found {len(circular_refs)} entities with self-references',
                'details': circular_refs[:10]
            })

        # Calculate score
        error_penalty = min(len(broken_refs), 5) * 20
        warning_penalty = min(len(circular_refs), 10) * 2
        score = max(0, 100 - error_penalty - warning_penalty)

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            score=score,
            errors=errors,
            warnings=warnings,
            info=info
        )

    @staticmethod
    def validate_complete(header: Dict, entities: List[Dict]) -> ValidationResult:
        """
        Validación completa (estructura + referencias)

        Args:
            header: Header del archivo
            entities: Lista de entidades

        Returns:
            ValidationResult combinado
        """
        struct_result = STEPValidator.validate_structure(header, entities)
        ref_result = STEPValidator.validate_references(entities)

        # Combinar resultados
        combined_errors = struct_result.errors + ref_result.errors
        combined_warnings = struct_result.warnings + ref_result.warnings
        combined_info = struct_result.info + ref_result.info

        combined_score = (struct_result.score + ref_result.score) / 2
        is_valid = struct_result.is_valid and ref_result.is_valid

        return ValidationResult(
            is_valid=is_valid,
            score=combined_score,
            errors=combined_errors,
            warnings=combined_warnings,
            info=combined_info
        )


class AnomalyDetector:
    """
    Detector de anomalías en archivos STEP
    """

    @staticmethod
    def detect_size_anomalies(headers: List[Dict], current_header: Dict) -> Dict:
        """
        Detecta anomalías de tamaño

        Args:
            headers: Lista de headers históricos
            current_header: Header actual

        Returns:
            Dict con anomalías detectadas
        """
        if len(headers) < 5:
            return {'anomalies': [], 'insufficient_data': True}

        # Extraer tamaños
        sizes = [h.get('file_size_bytes', 0) for h in headers if h.get('file_size_bytes')]

        if not sizes:
            return {'anomalies': [], 'no_data': True}

        import numpy as np

        # Calcular estadísticas
        mean = np.mean(sizes)
        std = np.std(sizes)

        current_size = current_header.get('file_size_bytes', 0)

        # Detectar anomalía (> 3 sigma)
        z_score = abs((current_size - mean) / std) if std > 0 else 0

        anomalies = []

        if z_score > 3:
            anomalies.append({
                'type': 'size_anomaly',
                'severity': 'high' if z_score > 5 else 'medium',
                'message': f'File size is {z_score:.1f} standard deviations from mean',
                'current': current_size,
                'mean': round(mean, 2),
                'z_score': round(z_score, 2)
            })

        return {
            'anomalies': anomalies,
            'stats': {
                'mean': round(mean, 2),
                'std': round(std, 2),
                'current': current_size,
                'z_score': round(z_score, 2)
            }
        }

    @staticmethod
    def detect_complexity_anomalies(headers: List[Dict], current_header: Dict) -> Dict:
        """
        Detecta anomalías de complejidad

        Args:
            headers: Lista de headers históricos
            current_header: Header actual

        Returns:
            Dict con anomalías detectadas
        """
        if len(headers) < 5:
            return {'anomalies': [], 'insufficient_data': True}

        # Extraer entity counts
        entity_counts = [h.get('total_entities', 0) for h in headers]

        if not entity_counts:
            return {'anomalies': [], 'no_data': True}

        import numpy as np

        mean = np.mean(entity_counts)
        std = np.std(entity_counts)

        current_count = current_header.get('total_entities', 0)

        z_score = abs((current_count - mean) / std) if std > 0 else 0

        anomalies = []

        if z_score > 3:
            anomalies.append({
                'type': 'complexity_anomaly',
                'severity': 'high' if z_score > 5 else 'medium',
                'message': f'Entity count is {z_score:.1f} standard deviations from mean',
                'current': current_count,
                'mean': round(mean, 2),
                'z_score': round(z_score, 2)
            })

        return {
            'anomalies': anomalies,
            'stats': {
                'mean': round(mean, 2),
                'std': round(std, 2),
                'current': current_count,
                'z_score': round(z_score, 2)
            }
        }

    @staticmethod
    def detect_all_anomalies(headers: List[Dict], current_header: Dict) -> Dict:
        """
        Detecta todas las anomalías

        Args:
            headers: Lista de headers históricos
            current_header: Header actual

        Returns:
            Dict con todas las anomalías
        """
        size_anomalies = AnomalyDetector.detect_size_anomalies(headers, current_header)
        complexity_anomalies = AnomalyDetector.detect_complexity_anomalies(headers, current_header)

        all_anomalies = (
            size_anomalies.get('anomalies', []) +
            complexity_anomalies.get('anomalies', [])
        )

        return {
            'total_anomalies': len(all_anomalies),
            'anomalies': all_anomalies,
            'size_analysis': size_anomalies,
            'complexity_analysis': complexity_anomalies
        }


class QualityChecker:
    """
    Verificador de calidad
    """

    @staticmethod
    def check_naming_conventions(entities: List[Dict]) -> Dict:
        """
        Verifica convenciones de nombres

        Args:
            entities: Lista de entidades

        Returns:
            Dict con resultados
        """
        issues = []

        # Check: IDs deben ser numéricos precedidos por #
        for entity in entities[:100]:  # Muestra de 100
            entity_id = entity.get('entity_id', '')

            if not entity_id:
                continue

            if not entity_id.startswith('#'):
                issues.append({
                    'entity_id': entity_id,
                    'issue': 'ID does not start with #'
                })

        return {
            'issues': issues,
            'sample_size': min(len(entities), 100),
            'passed': len(issues) == 0
        }

    @staticmethod
    def check_geometry_validity(entities: List[Dict]) -> Dict:
        """
        Verifica validez geométrica básica

        Args:
            entities: Lista de entidades

        Returns:
            Dict con resultados
        """
        issues = []

        # Buscar entidades geométricas
        geometric_types = {
            'CARTESIAN_POINT',
            'DIRECTION',
            'VERTEX_POINT',
            'EDGE_CURVE'
        }

        geometric_entities = [
            e for e in entities
            if e.get('entity_type') in geometric_types
        ]

        if not geometric_entities:
            issues.append({
                'type': 'no_geometry',
                'severity': 'warning',
                'message': 'No geometric entities found'
            })

        return {
            'geometric_entity_count': len(geometric_entities),
            'total_entity_count': len(entities),
            'percentage': round(len(geometric_entities) / len(entities) * 100, 2) if entities else 0,
            'issues': issues,
            'has_geometry': len(geometric_entities) > 0
        }


logger.info("OK Validators module loaded")
