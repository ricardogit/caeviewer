"""Graph-to-solver-spec translation layer.

Extrae propiedades de nodos y ARISTAS del grafo. Phase 2-3: edge-aware solver.

FASE 2 (caras CAD): un GEOMETRY con ``geometry_id`` se malla desde el CAD
(``mesh_source='geometry'``) y los BC/LOAD con ``entity_ids`` (UUID persistentes
de caras) se traducen a ``face_set`` = ['F_<índice>', ...] en esa versión.
Unidades: el solver trabaja en SI (m, N, Pa); fuerzas y presiones se convierten
desde la unidad declarada en el nodo.
"""
import math
from app.design.models.graph import DesignGraph, DesignNode, DesignEdge
from app.design.services.graph_service import DesignGraphService


class GraphSpecError(ValueError):
    """The graph cannot be turned into a solver spec (message is user-facing, Spanish)."""


FORCE_UNITS = {'N': 1.0, 'kN': 1e3, 'MN': 1e6, 'lbf': 4.4482216152605}
PRESSURE_UNITS = {'Pa': 1.0, 'kPa': 1e3, 'MPa': 1e6, 'GPa': 1e9, 'psi': 6894.757293168, 'bar': 1e5}
ACCEL_UNITS = {'m/s²': 1.0, 'm/s2': 1.0, 'g': 9.80665}
BC_TYPE_DOFS = {'fixed': [0, 1, 2], 'pinned': [0, 1, 2],
                'roller_x': [0], 'roller_y': [1], 'roller_z': [2]}


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
    nodes = DesignNode.query.filter_by(graph_id=graph_id).order_by(DesignNode.created_at, DesignNode.id).all()
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
            'E': float(props.get('E') if props.get('E') is not None else 210e9),
            'nu': float(props.get('nu') if props.get('nu') is not None else 0.3),
            'rho': float(props.get('rho') if props.get('rho') is not None else 7800.0),
        }

    # ── GEOMETRY ───────────────────────────────────────────────────────────

    if geometry_nodes:
        geom_node = geometry_nodes[0]
        props = geom_node.properties or {}
        # Fase 1b: versioned CAD geometry with persistent face IDs (app.geometry).
        # Consumed by the Gmsh/CalculiX path in Fase 2; BC/LOAD entity_ids refer to its faces.
        if props.get('geometry_id'):
            spec['geometry_id'] = props['geometry_id']
        mesh_id = props.get('mesh_id')
        if props.get('geometry_id'):
            spec['mesh_source'] = 'geometry'
            spec['mesh_params'] = {'order': int(props.get('element_order', 2))}
            if props.get('mesh_size_mm'):
                spec['mesh_params']['mesh_size'] = float(props['mesh_size_mm'])
        elif mesh_id:
            spec['mesh_source'] = 'cae_mesh'
            spec['mesh_id'] = mesh_id

        tier = geom_node.tier if geom_node.tier is not None else props.get('tier', 1)
        spec['tier'] = int(tier)

    # ── BC & LOAD with Phase 2-3 edge scoping ──────────────────────────────

    ctx = {'geometry_id': spec.get('geometry_id'), 'normals': None}
    use_edge_scoping = False
    edges = DesignEdge.query.filter_by(graph_id=graph_id).order_by(DesignEdge.created_at, DesignEdge.id).all()

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
            ).order_by(DesignEdge.created_at, DesignEdge.id).all()
            for bc_edge in bc_edges:
                bc_node = node_map.get(str(bc_edge.source_id))
                if bc_node and bc_node.node_type == 'BC':
                    bc_entry = _bc_node_to_entry(ctx, bc_node, geom_id)
                    spec['bcs'].append(bc_entry)

            # Get LOADs for this geometry via APPLIED_TO edge
            load_edges = DesignEdge.query.filter_by(
                graph_id=graph_id,
                target_id=geom.id,
                edge_type='APPLIED_TO'
            ).order_by(DesignEdge.created_at, DesignEdge.id).all()
            for load_edge in load_edges:
                load_node = node_map.get(str(load_edge.source_id))
                if load_node and load_node.node_type == 'LOAD':
                    load_entry = _load_node_to_entry(ctx, load_node, geom_id)
                    spec['loads'].append(load_entry)
    else:
        # Phase 1 fallback: all BCs/LOADs to all GEOMETRIEs
        for bc_node in bc_nodes:
            bc_entry = _bc_node_to_entry(ctx, bc_node)
            spec['bcs'].append(bc_entry)

        for load_node in load_nodes:
            load_entry = _load_node_to_entry(ctx, load_node)
            spec['loads'].append(load_entry)

    return spec


def _faces(ctx: dict, node: DesignNode) -> list | None:
    """face_set names for a node's ``entity_ids`` on the study geometry, or None."""
    ids = (node.properties or {}).get('entity_ids') or []
    if not ids:
        return None
    if not ctx.get('geometry_id'):
        raise GraphSpecError(f'"{node.label}" tiene caras seleccionadas pero el nodo GEOMETRY no '
                             'tiene una geometría CAD asignada.')
    from app.geometry.resolve import resolve_faces
    res = resolve_faces(ctx['geometry_id'], ids)
    bad = [i for i, r in res.items() if r['index'] is None]
    if bad:
        raise GraphSpecError(f'"{node.label}": {len(bad)} de {len(ids)} caras no existen en la versión '
                             'actual de la geometría. Vuelve a seleccionarlas.')
    return [f"F_{r['index']}" for r in res.values()]


