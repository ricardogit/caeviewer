"""
Graph Builder - Construcción y manipulación del grafo de entidades STEP
Autor: STEP Benchmark Team
Versión: 1.0.0
"""

import logging
from typing import Dict, List, Optional
from sqlalchemy import text
from datetime import datetime

from app.step_view_pro.models import STEPFileHeader, STEPEntity
from app.extensions import db

logger = logging.getLogger(__name__)


class GraphBuilder:
    """
    Constructor y navegador del grafo de entidades STEP

    Funcionalidades:
    - Computar árbol jerárquico completo
    - Búsqueda de rutas entre entidades
    - Análisis de conectividad
    - Detección de subgrafos
    """

    def __init__(self, header_id: str):
        """
        Inicializa el builder para un archivo STEP específico

        Args:
            header_id: UUID del STEP file header
        """
        self.header_id = header_id
        self.header = STEPFileHeader.query.filter_by(id=header_id).first()

        if not self.header:
            raise ValueError(f"Header no encontrado: {header_id}")

        logger.info(f"GraphBuilder inicializado para header {header_id}")

    def compute_entity_tree(self, use_cache: bool = True) -> Dict:
        """
        Computa el árbol jerárquico de entidades desde las raíces

        Args:
            use_cache: Si True, usa árbol pre-computado si existe

        Returns:
            Dict con estructura de árbol:
            {
                "root": {...},
                "metadata": {
                    "total_nodes": int,
                    "max_depth": int,
                    "root_count": int
                }
            }
        """
        # Verificar cache
        if use_cache and self.header.entity_tree_json:
            logger.info(f"OK Árbol obtenido de cache pre-computado")
            return self.header.entity_tree_json

        logger.info(f"🔨 Computando árbol de entidades para {self.header_id}")

        # Query recursiva con CTE (Common Table Expression)
        query = text("""
            WITH RECURSIVE entity_tree AS (
                -- Nodos raíz (sin referencias entrantes)
                SELECT
                    id,
                    entity_id,
                    entity_type,
                    entity_label,
                    COALESCE(references_to, '{}') as references_to,
                    COALESCE(referenced_by, '{}') as referenced_by,
                    depth_level,
                    is_leaf,
                    is_root,
                    manufacturing_feature,
                    entity_category,
                    ARRAY[entity_id] as path,
                    0 as tree_depth
                FROM step_entities
                WHERE header_id = :header_id AND is_root = true

                UNION ALL

                -- Nodos hijos (recursión)
                SELECT
                    e.id,
                    e.entity_id,
                    e.entity_type,
                    e.entity_label,
                    COALESCE(e.references_to, '{}') as references_to,
                    COALESCE(e.referenced_by, '{}') as referenced_by,
                    e.depth_level,
                    e.is_leaf,
                    e.is_root,
                    e.manufacturing_feature,
                    e.entity_category,
                    et.path || e.entity_id,
                    et.tree_depth + 1
                FROM step_entities e
                INNER JOIN entity_tree et ON e.entity_id = ANY(et.references_to)
                WHERE e.header_id = :header_id
                  AND NOT (e.entity_id = ANY(et.path))  -- Evitar ciclos
                  AND et.tree_depth < 50  -- Límite de profundidad
            )
            SELECT * FROM entity_tree
            ORDER BY tree_depth, entity_id;
        """)

        try:
            result = db.session.execute(query, {'header_id': self.header_id})
            rows = result.fetchall()
        except Exception as e:
            logger.error(f"Error executing entity tree query for header {self.header_id}: {e}")
            # Fallback: Get entities without recursive tree structure
            entities = STEPEntity.query.filter_by(header_id=self.header_id).all()
            logger.info(f"Fallback: Loaded {len(entities)} entities without tree structure")
            return {
                'roots': [
                    {
                        'entity_id': e.entity_id,
                        'entity_type': e.entity_type,
                        'entity_label': e.entity_label,
                        'depth_level': e.depth_level,
                        'tree_depth': 0,
                        'is_leaf': e.is_leaf,
                        'manufacturing_feature': e.manufacturing_feature,
                        'entity_category': e.entity_category,
                        'children': []
                    }
                    for e in entities if e.is_root
                ] if any(getattr(e, 'is_root', False) for e in entities) else [
                    {
                        'entity_id': e.entity_id,
                        'entity_type': e.entity_type,
                        'entity_label': e.entity_label,
                        'depth_level': e.depth_level,
                        'tree_depth': 0,
                        'is_leaf': e.is_leaf,
                        'manufacturing_feature': e.manufacturing_feature,
                        'entity_category': e.entity_category,
                        'children': []
                    }
                    for e in entities
                ],
                'metadata': {
                    'total_nodes': len(entities),
                    'max_depth': max((getattr(e, 'depth_level', 0) or 0) for e in entities) if entities else 0,
                    'root_count': len([e for e in entities if getattr(e, 'is_root', False)]) if entities else 0,
                    'header_id': str(self.header_id),
                    'timestamp': datetime.utcnow().isoformat()
                }
            }

        if not rows:
            logger.warning("No se encontraron entidades raíz")
            return {
                'roots': [],
                'metadata': {
                    'total_nodes': 0,
                    'max_depth': 0,
                    'root_count': 0
                }
            }

        # Construir estructura de árbol
        nodes_by_id = {}
        roots = []
        max_depth = 0

        for row in rows:
            node = {
                'entity_id': row.entity_id,
                'entity_type': row.entity_type,
                'entity_label': row.entity_label,
                'depth_level': row.depth_level,
                'tree_depth': row.tree_depth,
                'is_leaf': row.is_leaf,
                'manufacturing_feature': row.manufacturing_feature,
                'entity_category': row.entity_category,
                'children': []
            }

            nodes_by_id[row.entity_id] = node
            max_depth = max(max_depth, row.tree_depth)

            if row.is_root:
                roots.append(node)

        # Conectar padres con hijos
        for row in rows:
            if row.references_to and isinstance(row.references_to, list):
                for child_id in row.references_to:
                    if child_id in nodes_by_id:
                        parent = nodes_by_id[row.entity_id]
                        child = nodes_by_id[child_id]
                        if child not in parent['children']:
                            parent['children'].append(child)

        tree_data = {
            'roots': roots,
            'metadata': {
                'total_nodes': len(rows),
                'max_depth': max_depth,
                'root_count': len(roots),
                'header_id': str(self.header_id),
                'timestamp': datetime.utcnow().isoformat()
            }
        }

        logger.info(
            f"OK Árbol computado: {len(rows)} nodos, "
            f"{len(roots)} raíces, profundidad {max_depth}"
        )

        return tree_data

    def save_tree_to_cache(self, tree_data: Dict) -> None:
        """
        Guarda árbol computado en el header para futuras consultas

        Args:
            tree_data: Datos del árbol generados por compute_entity_tree
        """
        self.header.entity_tree_json = tree_data
        db.session.commit()

        logger.info(f"OK Árbol guardado en cache (header.entity_tree_json)")

    def get_entity_path_to_root(self, entity_id: int) -> List[Dict]:
        """
        Obtiene el camino desde una entidad hasta la raíz

        Args:
            entity_id: ID de la entidad STEP

        Returns:
            Lista de nodos desde entidad → raíz
        """
        # Query recursiva hacia arriba
        query = text("""
            WITH RECURSIVE path_to_root AS (
                -- Nodo inicial
                SELECT
                    entity_id,
                    entity_type,
                    entity_label,
                    COALESCE(referenced_by, '{}') as referenced_by,
                    0 as distance
                FROM step_entities
                WHERE header_id = :header_id AND entity_id = :entity_id

                UNION ALL

                -- Padres (los que referencian este nodo)
                SELECT
                    e.entity_id,
                    e.entity_type,
                    e.entity_label,
                    COALESCE(e.referenced_by, '{}') as referenced_by,
                    ptr.distance + 1
                FROM step_entities e
                INNER JOIN path_to_root ptr ON e.entity_id = ANY(ptr.referenced_by)
                WHERE e.header_id = :header_id AND ptr.distance < 20
            )
            SELECT * FROM path_to_root ORDER BY distance DESC;
        """)

        result = db.session.execute(
            query,
            {'header_id': self.header_id, 'entity_id': entity_id}
        )

        path = [
            {
                'entity_id': row.entity_id,
                'entity_type': row.entity_type,
                'entity_label': row.entity_label,
                'distance_to_target': row.distance
            }
            for row in result
        ]

        logger.info(f"Camino a raíz desde #{entity_id}: {len(path)} nodos")
        return path

    def get_subtree(self, entity_id: int, max_depth: int = 5) -> Dict:
        """
        Obtiene subárbol desde una entidad específica

        Args:
            entity_id: ID de la entidad raíz del subárbol
            max_depth: Profundidad máxima a explorar

        Returns:
            Dict con subárbol desde esa entidad
        """
        query = text("""
            WITH RECURSIVE subtree AS (
                -- Nodo raíz del subárbol
                SELECT
                    entity_id,
                    entity_type,
                    entity_label,
                    COALESCE(references_to, '{}') as references_to,
                    manufacturing_feature,
                    0 as depth
                FROM step_entities
                WHERE header_id = :header_id AND entity_id = :entity_id

                UNION ALL

                -- Hijos
                SELECT
                    e.entity_id,
                    e.entity_type,
                    e.entity_label,
                    COALESCE(e.references_to, '{}') as references_to,
                    e.manufacturing_feature,
                    st.depth + 1
                FROM step_entities e
                INNER JOIN subtree st ON e.entity_id = ANY(st.references_to)
                WHERE e.header_id = :header_id AND st.depth < :max_depth
            )
            SELECT * FROM subtree ORDER BY depth, entity_id;
        """)

        result = db.session.execute(
            query,
            {
                'header_id': self.header_id,
                'entity_id': entity_id,
                'max_depth': max_depth
            }
        )

        # Construir árbol
        nodes = {}
        root = None

        for row in result:
            node = {
                'entity_id': row.entity_id,
                'entity_type': row.entity_type,
                'entity_label': row.entity_label,
                'manufacturing_feature': row.manufacturing_feature,
                'depth': row.depth,
                'children': []
            }

            nodes[row.entity_id] = node

            if row.depth == 0:
                root = node

        # Conectar relaciones
        for row in result:
            if row.references_to and isinstance(row.references_to, list):
                for child_id in row.references_to:
                    if child_id in nodes:
                        nodes[row.entity_id]['children'].append(nodes[child_id])

        return {
            'root': root,
            'node_count': len(nodes),
            'max_depth_reached': max([n['depth'] for n in nodes.values()])
        }

    def get_neighbors(self, entity_id: int, distance: int = 1) -> Dict:
        """
        Obtiene vecindario de una entidad (N-hop neighbors)

        Args:
            entity_id: ID de la entidad central
            distance: Distancia máxima (número de saltos)

        Returns:
            Dict con nodo central y vecinos
        """
        entity = STEPEntity.query.filter_by(
            header_id=self.header_id,
            entity_id=entity_id
        ).first()

        if not entity:
            return {'error': 'Entity not found'}

        # Obtener vecinos directos
        neighbor_ids = set()

        if entity.references_to and isinstance(entity.references_to, list):
            neighbor_ids.update(entity.references_to)

        if entity.referenced_by and isinstance(entity.referenced_by, list):
            neighbor_ids.update(entity.referenced_by)

        # Si distance > 1, expandir vecindario
        if distance > 1:
            for _ in range(distance - 1):
                current_neighbors = list(neighbor_ids)
                for nid in current_neighbors:
                    n = STEPEntity.query.filter_by(
                        header_id=self.header_id,
                        entity_id=nid
                    ).first()

                    if n:
                        if n.references_to and isinstance(n.references_to, list):
                            neighbor_ids.update(n.references_to)
                        if n.referenced_by and isinstance(n.referenced_by, list):
                            neighbor_ids.update(n.referenced_by)

        # Cargar vecinos
        neighbors = STEPEntity.query.filter(
            STEPEntity.header_id == self.header_id,
            STEPEntity.entity_id.in_(list(neighbor_ids))
        ).all()

        # Construir edges
        edges = []
        for neighbor in neighbors:
            if (entity.references_to and isinstance(entity.references_to, list) and
                neighbor.entity_id in entity.references_to):
                edges.append({
                    'source': entity_id,
                    'target': neighbor.entity_id,
                    'type': 'references'
                })
            if (entity.referenced_by and isinstance(entity.referenced_by, list) and
                neighbor.entity_id in entity.referenced_by):
                edges.append({
                    'source': neighbor.entity_id,
                    'target': entity_id,
                    'type': 'referenced_by'
                })

        return {
            'center': {
                'entity_id': entity.entity_id,
                'entity_type': entity.entity_type,
                'entity_label': entity.entity_label
            },
            'neighbors': [
                {
                    'entity_id': n.entity_id,
                    'entity_type': n.entity_type,
                    'entity_label': n.entity_label
                }
                for n in neighbors
            ],
            'edges': edges,
            'neighbor_count': len(neighbors)
        }

    def search_entities(
        self,
        query: Optional[str] = None,
        entity_type: Optional[str] = None,
        manufacturing_feature: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Busca entidades por criterios

        Args:
            query: Texto a buscar en tipo o label
            entity_type: Filtro por tipo exacto
            manufacturing_feature: Filtro por feature
            limit: Máximo de resultados

        Returns:
            Lista de entidades encontradas
        """
        q = STEPEntity.query.filter_by(header_id=self.header_id)

        if query:
            q = q.filter(
                db.or_(
                    STEPEntity.entity_type.ilike(f'%{query}%'),
                    STEPEntity.entity_label.ilike(f'%{query}%')
                )
            )

        if entity_type:
            q = q.filter_by(entity_type=entity_type)

        if manufacturing_feature:
            q = q.filter_by(manufacturing_feature=manufacturing_feature)

        entities = q.limit(limit).all()

        return [
            {
                'entity_id': e.entity_id,
                'entity_type': e.entity_type,
                'entity_label': e.entity_label,
                'depth_level': e.depth_level,
                'is_leaf': e.is_leaf,
                'manufacturing_feature': e.manufacturing_feature,
                'entity_category': e.entity_category
            }
            for e in entities
        ]


# Función de utilidad para inicializar árboles pre-computados
def precompute_all_trees():
    """
    Pre-computa árboles para todos los headers que no los tienen

    Útil para ejecutar en background después de importar archivos
    """
    headers = STEPFileHeader.query.filter(
        STEPFileHeader.entity_tree_json.is_(None)
    ).all()

    logger.info(f"Pre-computando árboles para {len(headers)} headers...")

    for header in headers:
        try:
            builder = GraphBuilder(str(header.id))
            tree = builder.compute_entity_tree(use_cache=False)
            builder.save_tree_to_cache(tree)

            logger.info(f"OK Árbol pre-computado para {header.id}")

        except Exception as e:
            logger.error(f"X Error pre-computando {header.id}: {e}")

    logger.info("OK Pre-computación completada")


if __name__ == '__main__':
    # Test
    logging.basicConfig(level=logging.INFO)
    print("GraphBuilder Test")
    print("=" * 50)

    # Requiere un header_id válido
    # builder = GraphBuilder('your-header-uuid')
    # tree = builder.compute_entity_tree()
    # print(f"Árbol: {tree['metadata']}")
