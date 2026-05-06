"""
Query Optimizer - Optimización de queries SQL y lazy loading
Versión: 1.0.0
Autor: STEP-View Pro Team

Soporta:
- Lazy loading de relaciones
- Query batching
- Pagination helpers
- Index suggestions
- Query analysis
"""

import logging
from typing import List, Dict, Optional, Any
from sqlalchemy import inspect, event
from sqlalchemy.orm import Query

logger = logging.getLogger(__name__)


class QueryOptimizer:
    """
    Optimizador de queries SQL
    """

    def __init__(self, db_session):
        """
        Inicializa optimizer

        Args:
            db_session: SQLAlchemy session
        """
        self.db = db_session
        self.query_log = []
        self.slow_query_threshold_ms = 1000  # 1 segundo

    def paginate(self, query: Query, page: int = 1, per_page: int = 50) -> Dict:
        """
        Paginación eficiente de queries

        Args:
            query: SQLAlchemy query
            page: Número de página (1-indexed)
            per_page: Resultados por página

        Returns:
            Dict con resultados y metadata de paginación
        """
        total = query.count()
        pages = (total + per_page - 1) // per_page  # Ceiling division

        offset = (page - 1) * per_page
        items = query.limit(per_page).offset(offset).all()

        return {
            'items': items,
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': pages,
            'has_prev': page > 1,
            'has_next': page < pages
        }

    def batch_load(self, model_class, ids: List[Any], batch_size: int = 100) -> List:
        """
        Carga en batch de objetos por IDs

        Args:
            model_class: Clase del modelo
            ids: Lista de IDs
            batch_size: Tamaño del batch

        Returns:
            Lista de objetos
        """
        results = []

        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_results = model_class.query.filter(
                model_class.id.in_(batch_ids)
            ).all()
            results.extend(batch_results)

        return results

    def lazy_load_column(self, query: Query, *columns) -> Query:
        """
        Lazy loading de columnas específicas

        Args:
            query: Query base
            *columns: Columnas a defer

        Returns:
            Query optimizado
        """
        from sqlalchemy.orm import defer

        for column in columns:
            query = query.options(defer(column))

        return query

    def eager_load_relationships(self, query: Query, *relationships) -> Query:
        """
        Eager loading de relaciones para evitar N+1

        Args:
            query: Query base
            *relationships: Relaciones a joinedload

        Returns:
            Query optimizado
        """
        from sqlalchemy.orm import joinedload

        for relationship in relationships:
            query = query.options(joinedload(relationship))

        return query

    def analyze_query(self, query: Query) -> Dict:
        """
        Analiza un query para detectar problemas de performance

        Args:
            query: Query a analizar

        Returns:
            Dict con análisis
        """
        # Obtener SQL statement
        statement = str(query.statement.compile(compile_kwargs={"literal_binds": True}))

        issues = []
        suggestions = []

        # Detectar JOINS
        if 'JOIN' in statement.upper():
            join_count = statement.upper().count('JOIN')
            if join_count > 3:
                issues.append(f"High number of JOINs ({join_count})")
                suggestions.append("Consider using eager loading or separate queries")

        # Detectar SELECT *
        if 'SELECT *' in statement.upper():
            issues.append("Using SELECT *")
            suggestions.append("Specify only needed columns for better performance")

        # Detectar falta de LIMIT
        if 'LIMIT' not in statement.upper():
            issues.append("No LIMIT clause")
            suggestions.append("Add LIMIT to prevent loading all results")

        # Detectar subqueries
        if statement.upper().count('SELECT') > 1:
            issues.append("Contains subqueries")
            suggestions.append("Consider flattening subqueries if possible")

        return {
            'statement': statement,
            'issues': issues,
            'suggestions': suggestions,
            'complexity_score': len(issues)
        }

    def suggest_indexes(self, model_class) -> List[Dict]:
        """
        Sugiere índices para un modelo

        Args:
            model_class: Clase del modelo

        Returns:
            Lista de sugerencias de índices
        """
        suggestions = []
        mapper = inspect(model_class)

        # Analizar columnas con foreign keys sin índice
        for column in mapper.columns:
            if column.foreign_keys and not any(
                column in idx.columns for idx in mapper.tables[0].indexes
            ):
                suggestions.append({
                    'table': mapper.tables[0].name,
                    'column': column.name,
                    'type': 'foreign_key',
                    'reason': 'Foreign key without index',
                    'suggested_index': f'idx_{mapper.tables[0].name}_{column.name}'
                })

        # Analizar relaciones
        for relationship in mapper.relationships:
            if not relationship.lazy:  # Eager loaded
                suggestions.append({
                    'table': mapper.tables[0].name,
                    'relationship': relationship.key,
                    'type': 'relationship',
                    'reason': 'Eager loaded relationship, ensure proper indexes',
                    'suggestion': 'Add index on foreign key columns'
                })

        return suggestions

    def enable_query_logging(self):
        """Habilita logging de queries"""
        @event.listens_for(self.db.get_bind(), "before_cursor_execute", retval=True)
        def receive_before_cursor_execute(conn, cursor, statement, params, context, executemany):
            context._query_start_time = time.time()
            return statement, params

        @event.listens_for(self.db.get_bind(), "after_cursor_execute")
        def receive_after_cursor_execute(conn, cursor, statement, params, context, executemany):
            duration_ms = (time.time() - context._query_start_time) * 1000

            query_info = {
                'statement': statement,
                'params': params,
                'duration_ms': duration_ms,
                'timestamp': datetime.utcnow().isoformat()
            }

            self.query_log.append(query_info)

            if duration_ms > self.slow_query_threshold_ms:
                logger.warning(f"SLOW QUERY ({duration_ms:.2f}ms): {statement[:200]}")

        logger.info("Query logging enabled")

    def get_slow_queries(self, threshold_ms: Optional[int] = None) -> List[Dict]:
        """
        Obtiene queries lentos del log

        Args:
            threshold_ms: Threshold custom (default: usar configurado)

        Returns:
            Lista de queries lentos
        """
        threshold = threshold_ms or self.slow_query_threshold_ms

        return [
            q for q in self.query_log
            if q['duration_ms'] > threshold
        ]

    def clear_query_log(self):
        """Limpia log de queries"""
        self.query_log.clear()
        logger.info("Query log cleared")


class LazyLoader:
    """
    Helper para lazy loading de datos pesados
    """

    @staticmethod
    def chunk_list(lst: List, chunk_size: int):
        """
        Divide lista en chunks

        Args:
            lst: Lista a dividir
            chunk_size: Tamaño del chunk

        Yields:
            Chunks de la lista
        """
        for i in range(0, len(lst), chunk_size):
            yield lst[i:i + chunk_size]

    @staticmethod
    def lazy_dict_values(data: Dict, keys: List[str]):
        """
        Carga lazy de valores de diccionario

        Args:
            data: Diccionario fuente
            keys: Keys a cargar

        Returns:
            Dict con valores solicitados
        """
        return {k: data[k] for k in keys if k in data}


# Import necesario para query logging
import time
from datetime import datetime


logger.info("OK Query Optimizer module loaded")