def _symmetry_dofs(ctx: dict, node: DesignNode) -> list:
    """Normal DOF of planar, axis-aligned faces (symmetry BC without MPCs)."""
    from app.extensions import db
    from app.geometry.models import GeometryEntity
    from app.geometry.resolve import resolve_faces
    ids = (node.properties or {}).get('entity_ids') or []
    if not ids or not ctx.get('geometry_id'):
        raise GraphSpecError(f'"{node.label}": la simetría necesita caras planas seleccionadas.')
    axes = set()
    for r in resolve_faces(ctx['geometry_id'], ids).values():
        e = db.session.get(GeometryEntity, r['entity_id']) if r['entity_id'] else None
        n = (e.normal if e is not None else None) or []
        if e is None or e.surface_type != 'plane' or len(n) != 3:
            raise GraphSpecError(f'"{node.label}": la simetría solo admite caras planas.')
        k = max(range(3), key=lambda i: abs(n[i]))
        if abs(abs(n[k]) - 1.0) > 1e-6:
            raise GraphSpecError(f'"{node.label}": la cara de simetría debe ser normal a X, Y o Z '
                                 '(planos inclinados requieren restricciones MPC, aún no soportadas).')
        axes.add(k)
    return sorted(axes)


def _bc_node_to_entry(ctx: dict, node: DesignNode, geometry_id: str = None) -> dict:
    """Convert BC node to solver BC entry."""
    props = node.properties or {}
    faces = _faces(ctx, node)
    bc_type = props.get('bc_type', 'fixed')
    if props.get('dofs'):
        dofs = sorted({int(d) for d in props['dofs'] if int(d) in (0, 1, 2)})
        if not dofs:
            raise GraphSpecError(f'"{node.label}": los sólidos solo tienen grados de libertad de '
                                 'traslación (UX, UY, UZ); RX/RY/RZ no aplican.')
    elif bc_type == 'symmetry':
        dofs = _symmetry_dofs(ctx, node)
    else:
        dofs = BC_TYPE_DOFS.get(bc_type, [0, 1, 2])
    values = [float(props.get('value', 0) or 0)] * len(dofs)

    entry = {'dofs': dofs, 'values': values, 'label': node.label}
    # topology optimization keeps support regions solid, but not symmetry/plane constraints
    if bc_type == 'symmetry':
        entry['symmetry'] = True
    elif props.get('keep_solid') is False:
        entry['keep_solid'] = False
    if faces:
        entry['face_set'] = faces
    else:
        entry['node_set'] = props.get('node_set', 'fixed')
    if geometry_id:
        entry['geometry_id'] = geometry_id
    return entry


def _unit(table: dict, unit: str, node: DesignNode, default: str) -> float:
    u = (unit or default).strip()
    if u not in table:
        raise GraphSpecError(f'"{node.label}": unidad "{u}" no reconocida '
                             f'(usa {", ".join(table)}).')
    return table[u]


def _load_node_to_entry(ctx: dict, node: DesignNode, geometry_id: str = None) -> dict:
    """Convert LOAD node to solver LOAD entry (SI units)."""
    props = node.properties or {}
    load_type = props.get('load_type', 'force')
    mag = float(props.get('magnitude', 0) or 0)
    # defaults match NodePanel (Dz = -1)
    dx = float(props.get('dir_x', 0) or 0)
    dy = float(props.get('dir_y', 0) or 0)
    dz = float(props.get('dir_z', -1) if props.get('dir_z') is not None else -1)
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm > 1e-12:
        dx, dy, dz = dx / norm, dy / norm, dz / norm

    entry = {'label': node.label}
    if load_type == 'gravity':
        g = mag * _unit(ACCEL_UNITS, props.get('unit'), node, 'm/s²') if mag else 9.80665
        entry['gravity'] = [g * dx, g * dy, g * dz]
        return entry
    if load_type not in ('force', 'pressure'):
        raise GraphSpecError(f'"{node.label}": el tipo de carga "{load_type}" aún no está soportado '
                             '(disponibles: force, pressure, gravity).')

    faces = _faces(ctx, node)
    if load_type == 'pressure':
        if not faces:
            raise GraphSpecError(f'"{node.label}": la presión necesita caras seleccionadas.')
        entry['face_set'] = faces
        entry['pressure'] = mag * _unit(PRESSURE_UNITS, props.get('unit'), node, 'Pa')
    else:
        f = mag * _unit(FORCE_UNITS, props.get('unit'), node, 'N')
        entry['force'] = [f * dx, f * dy, f * dz]
        if faces:
            entry['face_set'] = faces
        else:
            entry['node_set'] = props.get('node_set', 'tip')
    if geometry_id:
        entry['geometry_id'] = geometry_id
    return entry
