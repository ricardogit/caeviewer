"""Graph-to-solver-spec translation layer.

Extrae propiedades de nodos y ARISTAS del grafo. Phase 2-3: edge-aware solver.
"""
import math
from app.design.models.graph import DesignGraph, DesignNode, DesignEdge
from app.design.services.graph_service import DesignGraphService


def graph_to_solver_spec(graph_id: str) -> dict:
    """Extrae material, BC, LOAD de nodos y aristas con edge-aware scoping.

    Phase 2-3: Si hay aristas CONSTRAINS_MATERIAL/CONSTRAINS_BC/APPLIED_TO,
    usa esas para scope. Si no, fallback a lógica global (Phase 1).

    Args:
        graph_id: UUID del DesignGraph

    Returns:
        dict: spec compatible con FEMKernel con:
            - material: { type, E, nu, rho }
            - bcs: [{ node_set, dofs, values, geometry_id? }]
            - loads: [{ node_set, force, geometry_id? }]
            - mesh_source, mesh_id, tier
    """

    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        raise ValueError(f"Graph {graph_id} not found")

    spec = {
        'physics': ['structural'],
        'mesh_source': 'cantilever',
        'material': {
            'type': 'linear_elastic_isotropic',
            'E': 210e9,
            'nu': 0.3,
            'rho': 7800.0,
        },
        'bcs': [],
        'loads': [],
    }

    service = DesignGraphService()
    nodes = DesignNode.query.filter_by(graph_id=graph_id).all()
    node_map = {str(n.id): n for n in nodes}

    # Phase 1 fallback: collect all nodes by type
    material_nodes = [n for n in nodes if n.node_type == 'MATERIAL']
    geometry_nodes = [n for n in nodes if n.node_type == 'GEOMETRY']
    bc_nodes = [n for n in nodes if n.node_type == 'BC']
    load_nodes = [n for n in nodes if n.node_type == 'LOAD']

    # ── Material ───────────────────────────────────────────────────────────

    if material_nodes:
        mat_node = material_nodes[0]  # Use first material as default
        props = mat_node.properties or {}
        spec['material'] = {
            'type': props.get('model_type', 'linear_elastic_isotropic'),
            'E': float(props.get('E', 210e9)),
            'nu': float(props.get('nu', 0.3)),
            'rho': float(props.get('rho', 7800.0)),
        }

    # ── GEOMETRY ───────────────────────────────────────────────────────────

    if geometry_nodes:
        geom_node = geometry_nodes[0]
        props = geom_node.properties or {}
        mesh_id = props.get('mesh_id')
        if mesh_id:
            spec['mesh_source'] = 'cae_mesh'
            spec['mesh_id'] = mesh_id

        tier = geom_node.tier if geom_node.tier is not None else props.get('tier', 1)
        spec['tier'] = int(tier)

    # ── BC & LOAD with Phase 2-3 edge scoping ──────────────────────────────

    use_edge_scoping = False
    edges = DesignEdge.query.filter_by(graph_id=graph_id).all()

    # Check if any CONSTRAINS_BC or APPLIED_TO edges exist (Phase 2+ indicator)
    if any(e.edge_type in ('CONSTRAINS_BC', 'APPLIED_TO') for e in edges):
        use_edge_scoping = True

    if use_edge_scoping and geometry_nodes:
        # Phase 2-3: Edge-aware scoping
        for geom in geometry_nodes:
            geom_id = str(geom.id)

            # Get BCs for this geometry via CONSTRAINS_BC edge
            bc_edges = DesignEdge.query.filter_by(
                graph_id=graph_id,
                target_id=geom.id,
                edge_type='CONSTRAINS_BC'
            ).all()
            for bc_edge in bc_edges:
                bc_node = node_map.get(str(bc_edge.source_id))
                if bc_node and bc_node.node_type == 'BC':
                    bc_entry = _bc_node_to_entry(bc_node, geom_id)
                    spec['bcs'].append(bc_entry)

            # Get LOADs for this geometry via APPLIED_TO edge
            load_edges = DesignEdge.query.filter_by(
                graph_id=graph_id,
                target_id=geom.id,
                edge_type='APPLIED_TO'
            ).all()
            for load_edge in load_edges:
                load_node = node_map.get(str(load_edge.source_id))
                if load_node and load_node.node_type == 'LOAD':
                    load_entry = _load_node_to_entry(load_node, geom_id)
                    spec['loads'].append(load_entry)
    else:
        # Phase 1 fallback: all BCs/LOADs to all GEOMETRIEs
        for bc_node in bc_nodes:
            bc_entry = _bc_node_to_entry(bc_node)
            spec['bcs'].append(bc_entry)

        for load_node in load_nodes:
            load_entry = _load_node_to_entry(load_node)
            spec['loads'].append(load_entry)

    return spec


def _bc_node_to_entry(node: DesignNode, geometry_id: str = None) -> dict:
    """Convert BC node to solver BC entry."""
    props = node.properties or {}
    dofs = props.get('dofs', [0, 1, 2])
    values = [float(props.get('value', 0))] * len(dofs)

    entry = {
        'node_set': props.get('node_set', 'fixed'),
        'dofs': dofs,
        'values': values,
    }
    if geometry_id:
        entry['geometry_id'] = geometry_id
    return entry


def _load_node_to_entry(node: DesignNode, geometry_id: str = None) -> dict:
    """Convert LOAD node to solver LOAD entry."""
    props = node.properties or {}
    mag = float(props.get('magnitude', 0))
    dx = float(props.get('dir_x', 0))
    dy = float(props.get('dir_y', -1))
    dz = float(props.get('dir_z', 0))

    norm = math.sqrt(dx*dx + dy*dy + dz*dz)
    if norm > 1e-10:
        dx, dy, dz = dx/norm, dy/norm, dz/norm

    entry = {
        'node_set': props.get('node_set', 'tip'),
        'force': [mag * dx, mag * dy, mag * dz],
    }
    if geometry_id:
        entry['geometry_id'] = geometry_id
    return entry
