"""'geometry.import' job — runs in the geometry worker (needs pythonOCC).

STEP → XDE shape (mm) → per-face/solid signatures → BREP → geometry_entities,
then, if the geometry has a parent version, signature remap parent → child.
OCC modules are imported inside the handler so registering it is OCC-free.
"""
import logging
import time
from collections import Counter

from app.jobs.handlers import handler, JobCancelled

logger = logging.getLogger(__name__)

# Version-to-version remap: pass 1 = Fase 1a defaults, pass 2 = relaxed on the remainder.
TIGHT = {}
LOOSE = {'pos_tol': 1e-3, 'measure_tol': 1e-2}


@handler('geometry.import', queue='geometry')
def geometry_import(ctx, payload):
    from app.extensions import db
    from app.geometry.models import Geometry
    from app.geometry.storage import abs_path

    geo = db.session.get(Geometry, payload['geometry_id'])
    if geo is None:
        raise RuntimeError(f"Geometry {payload['geometry_id']} not found")
    geo.status, geo.error = 'processing', None
    db.session.commit()
    try:
        result = _import(ctx, geo, abs_path(geo.file_uri))
        geo.status = 'ready'
        db.session.commit()
        return result
    except JobCancelled:
        db.session.rollback()
        geo.status, geo.error = 'failed', 'Importación cancelada'
        db.session.commit()
        raise
    except Exception as e:
        db.session.rollback()
        geo.status, geo.error = 'failed', f'{type(e).__name__}: {e}'[:2000]
        db.session.commit()
        raise


