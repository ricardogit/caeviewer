"""DesignGraphService — NetworkX-backed graph operations.

Full implementation: FASE 1.
"""
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    NX_AVAILABLE = True
except ImportError:
    NX_AVAILABLE = False
    logger.warning("networkx not installed — run: pip install networkx")

VALID_NODE_TYPES = {'CONCEPT', 'GEOMETRY', 'MATERIAL', 'BC', 'LOAD', 'RESULT', 'OPTIMIZATION'}
VALID_EDGE_TYPES = {'FUNCTIONAL', 'PHYSICAL', 'DEPENDS_ON', 'MANUFACTURED_BY', 'CONSTRAINS', 'PRODUCES'}


class DesignGraphService:
    """Business logic for DesignGraph — uses NetworkX for graph algorithms."""

    # ── NetworkX conversion ────────────────────────────────────────────────────

    def to_networkx(self, graph_id) -> 'nx.DiGraph':
        from app.design.models.graph import DesignGraph, DesignNode, DesignEdge
        if not NX_AVAILABLE:
            raise RuntimeError("networkx is required for graph operations")

        graph = DesignGraph.query.filter_by(id=graph_id).first()
        if not graph:
            raise ValueError(f"Graph {graph_id} not found")

        G = nx.DiGraph()
        G.graph.update({'id': str(graph_id), 'name': graph.name, 'tier': graph.tier})

        for n in DesignNode.query.filter_by(graph_id=graph_id).all():
            G.add_node(str(n.id),
                       node_type=n.node_type,
                       label=n.label,
                       level=n.level,
                       properties=n.properties or {})

        for e in DesignEdge.query.filter_by(graph_id=graph_id).all():
            G.add_edge(str(e.source_id), str(e.target_id),
                       id=str(e.id),
                       edge_type=e.edge_type,
                       weight=e.weight)

        return G

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add_node(self, graph_id, node_type: str, label: str, properties: dict,
                 level: int = 0, pos_x: float = 0.0, pos_y: float = 0.0):
        from app.extensions import db
        from app.design.models.graph import DesignNode

        if node_type not in VALID_NODE_TYPES:
            raise ValueError(f"Invalid node_type '{node_type}'. Valid: {VALID_NODE_TYPES}")

        node = DesignNode(
            graph_id=graph_id,
            node_type=node_type,
            label=label,
            level=level,
            properties=properties or {},
            pos_x=pos_x,
            pos_y=pos_y,
        )
        db.session.add(node)
        db.session.commit()
        self._update_graph_hash(graph_id)
        return node

    def update_node(self, graph_id, node_id, updates: dict):
        from app.extensions import db
        from app.design.models.graph import DesignNode

        node = DesignNode.query.filter_by(id=node_id, graph_id=graph_id).first()
        if not node:
            raise ValueError(f"Node {node_id} not found in graph {graph_id}")

        allowed = {'label', 'level', 'properties', 'pos_x', 'pos_y', 'level_set', 'tier'}
        for key, val in updates.items():
            if key in allowed and val is not None:
                setattr(node, key, val)

        db.session.commit()
        self._update_graph_hash(graph_id)
        return node

    def delete_node(self, graph_id, node_id):
        from app.extensions import db
        from app.design.models.graph import DesignNode, DesignEdge

        node = DesignNode.query.filter_by(id=node_id, graph_id=graph_id).first()
        if not node:
            raise ValueError(f"Node {node_id} not found in graph {graph_id}")

        # Delete connected edges first
        DesignEdge.query.filter(
            DesignEdge.graph_id == graph_id,
            (DesignEdge.source_id == node_id) | (DesignEdge.target_id == node_id)
        ).delete(synchronize_session=False)

        db.session.delete(node)
        db.session.commit()
        self._update_graph_hash(graph_id)

    def add_edge(self, graph_id, source_id, target_id, edge_type: str,
                 weight: float = 1.0, properties: dict = None):
        from app.extensions import db
        from app.design.models.graph import DesignEdge

        if edge_type not in VALID_EDGE_TYPES:
            raise ValueError(f"Invalid edge_type '{edge_type}'. Valid: {VALID_EDGE_TYPES}")

        edge = DesignEdge(
            graph_id=graph_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            weight=weight,
            properties=properties or {},
        )
        db.session.add(edge)
        db.session.commit()
        self._update_graph_hash(graph_id)
        return edge

    def delete_edge(self, graph_id, edge_id):
        from app.extensions import db
        from app.design.models.graph import DesignEdge

        edge = DesignEdge.query.filter_by(id=edge_id, graph_id=graph_id).first()
        if not edge:
            raise ValueError(f"Edge {edge_id} not found in graph {graph_id}")

        db.session.delete(edge)
        db.session.commit()
        self._update_graph_hash(graph_id)

    # ── Graph queries ──────────────────────────────────────────────────────────

    def get_subgraph_by_level(self, graph_id, level: int):
        G = self.to_networkx(graph_id)
        nodes_at_level = [n for n, d in G.nodes(data=True) if d.get('level') == level]
        return G.subgraph(nodes_at_level)

    def get_physics_domain(self, graph_id) -> dict:
        from app.design.models.graph import DesignNode

        nodes = DesignNode.query.filter_by(graph_id=graph_id).all()
        domain = {k: [] for k in ('material_nodes', 'bc_nodes', 'load_nodes',
                                   'geometry_nodes', 'concept_nodes', 'result_nodes')}
        for n in nodes:
            mapping = {
                'MATERIAL': 'material_nodes', 'BC': 'bc_nodes',
                'LOAD': 'load_nodes', 'GEOMETRY': 'geometry_nodes',
                'CONCEPT': 'concept_nodes', 'RESULT': 'result_nodes',
            }
            key = mapping.get(n.node_type)
            if key:
                domain[key].append(n)
        return domain

    def compute_dependency_order(self, graph_id) -> list:
        if not NX_AVAILABLE:
            return []
        G = self.to_networkx(graph_id)
        try:
            return list(nx.topological_sort(G))
        except nx.NetworkXUnfeasible:
            return list(G.nodes())

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate_completeness(self, graph_id) -> list:
        from app.design.models.graph import DesignEdge

        errors = []
        domain = self.get_physics_domain(graph_id)
        edges = DesignEdge.query.filter_by(graph_id=graph_id).all()

        geom_ids = {str(n.id) for n in domain['geometry_nodes']}
        mat_ids  = {str(n.id) for n in domain['material_nodes']}
        bc_ids   = {str(n.id) for n in domain['bc_nodes']}
        load_ids = {str(n.id) for n in domain['load_nodes']}

        def connected(set_a, set_b):
            return any(
                (str(e.source_id) in set_a and str(e.target_id) in set_b) or
                (str(e.target_id) in set_a and str(e.source_id) in set_b)
                for e in edges
            )

        if not domain['geometry_nodes']:
            errors.append({'severity': 'error', 'node_id': None,
                           'message': 'Falta nodo GEOMETRY. Agrega al menos una geometría.'})

        if not domain['material_nodes']:
            errors.append({'severity': 'error', 'node_id': None,
                           'message': 'Falta nodo MATERIAL. Agrega al menos un material.'})

        if not domain['load_nodes'] and not domain['bc_nodes']:
            errors.append({'severity': 'error', 'node_id': None,
                           'message': 'Faltan nodos LOAD o BC. Agrega al menos una carga o condición de frontera.'})

        if domain['material_nodes'] and domain['geometry_nodes']:
            if not connected(mat_ids, geom_ids):
                errors.append({'severity': 'warning', 'node_id': None,
                               'message': 'Nodo MATERIAL no conectado a ningún GEOMETRY.'})

        if domain['geometry_nodes'] and (domain['load_nodes'] or domain['bc_nodes']):
            if not connected(load_ids | bc_ids, geom_ids):
                errors.append({'severity': 'warning', 'node_id': None,
                               'message': 'Nodos LOAD/BC no conectados a ningún GEOMETRY.'})

        if NX_AVAILABLE:
            G = self.to_networkx(graph_id)
            if not nx.is_weakly_connected(G) and len(G.nodes) > 1:
                errors.append({'severity': 'warning', 'node_id': None,
                               'message': 'El grafo tiene componentes desconectados.'})

        return errors

    # ── Serialisation helpers ──────────────────────────────────────────────────

    def to_reactflow_format(self, graph_id) -> dict:
        from app.design.models.graph import DesignNode, DesignEdge

        nodes = DesignNode.query.filter_by(graph_id=graph_id).all()
        edges = DesignEdge.query.filter_by(graph_id=graph_id).all()

        rf_nodes = [{
            'id': str(n.id),
            'type': 'designNode',
            'position': {'x': n.pos_x or 0.0, 'y': n.pos_y or 0.0},
            'data': {
                'node_type': n.node_type,
                'label': n.label,
                'level': n.level,
                'properties': n.properties or {},
                'level_set': n.level_set,
                'result_ref': n.result_ref,
                'tier': n.tier,
            },
        } for n in nodes]

        rf_edges = [{
            'id': str(e.id),
            'source': str(e.source_id),
            'target': str(e.target_id),
            'type': 'designEdge',
            'label': e.edge_type,
            'data': {
                'edge_type': e.edge_type,
                'weight': e.weight,
                'properties': e.properties or {},
            },
        } for e in edges]

        return {'nodes': rf_nodes, 'edges': rf_edges}

    def compute_graph_hash(self, graph_id) -> str:
        from app.design.models.graph import DesignGraph, DesignNode, DesignEdge

        graph = DesignGraph.query.filter_by(id=graph_id).first()
        if not graph:
            return ''

        nodes = DesignNode.query.filter_by(graph_id=graph_id).order_by(DesignNode.created_at).all()
        edges = DesignEdge.query.filter_by(graph_id=graph_id).order_by(DesignEdge.created_at).all()

        payload = {
            'name': graph.name,
            'tier': graph.tier,
            'nodes': [{'id': str(n.id), 'type': n.node_type,
                       'label': n.label, 'props': n.properties} for n in nodes],
            'edges': [{'src': str(e.source_id), 'tgt': str(e.target_id),
                       'type': e.edge_type} for e in edges],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()

    def to_jsonld(self, graph_id) -> dict:
        raise NotImplementedError("Implemented in FASE 7")

    # ── Internal ───────────────────────────────────────────────────────────────

    def _update_graph_hash(self, graph_id):
        from app.extensions import db
        from app.design.models.graph import DesignGraph
        graph = DesignGraph.query.filter_by(id=graph_id).first()
        if graph:
            graph.hash = self.compute_graph_hash(graph_id)
            db.session.commit()
