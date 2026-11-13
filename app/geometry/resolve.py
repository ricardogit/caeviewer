"""Resolve persistent face IDs (GeometryEntity UUIDs) against a geometry version.

Boundary conditions store entity UUIDs. When the GEOMETRY node of a study
points at another version of the same part, each stored face is carried along
the ``parent_entity_id`` chain written by the version remap (H1b), in either
direction (old BC → new geometry, or new BC → old geometry). Faces without a
match (deleted or changed beyond the remap tolerances) resolve to ``None`` and
must be re-selected: a load must never land on a guessed face.
"""
from __future__ import annotations

import uuid as _uuid

from app.extensions import db
from app.geometry.models import Geometry, GeometryEntity


def _uuid_or_none(v):
    try:
        return _uuid.UUID(str(v))
    except (ValueError, TypeError):
        return None


def resolve_faces(geometry_id, entity_ids) -> dict:
    """Map each entity id to {index, status, entity_id} on ``geometry_id``.

    status: ``exact`` (face of this version), ``carried`` (same face via the
    version remap), ``missing`` (no counterpart), ``invalid`` (not a face / bad id /
    other part).
    """
    geo = db.session.get(Geometry, geometry_id)
    if geo is None:
        raise ValueError(f'La geometría {geometry_id} no existe.')
    ids = [str(i) for i in entity_ids]
    wanted = {i: _uuid_or_none(i) for i in ids}
    rows = (GeometryEntity.query.filter(GeometryEntity.id.in_([u for u in wanted.values() if u]))
            .all()) if any(wanted.values()) else []
    by_id = {str(r.id): r for r in rows}

    out: dict = {}
    pending = []
    for i in ids:
        r = by_id.get(i)
        if r is None or r.entity_type != 'face':
            out[i] = {'index': None, 'status': 'invalid', 'entity_id': None}
        elif r.geometry_id == geo.id:
            out[i] = {'index': r.entity_index, 'status': 'exact', 'entity_id': i}
        else:
            pending.append(r)
    if not pending:
        return out

    # Every face of the lineage, with its parent link, to walk chains both ways.
    lineage = (db.session.query(GeometryEntity.id, GeometryEntity.parent_entity_id,
                                GeometryEntity.geometry_id, GeometryEntity.entity_index)
               .join(Geometry, Geometry.id == GeometryEntity.geometry_id)
               .filter(Geometry.lineage_id == geo.lineage_id, GeometryEntity.entity_type == 'face')
               .all())
    parent = {e.id: e.parent_entity_id for e in lineage}
    here = {e.id: e.entity_index for e in lineage if e.geometry_id == geo.id}

    def ancestors(eid):
        seen = []
        while eid is not None and eid not in seen and len(seen) < 1000:
            seen.append(eid)
            eid = parent.get(eid)
        return seen

    # older stored face → this version: a face here whose ancestor chain contains it
    carried_from_old = {}
    for fid, idx in here.items():
        for anc in ancestors(fid)[1:]:
            carried_from_old.setdefault(anc, (fid, idx))

    for r in pending:
        i = str(r.id)
        other = db.session.get(Geometry, r.geometry_id)
        if other is None or other.lineage_id != geo.lineage_id:
            out[i] = {'index': None, 'status': 'invalid', 'entity_id': None}
            continue
        hit = carried_from_old.get(r.id)
        if hit is None:
            # newer stored face → this (older) version: walk the stored face's own chain
            for anc in ancestors(r.id)[1:]:
                if anc in here:
                    hit = (anc, here[anc])
                    break
        out[i] = ({'index': hit[1], 'status': 'carried', 'entity_id': str(hit[0])} if hit
                  else {'index': None, 'status': 'missing', 'entity_id': None})
    return out
