"""CAD geometry → FEM mesh with one face set per CAD face (FASE 2).

The versioned geometry (app.geometry, Hub H1b) stores a BREP in mm plus one
signature per face in ``geometry_entities``. Meshing re-imports the BREP in
Gmsh, matches every Gmsh surface to its CAD face with the H1a bridge (signature
matching, strict: a load must never land on the wrong face) and returns a
``FEMMesh`` in metres whose ``face_sets['F_<index>']`` hold the boundary
triangles of CAD face ``index`` (1-based TopExp index = ``entity_index``).

Only Gmsh is needed (no pythonOCC), so this runs in the ``solve`` worker on any
platform. Meshes are cached under ``DATA_DIR/meshes/<geometry_id>/<key>.npz``,
keyed by the geometry digest and the mesh parameters.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time

import numpy as np

from app.design.services.fem.mesh import FEMMesh, _gmsh_lock, gmsh_extract

logger = logging.getLogger(__name__)

MESHER_VERSION = 4          # bump when meshing options change (invalidates the cache)
DEFAULT_TARGET_TETS = 15_000
REGULAR_TET = 1.0 / (6.0 * np.sqrt(2.0))   # volume of a regular tet of edge 1
UNIT_TO_M = {'mm': 1e-3, 'm': 1.0, 'cm': 1e-2, 'in': 0.0254}
ALGORITHMS_3D = (1, 10, 4)  # Delaunay, HXT, Frontal — fresh Gmsh session per attempt


class CADMeshError(RuntimeError):
    pass


def _load(geometry_id):
    from app.extensions import db
    from app.geometry.models import Geometry, GeometryEntity
    geo = db.session.get(Geometry, geometry_id)
    if geo is None:
        raise CADMeshError(f'La geometría {geometry_id} no existe.')
    if geo.status != 'ready' or not geo.brep_uri:
        raise CADMeshError(f'La geometría "{geo.name}" v{geo.version} no está lista ({geo.status}).')
    ents = (GeometryEntity.query.filter_by(geometry_id=geo.id)
            .order_by(GeometryEntity.entity_type, GeometryEntity.entity_index).all())
    faces = [e.as_signature() for e in ents if e.entity_type == 'face']
    solids = [e.as_signature() for e in ents if e.entity_type == 'solid']
    return geo, faces, solids


def solid_volume(solids: list) -> float:
    return float(sum(abs(s['area'] or 0.0) for s in solids))


def default_mesh_size(geo, solids, target_tets: int = DEFAULT_TARGET_TETS) -> float:
    """Element size (geometry units) giving roughly ``target_tets`` tetrahedra."""
    vol = solid_volume(solids)
    if vol <= 0:
        return float(geo.scale or 1.0) / 20.0
    h = (vol / (REGULAR_TET * target_tets)) ** (1.0 / 3.0)
    return float(min(h, (geo.scale or h) / 8.0))


# Mesh.MeshSizeFromCurvature (elements per 2π) and MeshSizeMin / h, per element order.
# T10 mid-edge nodes follow the curved surface, so 6 elements per turn are enough; with
# 12 and min 0.05h small fillets blew the "15 000 tets" default up to 393 000 (pedestal).
MESH_OPTS = {1: {'curvature': 10, 'min_factor': 0.10}, 2: {'curvature': 6, 'min_factor': 0.25}}


def estimate_size(geometry_id, mesh_size=None, order: int = 2) -> dict:
    """Pre-meshing estimate (for the tier check before enqueueing).

    Two regimes, take the larger: fine meshes are volume-driven; coarse meshes are
    driven by curvature refinement (local size 2πr/12 on curved faces). Factors
    calibrated on the example parts (±20 %); the worker re-checks the exact size.
    """
    geo, faces, solids = _load(geometry_id)
    h = float(mesh_size) if mesh_size else default_mesh_size(geo, solids)
    opts = MESH_OPTS[order]
    vol_tets = 1.8 * solid_volume(solids) / (REGULAR_TET * h ** 3)
    surf_tris = 0.0
    for f in faces:
        hf = max(h * opts['min_factor'], min(h, 2 * np.pi * f['radius'] / opts['curvature'])) \
            if f.get('radius') else h
        surf_tris += abs(f['area'] or 0.0) / (0.433 * hf * hf)     # equilateral triangles
    n_tets = int(max(vol_tets, 9.0 * surf_tris)) + 1
    n_nodes = int(n_tets * (1.6 if order == 2 else 0.22)) + 1
    return {'n_elements': n_tets, 'n_nodes': n_nodes, 'n_dof': 3 * n_nodes, 'mesh_size': h, 'estimated': True}


def _cache_path(geo, h: float, order: int):
    from app.geometry.storage import data_dir
    import gmsh
    key = hashlib.sha256(json.dumps({
        'digest': geo.digest, 'sha256': geo.sha256, 'h': round(h, 9), 'order': order,
        'gmsh': gmsh.GMSH_API_VERSION, 'mesher': MESHER_VERSION,
    }, sort_keys=True).encode()).hexdigest()[:24]
    return data_dir() / 'meshes' / str(geo.id) / f'{key}.npz'


def cached_stats(geometry_id, mesh_size=None, order: int = 2) -> dict | None:
    """Exact size of an already-cached mesh, or None."""
    geo, _, solids = _load(geometry_id)
    h = float(mesh_size) if mesh_size else default_mesh_size(geo, solids)
    path = _cache_path(geo, h, order)
    if not path.exists():
        return None
    with np.load(path, allow_pickle=False) as z:
        meta = json.loads(str(z['meta']))
    return {k: meta[k] for k in ('n_nodes', 'n_elements', 'n_dof', 'mesh_size')} | {'estimated': False}


def _save(path, mesh: FEMMesh, meta: dict):
    names = sorted(mesh.face_sets, key=lambda n: int(n[2:]))
    idx = np.array([int(n[2:]) for n in names], dtype=np.int64)
    counts = np.array([len(mesh.face_sets[n]) for n in names], dtype=np.int64)
    tris = np.concatenate([mesh.face_sets[n] for n in names]) if names else np.zeros((0, 3), np.int64)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp.npz')
    np.savez_compressed(tmp, nodes=mesh.nodes, elements=mesh.elements, face_index=idx,
                        face_count=counts, face_tris=tris, meta=json.dumps(meta))
    tmp.replace(path)


def _read(path) -> tuple[FEMMesh, dict]:
    with np.load(path, allow_pickle=False) as z:
        meta = json.loads(str(z['meta']))
        offs = np.concatenate([[0], np.cumsum(z['face_count'])])
        tris = z['face_tris']
        faces = {f'F_{i}': tris[offs[k]:offs[k + 1]] for k, i in enumerate(z['face_index'])}
        mesh = FEMMesh(z['nodes'], z['elements'], face_sets=faces, canonical=True)
    return mesh, meta


def _attempt(brep, occ, h: float, order: int, algo: int, scale_m: float, report: dict):
    from app.design.services.fem.tet_batch import canonicalize, volumes
    from app.geometry.gmsh_bridge import gmsh_session, gmsh_signatures, import_brep, match_faces
    with gmsh_session('fem', heal=False) as gmsh:
        import_brep(brep)
        bridge = match_faces(occ, gmsh_signatures(), strict=True)
        report['bridge'] = {k: bridge[k] for k in ('matched', 'grouped_by_solid', 'max_dev')}
        report['tag_to_face'] = {int(t): int(f) for f, t in bridge['face_to_tag'].items()}
        opts = MESH_OPTS[order]
        gmsh.option.setNumber('Mesh.MeshSizeMax', h)
        gmsh.option.setNumber('Mesh.MeshSizeMin', h * opts['min_factor'])
        gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', opts['curvature'])
        gmsh.option.setNumber('Mesh.Algorithm3D', algo)
        gmsh.option.setNumber('Mesh.Optimize', 1)
        gmsh.option.setNumber('General.NumThreads', 1)   # >1 thread gives a different mesh per run
        gmsh.model.mesh.generate(3)
        if not len(gmsh.model.mesh.getElementsByType(4)[0]):
            raise CADMeshError('Gmsh no generó tetraedros.')
        if order == 2:
            gmsh.model.mesh.setOrder(2)
        surfaces = {f'F_{fi}': tag for fi, tag in bridge['face_to_tag'].items()}
        nodes, tets, faces = gmsh_extract(gmsh, surfaces)
        nodes = nodes * scale_m
        if order == 2:
            try:
                tets_c = canonicalize(nodes, tets, reorder_mids=False)
                volumes(nodes, tets_c)          # raises on non-positive Jacobian at any Gauss point
            except ValueError as e:
                # curved mid-edge nodes inverted some elements: fall back to straight-sided T10
                report['curved_t10_rejected'] = str(e)
                gmsh.model.mesh.setOrder(1)
                gmsh.option.setNumber('Mesh.SecondOrderLinear', 1)
                gmsh.model.mesh.setOrder(2)
                nodes, tets, faces = gmsh_extract(gmsh, surfaces)
                nodes = nodes * scale_m
        return FEMMesh(nodes, tets, face_sets=faces, mids_known=True)


def mesh_geometry(geometry_id, mesh_size=None, order: int = 2, progress=None) -> tuple[FEMMesh, dict]:
    """Mesh a ready geometry (cached). ``mesh_size`` in geometry units (mm)."""
    if order not in (1, 2):
        raise CADMeshError('El orden de elemento debe ser 1 (T4) o 2 (T10).')
    geo, faces, solids = _load(geometry_id)
    if len(solids) != 1:
        raise CADMeshError(f'La geometría tiene {len(solids)} sólidos; por ahora el kernel FEM '
                           'solo malla piezas de un sólido (ensambles requieren contacto o fusión).')
    h = float(mesh_size) if mesh_size else default_mesh_size(geo, solids)
    path = _cache_path(geo, h, order)
    if path.exists():
        mesh, meta = _read(path)
        return mesh, {**meta, 'cache_hit': True}

    from app.geometry.storage import abs_path
    scale_m = UNIT_TO_M.get(geo.units or 'mm', 1e-3)
    occ = {'faces': faces, 'solids': solids, 'scale': geo.scale}
    report: dict = {'attempts': []}
    t0 = time.perf_counter()
    mesh = None
    with _gmsh_lock:
        for algo in ALGORITHMS_3D:
            if progress:
                progress(f'Mallando con Gmsh (algoritmo {algo}, h={h:.3g} {geo.units})')
            try:
                mesh = _attempt(str(abs_path(geo.brep_uri)), occ, h, order, algo, scale_m, report)
                report['attempts'].append({'algorithm3d': algo, 'ok': True})
                break
            except Exception as e:                       # FaceBridgeError is fatal, meshing errors retry
                from app.geometry.gmsh_bridge import FaceBridgeError
                if isinstance(e, FaceBridgeError):
                    raise CADMeshError(f'Puente de caras CAD↔Gmsh falló: {e}') from e
                report['attempts'].append({'algorithm3d': algo, 'ok': False, 'error': str(e)[:300]})
                logger.warning('Meshing geometry %s with algorithm %s failed: %s', geo.id, algo, e)
    tag_to_face = report.pop('tag_to_face', {})
    if mesh is None:
        raise CADMeshError(_explain_failure(report['attempts'], tag_to_face))
    meta = {'geometry_id': str(geo.id), 'geometry_name': geo.name, 'geometry_version': geo.version,
            'mesh_size': h, 'units': geo.units, 'order': order, 'element_type': mesh.element_type,
            'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': mesh.n_dof_structural,
            'n_face_sets': len(mesh.face_sets), 'mesh_seconds': round(time.perf_counter() - t0, 3),
            **report}
    _save(path, mesh, meta)
    return mesh, {**meta, 'cache_hit': False}


def _explain_failure(attempts: list, tag_to_face: dict) -> str:
    """User-facing reason, with Gmsh surface tags translated to CAD face numbers."""
    errs = [a.get('error', '') for a in attempts if not a.get('ok')]
    tags = sorted({int(t) for e in errs for t in re.findall(r'surface (\d+)', e)})
    faces = [tag_to_face[t] for t in tags if t in tag_to_face]
    text = ' '.join(errs)
    if 'PLC Error' in text or 'overlapping facets' in text or 'intersect' in text:
        msg = ('Gmsh no pudo mallar el volumen: la malla de superficie se autointersecta '
               '(caras muy delgadas, solapadas o tangentes en el CAD).')
        if faces:
            msg += ' Revisa las caras ' + ', '.join(f'#{f}' for f in faces) + '.'
        return msg + ' Prueba otro tamaño de elemento o repara la geometría en el CAD.'
    return 'Gmsh no pudo mallar la geometría: ' + '; '.join(e.splitlines()[0][:200] for e in errs)