def _import(ctx, geo, step_path):
    from app.extensions import db
    from app.geometry.occ_import import read_step, compute_signatures, write_brep
    from app.geometry.signature import digest_of
    from app.geometry.storage import abs_path

    timings = {}
    t = time.perf_counter()
    ctx.progress(5, 'Leyendo STEP (XDE, mm)', force=True)
    shape = read_step(step_path)
    timings['read_s'] = round(time.perf_counter() - t, 3)
    ctx.check_cancel()

    t = time.perf_counter()
    ctx.progress(35, f'Calculando firmas de {shape.n_faces} caras', force=True)
    sigs = compute_signatures(shape)
    timings['signatures_s'] = round(time.perf_counter() - t, 3)
    ctx.check_cancel()

    ctx.progress(70, 'Escribiendo BREP', force=True)
    brep_rel = f'geometry/{geo.id}/shape.brep'
    dest = abs_path(brep_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_brep(shape, dest)

    ctx.progress(80, 'Guardando entidades', force=True)
    stats = _upsert_entities(geo, sigs)
    new_digest = digest_of(f['hash'] for f in sigs['faces'])

    prev_digest = geo.digest
    geo.brep_uri = brep_rel
    geo.bbox = [round(v, 6) for v in sigs['bbox']]
    geo.scale = sigs['scale']
    geo.n_faces = len(sigs['faces'])
    geo.n_solids = len(sigs['solids'])
    geo.is_assembly = shape.is_assembly
    geo.digest = new_digest
    meta = dict(geo.meta or {})
    meta.update({
        'surface_types': dict(Counter(f['surface_type'] for f in sigs['faces'])),
        'n_free_shapes': shape.n_free_shapes,
        'n_named_faces': len(shape.face_names),
        'timings': timings,
        'entity_upsert': stats,
    })
    if prev_digest and prev_digest != new_digest:
        # Re-import of the same file must be deterministic; flag loudly if not.
        meta['digest_changed_on_reimport'] = {'previous': prev_digest, 'new': new_digest}
        logger.warning("Geometry %s: face digest changed on re-import", geo.id)
    geo.meta = meta
    db.session.flush()

    remap = None
    if geo.parent_id:
        ctx.progress(90, 'Emparejando caras con la versión anterior', force=True)
        remap = remap_from_parent(geo)
        meta = dict(geo.meta)
        meta['remap'] = remap
        geo.meta = meta
    db.session.commit()
    ctx.progress(100, 'Geometría lista', force=True)
    return {'geometry_id': str(geo.id), 'n_faces': geo.n_faces, 'n_solids': geo.n_solids,
            'digest': new_digest, 'deterministic': prev_digest in (None, new_digest),
            'remap': {k: v for k, v in (remap or {}).items() if not isinstance(v, list)} or None,
            'timings': timings}


def _upsert_entities(geo, sigs) -> dict:
    """Insert/update rows keyed by (type, index) so entity UUIDs survive re-imports."""
    from app.extensions import db
    from app.geometry.models import GeometryEntity

    existing = {(e.entity_type, e.entity_index): e for e in geo.entities}
    seen = set()
    created = updated = 0
    for etype, items in (('face', sigs['faces']), ('solid', sigs['solids'])):
        for s in items:
            key = (etype, s['index'])
            seen.add(key)
            row = existing.get(key)
            if row is None:
                row = GeometryEntity(geometry_id=geo.id, entity_type=etype, entity_index=s['index'])
                db.session.add(row)
                created += 1
            else:
                updated += 1
            row.solid_index = s.get('solid') if etype == 'face' else None
            row.surface_type = s.get('surface_type')
            row.measure = s.get('area')
            row.centroid = s.get('centroid')
            row.normal = s.get('normal')
            row.radius = s.get('radius')
            row.bbox = s.get('bbox')
            row.sig_hash = s.get('hash')
            row.name = s.get('name')
    removed = 0
    for key, row in existing.items():
        if key not in seen:
            db.session.delete(row)
            removed += 1
    return {'created': created, 'updated': updated, 'removed': removed}


def remap_from_parent(geo) -> dict:
    """Link each face of ``geo`` to its match in the parent version (two-pass signature match).

    Ambiguous faces are left unmatched on purpose: never carry a BC onto the wrong face.
    """
    from app.extensions import db
    from app.geometry.models import Geometry, GeometryEntity
    from app.geometry.signature import match_signatures

    parent = db.session.get(Geometry, geo.parent_id)
    if parent is None or parent.status != 'ready':
        return {'error': 'La versión anterior no está lista; sin remapeo'}

    def faces(g):
        return (GeometryEntity.query.filter_by(geometry_id=g.id, entity_type='face')
                .order_by(GeometryEntity.entity_index).all())

    old, new = faces(parent), faces(geo)
    for e in new:
        e.parent_entity_id, e.match_kind = None, None
    scale = max(parent.scale or 0, geo.scale or 0) or 1.0

    remaining_old, remaining_new = list(range(len(old))), list(range(len(new)))
    counts = {'exact': 0, 'tight': 0, 'loose': 0}
    n_ambiguous = 0
    for label, tol in (('tight', TIGHT), ('loose', LOOSE)):
        if not remaining_old or not remaining_new:
            break
        a = [old[i].as_signature() for i in remaining_old]
        b = [new[j].as_signature() for j in remaining_new]
        m = match_signatures(a, b, scale, **tol)
        n_ambiguous = len(m['ambiguous'])
        used_a, used_b = set(), set()
        for ia, ib, _cost in m['pairs']:
            po, ne = old[remaining_old[ia]], new[remaining_new[ib]]
            kind = 'exact' if po.sig_hash == ne.sig_hash else label
            ne.parent_entity_id, ne.match_kind = po.id, kind
            counts[kind] += 1
            used_a.add(ia)
            used_b.add(ib)
        remaining_old = [x for k, x in enumerate(remaining_old) if k not in used_a]
        remaining_new = [x for k, x in enumerate(remaining_new) if k not in used_b]

    old_index = {o.id: o.entity_index for o in old}
    return {
        'parent_id': str(parent.id),
        'parent_version': parent.version,
        'matched_exact': counts['exact'],
        'matched_tight': counts['tight'],
        'matched_loose': counts['loose'],
        'index_preserved': sum(1 for e in new if e.parent_entity_id is not None
                               and old_index.get(e.parent_entity_id) == e.entity_index),
        'new_faces': [new[j].entity_index for j in remaining_new],
        'removed_parent_faces': [old[i].entity_index for i in remaining_old],
        'ambiguous_last_pass': n_ambiguous,
    }
