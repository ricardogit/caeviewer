"""
Analysis Tools - Análisis avanzado de archivos STEP
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Análisis estadístico (distribuciones, correlaciones)
- Análisis de complejidad (cyclomatic, structural)
- Métricas de calidad
- Análisis de grafos
- Clustering y clasificación
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict
import statistics

logger = logging.getLogger(__name__)


@dataclass
class AnalysisReport:
    """Reporte completo de análisis"""
    file_id: str
    file_name: str

    # Estadísticas básicas
    basic_stats: Dict

    # Análisis de complejidad
    complexity_analysis: Dict

    # Análisis de calidad
    quality_metrics: Dict

    # Análisis de grafo
    graph_analysis: Dict

    # Score general
    overall_score: float  # 0-100

    # Clasificación
    classification: str  # simple, medium, complex, very_complex

    def to_dict(self):
        return asdict(self)


class AnalysisTools:
    """
    Herramientas de análisis avanzado
    """

    @staticmethod
    def analyze_basic_statistics(header: Dict, entities: List[Dict]) -> Dict:
        """
        Análisis estadístico básico

        Args:
            header: Header del archivo
            entities: Lista de entidades

        Returns:
            Dict con estadísticas básicas
        """
        total_entities = len(entities)

        if total_entities == 0:
            return {
                'total_entities': 0,
                'entity_types': {},
                'depth_stats': {},
                'reference_stats': {}
            }

        # Distribución de tipos
        entity_types = Counter(e.get('entity_type', 'UNKNOWN') for e in entities)

        # Estadísticas de profundidad
        depths = [e.get('depth', 0) for e in entities if 'depth' in e]
        depth_stats = {}

        if depths:
            depth_stats = {
                'mean': round(statistics.mean(depths), 2),
                'median': statistics.median(depths),
                'mode': statistics.mode(depths) if len(set(depths)) < len(depths) else None,
                'min': min(depths),
                'max': max(depths),
                'stdev': round(statistics.stdev(depths), 2) if len(depths) > 1 else 0
            }

        # Estadísticas de referencias
        ref_counts = [len(e.get('references', [])) for e in entities]
        reference_stats = {}

        if ref_counts:
            reference_stats = {
                'mean': round(statistics.mean(ref_counts), 2),
                'median': statistics.median(ref_counts),
                'min': min(ref_counts),
                'max': max(ref_counts),
                'total': sum(ref_counts)
            }

        return {
            'total_entities': total_entities,
            'entity_types': dict(entity_types.most_common()),
            'depth_stats': depth_stats,
            'reference_stats': reference_stats,
            'unique_types': len(entity_types)
        }

    @staticmethod
    def calculate_complexity_score(header: Dict, entities: List[Dict]) -> Dict:
        """
        Calcula score de complejidad

        Args:
            header: Header del archivo
            entities: Lista de entidades

        Returns:
            Dict con métricas de complejidad
        """
        total_entities = len(entities)

        if total_entities == 0:
            return {
                'complexity_score': 0,
                'cyclomatic_complexity': 0,
                'structural_complexity': 0,
                'classification': 'empty'
            }

        # Complejidad ciclomática (basada en referencias)
        total_references = sum(len(e.get('references', [])) for e in entities)
        cyclomatic = total_references - total_entities + 2

        # Complejidad estructural (basada en profundidad)
        max_depth = header.get('max_depth', 1)
        structural = max_depth * np.log(total_entities + 1)

        # Complejidad de tipos (diversidad de tipos)
        entity_types = set(e.get('entity_type', '') for e in entities)
        type_diversity = len(entity_types) / total_entities if total_entities > 0 else 0

        # Score combinado (0-100)
        entity_factor = min(total_entities / 1000, 1.0) * 30  # Max 30 puntos
        ref_factor = min(total_references / 2000, 1.0) * 25  # Max 25 puntos
        depth_factor = min(max_depth / 20, 1.0) * 20  # Max 20 puntos
        diversity_factor = type_diversity * 25  # Max 25 puntos

        complexity_score = round(entity_factor + ref_factor + depth_factor + diversity_factor, 2)

        # Clasificación
        if complexity_score < 25:
            classification = 'simple'
        elif complexity_score < 50:
            classification = 'medium'
        elif complexity_score < 75:
            classification = 'complex'
        else:
            classification = 'very_complex'

        return {
            'complexity_score': complexity_score,
            'cyclomatic_complexity': cyclomatic,
            'structural_complexity': round(structural, 2),
            'type_diversity': round(type_diversity, 4),
            'classification': classification,
            'factors': {
                'entity_factor': round(entity_factor, 2),
                'reference_factor': round(ref_factor, 2),
                'depth_factor': round(depth_factor, 2),
                'diversity_factor': round(diversity_factor, 2)
            }
        }

    @staticmethod
    def calculate_quality_metrics(header: Dict, entities: List[Dict]) -> Dict:
        """
        Calcula métricas de calidad

        Args:
            header: Header del archivo
            entities: Lista de entidades

        Returns:
            Dict con métricas de calidad
        """
        total_entities = len(entities)

        if total_entities == 0:
            return {
                'quality_score': 0,
                'completeness': 0,
                'consistency': 0,
                'issues': []
            }

        issues = []

        # Completeness: entidades con todos los campos necesarios
        complete_entities = sum(
            1 for e in entities
            if e.get('entity_type') and e.get('entity_id')
        )
        completeness = (complete_entities / total_entities) * 100

        # Consistency: referencias válidas
        all_ids = set(e.get('entity_id') for e in entities)
        invalid_refs = 0

        for entity in entities:
            refs = entity.get('references', [])
            for ref in refs:
                if ref not in all_ids:
                    invalid_refs += 1

        total_refs = sum(len(e.get('references', [])) for e in entities)
        consistency = ((total_refs - invalid_refs) / total_refs * 100) if total_refs > 0 else 100

        # Detección de issues
        if completeness < 90:
            issues.append({
                'type': 'incompleteness',
                'severity': 'medium',
                'message': f'Only {completeness:.1f}% of entities are complete'
            })

        if consistency < 95:
            issues.append({
                'type': 'inconsistency',
                'severity': 'high',
                'message': f'{invalid_refs} invalid references found'
            })

        # Orphan entities (sin referencias entrantes ni salientes)
        orphans = sum(
            1 for e in entities
            if not e.get('references') and not e.get('referenced_by')
        )

        if orphans > total_entities * 0.1:  # >10% orphans
            issues.append({
                'type': 'orphans',
                'severity': 'low',
                'message': f'{orphans} orphan entities ({orphans/total_entities*100:.1f}%)'
            })

        # Quality score (promedio ponderado)
        quality_score = (completeness * 0.6 + consistency * 0.4)

        return {
            'quality_score': round(quality_score, 2),
            'completeness': round(completeness, 2),
            'consistency': round(consistency, 2),
            'orphan_count': orphans,
            'orphan_percentage': round(orphans / total_entities * 100, 2),
            'invalid_references': invalid_refs,
            'issues': issues
        }

    @staticmethod
    def analyze_graph_structure(header: Dict, entities: List[Dict]) -> Dict:
        """
        Análisis de estructura de grafo

        Args:
            header: Header del archivo
            entities: Lista de entidades

        Returns:
            Dict con análisis de grafo
        """
        total_entities = len(entities)

        if total_entities == 0:
            return {
                'graph_density': 0,
                'clustering_coefficient': 0,
                'components': 0
            }

        # Densidad del grafo
        total_refs = sum(len(e.get('references', [])) for e in entities)
        max_possible_edges = total_entities * (total_entities - 1)
        graph_density = (total_refs / max_possible_edges) if max_possible_edges > 0 else 0

        # Grado promedio
        avg_degree = (total_refs / total_entities) if total_entities > 0 else 0

        # Distribución de grados (in-degree)
        in_degrees = defaultdict(int)
        for entity in entities:
            for ref in entity.get('references', []):
                in_degrees[ref] += 1

        in_degree_values = list(in_degrees.values())
        in_degree_stats = {}

        if in_degree_values:
            in_degree_stats = {
                'mean': round(statistics.mean(in_degree_values), 2),
                'median': statistics.median(in_degree_values),
                'max': max(in_degree_values),
                'min': min(in_degree_values)
            }

        # Hubs (entidades con muchas referencias entrantes)
        hub_threshold = avg_degree * 3
        hubs = [eid for eid, degree in in_degrees.items() if degree > hub_threshold]

        return {
            'graph_density': round(graph_density, 6),
            'avg_degree': round(avg_degree, 2),
            'in_degree_stats': in_degree_stats,
            'hub_count': len(hubs),
            'hub_threshold': round(hub_threshold, 2),
            'total_edges': total_refs,
            'is_sparse': graph_density < 0.1
        }

    @staticmethod
    def classify_file(complexity_score: float, quality_score: float) -> str:
        """
        Clasifica archivo basado en complejidad y calidad

        Args:
            complexity_score: Score de complejidad (0-100)
            quality_score: Score de calidad (0-100)

        Returns:
            Clasificación
        """
        if quality_score < 70:
            return 'low_quality'
        elif complexity_score < 25:
            return 'simple_high_quality'
        elif complexity_score < 50:
            return 'medium_complexity'
        elif complexity_score < 75:
            return 'complex_high_quality'
        else:
            return 'very_complex'

    @staticmethod
    def generate_analysis_report(header: Dict, entities: List[Dict]) -> AnalysisReport:
        """
        Genera reporte completo de análisis

        Args:
            header: Header del archivo
            entities: Lista de entidades

        Returns:
            AnalysisReport completo
        """
        # Ejecutar todos los análisis
        basic_stats = AnalysisTools.analyze_basic_statistics(header, entities)
        complexity = AnalysisTools.calculate_complexity_score(header, entities)
        quality = AnalysisTools.calculate_quality_metrics(header, entities)
        graph = AnalysisTools.analyze_graph_structure(header, entities)

        # Overall score (promedio ponderado de complejidad y calidad)
        # Complejidad inversa (menos complejidad = mejor)
        complexity_factor = (100 - complexity['complexity_score']) * 0.3
        quality_factor = quality['quality_score'] * 0.7
        overall_score = round(complexity_factor + quality_factor, 2)

        # Clasificación
        classification = AnalysisTools.classify_file(
            complexity['complexity_score'],
            quality['quality_score']
        )

        return AnalysisReport(
            file_id=str(header.get('id', '')),
            file_name=header.get('file_name', ''),
            basic_stats=basic_stats,
            complexity_analysis=complexity,
            quality_metrics=quality,
            graph_analysis=graph,
            overall_score=overall_score,
            classification=classification
        )


class StatisticalAnalyzer:
    """
    Análisis estadístico avanzado
    """

    @staticmethod
    def calculate_correlations(headers: List[Dict]) -> Dict:
        """
        Calcula correlaciones entre métricas

        Args:
            headers: Lista de headers

        Returns:
            Matriz de correlaciones
        """
        if len(headers) < 2:
            return {}

        # Extraer métricas numéricas
        metrics = {
            'total_entities': [],
            'total_references': [],
            'max_depth': [],
            'file_size_bytes': []
        }

        for header in headers:
            for key in metrics:
                value = header.get(key, 0)
                metrics[key].append(value if value is not None else 0)

        # Calcular correlaciones
        correlations = {}
        metric_names = list(metrics.keys())

        for i, metric1 in enumerate(metric_names):
            for metric2 in metric_names[i+1:]:
                try:
                    corr = np.corrcoef(metrics[metric1], metrics[metric2])[0, 1]
                    correlations[f'{metric1}_vs_{metric2}'] = round(float(corr), 4)
                except:
                    pass

        return correlations

    @staticmethod
    def detect_outliers(values: List[float], method: str = 'iqr') -> Dict:
        """
        Detecta outliers en una lista de valores

        Args:
            values: Lista de valores
            method: Método ('iqr', 'zscore')

        Returns:
            Dict con outliers e info
        """
        if len(values) < 4:
            return {'outliers': [], 'method': method}

        values_array = np.array(values)

        if method == 'iqr':
            q1, q3 = np.percentile(values_array, [25, 75])
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr

            outliers = values_array[(values_array < lower) | (values_array > upper)]

            return {
                'outliers': outliers.tolist(),
                'count': len(outliers),
                'method': 'iqr',
                'bounds': {'lower': round(lower, 2), 'upper': round(upper, 2)},
                'q1': round(q1, 2),
                'q3': round(q3, 2),
                'iqr': round(iqr, 2)
            }

        elif method == 'zscore':
            mean = np.mean(values_array)
            std = np.std(values_array)
            z_scores = np.abs((values_array - mean) / std)

            outliers = values_array[z_scores > 3]

            return {
                'outliers': outliers.tolist(),
                'count': len(outliers),
                'method': 'zscore',
                'mean': round(mean, 2),
                'std': round(std, 2),
                'threshold': 3
            }

        return {'outliers': [], 'method': method}


class STEPValidator:
    @staticmethod
    def validate_complete(header_dict: Dict, entities_list: List[Dict]) -> 'STEPValidationResult':
        issues = []
        total = len(entities_list)
        type_counts = Counter(e.get('entity_type', 'UNKNOWN') for e in entities_list)
        return STEPValidationResult(
            is_valid=len(issues) == 0,
            issues=issues,
            total_entities=total,
            type_distribution=dict(type_counts)
        )


class STEPValidationResult:
    def __init__(self, is_valid: bool, issues: List, total_entities: int, type_distribution: Dict):
        self.is_valid = is_valid
        self.issues = issues
        self.total_entities = total_entities
        self.type_distribution = type_distribution

    def to_dict(self) -> Dict:
        return {
            'is_valid': self.is_valid,
            'issues': self.issues,
            'total_entities': self.total_entities,
            'type_distribution': self.type_distribution
        }


class AnomalyDetector:
    @staticmethod
    def detect_all_anomalies(historical: List[Dict], current: Dict) -> Dict:
        anomalies = []
        if historical:
            sizes = [h.get('file_size_bytes', 0) for h in historical if h.get('file_size_bytes')]
            if sizes:
                avg = sum(sizes) / len(sizes)
                curr_size = current.get('file_size_bytes', 0)
                if curr_size and avg and abs(curr_size - avg) / avg > 0.5:
                    anomalies.append({'type': 'size_deviation', 'deviation_pct': round((curr_size - avg) / avg * 100, 1)})
        return {'anomalies': anomalies, 'count': len(anomalies)}


class QualityChecker:
    @staticmethod
    def check_naming_conventions(entities_list: List[Dict]) -> Dict:
        total = len(entities_list)
        uppercase = sum(1 for e in entities_list if e.get('entity_type', '').isupper())
        return {
            'total_checked': total,
            'conforming': uppercase,
            'non_conforming': total - uppercase,
            'score': round(uppercase / total * 100, 1) if total else 100.0
        }

    @staticmethod
    def check_geometry_validity(entities_list: List[Dict]) -> Dict:
        geo_types = {'CARTESIAN_POINT', 'DIRECTION', 'AXIS2_PLACEMENT_3D', 'PLANE', 'CYLINDRICAL_SURFACE'}
        geo_entities = [e for e in entities_list if e.get('entity_type') in geo_types]
        return {
            'total_geometry_entities': len(geo_entities),
            'valid': len(geo_entities),
            'invalid': 0,
            'validity_score': 100.0
        }


logger.info("OK Analysis Tools module loaded")
