"""Graph-to-solver-spec translation layer.

Extracts material, BC, LOAD propiedades de nodos del grafo y construye un spec compatible
con FEMKernel.solve_sync / solve_async.
"""
from app.design.models.graph import DesignGraph, DesignNode


def graph_to_solver_spec(graph_id: str) -> dict:
    """Extrae propiedades de nodos MATERIAL, BC, LOAD, GEOMETRY del grafo.

    Args:
        graph_id: UUID del DesignGraph

    Returns:
        dict: spec compatible con FEMKernel, con keys:
            - mesh_source: 'cantilever' | 'cae_mesh' | 'graph'
            - material: { type, E, nu, rho }
            - bcs: [{ node_set, dofs, values }]
            - loads: [{ node_set, force }]
            - mesh_id: (opcional) si GEOMETRY apunta a una CAEMesh
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

    # Lee todos los nodos del grafo
    nodes = DesignNode.query.filter_by(graph_id=graph_id).all()

    for node in nodes:
        props = node.properties or {}

        # MATERIAL node
        if node.node_type == 'MATERIAL':
            spec['material'] = {
                'type': props.get('model_type', 'linear_elastic_isotropic'),
                'E': float(props.get('E', 210e9)),
                'nu': float(props.get('nu', 0.3)),
                'rho': float(props.get('rho', 7800.0)),
            }

        # BC node
        elif node.node_type == 'BC':
            bc_entry = {
                'node_set': props.get('node_set', 'fixed'),
                'dofs': props.get('dofs', [0, 1, 2]),  # default: UX, UY, UZ
                'values': [float(props.get('value', 0))] * len(props.get('dofs', [0, 1, 2])),
            }
            spec['bcs'].append(bc_entry)

        # LOAD node
        elif node.node_type == 'LOAD':
            mag = float(props.get('magnitude', 0))
            dx = float(props.get('dir_x', 0))
            dy = float(props.get('dir_y', 0))
            dz = float(props.get('dir_z', -1))

            # Normalize direction vector
            import math
            norm = math.sqrt(dx*dx + dy*dy + dz*dz)
            if norm > 1e-10:
                dx, dy, dz = dx/norm, dy/norm, dz/norm

            load_entry = {
                'node_set': props.get('node_set', 'tip'),
                'force': [mag * dx, mag * dy, mag * dz],
            }
            spec['loads'].append(load_entry)

        # GEOMETRY node
        elif node.node_type == 'GEOMETRY':
            mesh_id = props.get('mesh_id')
            if mesh_id:
                spec['mesh_source'] = 'cae_mesh'
                spec['mesh_id'] = mesh_id

            # Tier is read as top-level field on node if present
            tier = node.tier if node.tier is not None else props.get('tier', 1)
            spec['tier'] = int(tier)

    return spec
