"""Problem size before solving (tier check at enqueue time, plan: 413 on overflow).

Exact for inline meshes, CAE meshes and cached CAD meshes; a calibrated estimate
for uncached CAD meshes and generated cantilevers. The worker always re-checks
the exact size after meshing.
"""
from __future__ import annotations

import math


def estimate_problem_size(spec: dict) -> dict | None:
    source = spec.get('mesh_source', 'inline')
    p = spec.get('mesh_params') or {}

    if source == 'geometry' and spec.get('geometry_id'):
        from app.design.services.fem.cad_mesh import cached_stats, estimate_size
        order = int(p.get('order', 2))
        return (cached_stats(spec['geometry_id'], p.get('mesh_size'), order)
                or estimate_size(spec['geometry_id'], p.get('mesh_size'), order))

    if source == 'cantilever':
        L = float(p.get('length', 0.05)); W = float(p.get('width', 0.01)); H = float(p.get('height', 0.01))
        lc = L / max(1, int(p.get('n_along_length', 12)))
        n_tets = int(1.8 * L * W * H / (lc ** 3 / (6 * math.sqrt(2)))) + 1
        n_nodes = int(n_tets * (1.6 if int(p.get('order', spec.get('element_order', 1))) == 2 else 0.22)) + 1
        return {'n_nodes': n_nodes, 'n_elements': n_tets, 'n_dof': 3 * n_nodes, 'estimated': True}

    if source == 'cae_mesh' and spec.get('mesh_id'):
        from app.cae.models import CAEMesh
        rec = CAEMesh.query.filter_by(id=spec['mesh_id']).first()
        if rec is None or rec.node_count is None:
            return None
        return {'n_nodes': rec.node_count, 'n_elements': rec.element_count or 0,
                'n_dof': 3 * rec.node_count, 'estimated': False}

    if source == 'inline' and spec.get('nodes') is not None:
        n = len(spec['nodes'])
        return {'n_nodes': n, 'n_elements': len(spec.get('elements') or []), 'n_dof': 3 * n,
                'estimated': False}
    return None
