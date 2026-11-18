"""Geometric signatures and signature matching (no OCC / Gmsh imports).

A *signature* is a plain dict describing one topological entity::

    {
      "index": 12,                 # 1-based index (TopExp map order) or Gmsh tag
      "surface_type": "plane",     # normalised type name (see normalise_type)
      "area": 123.4,               # area for faces, volume for solids ("measure")
      "centroid": [x, y, z],
      "bbox": [xmin, ymin, zmin, xmax, ymax, zmax],
      "normal": [nx, ny, nz] | None,
      "radius": float | None,
      "solid": 3,                  # owning solid index (0 = free face), optional
    }

``match_signatures`` pairs two lists of signatures 1:1 (OCC faces vs Gmsh surfaces,
or face list of geometry version N vs version N+1).
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Iterable

import numpy as np

# ---------------------------------------------------------------------------
# Type normalisation
# ---------------------------------------------------------------------------


def normalise_type(name: str | None) -> str:
    """Map OCC (``BSplineSurface``) and Gmsh (``BSpline surface``) names to one key."""
    if not name:
        return "unknown"
    key = name.lower().replace(" ", "").replace("_", "")
    for prefix in ("geomabs",):
        if key.startswith(prefix):
            key = key[len(prefix):]
    key = key.replace("surface", "")
    aliases = {
        "": "unknown",
        "other": "unknown",
        "bspline": "bspline",
        "bezier": "bezier",
        "ofrevolution": "revolution",
        "revolution": "revolution",
        "ofextrusion": "extrusion",
        "extrusion": "extrusion",
        "offset": "offset",
        "discrete": "discrete",
    }
    return aliases.get(key, key)


# ---------------------------------------------------------------------------
# Stable hash
# ---------------------------------------------------------------------------


def _round(v: Any, nd: int):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [_round(x, nd) for x in v]
    if isinstance(v, float):
        r = round(v, nd)
        return 0.0 if r == 0 else r  # avoid "-0.0"
    return v


def signature_hash(sig: dict, decimals: int = 4) -> str:
    """SHA-256 of the rounded, canonical signature (index excluded).

    ``decimals`` is in model units (mm): 4 -> 0.1 µm. The hash is meant for
    exact re-import identity (same file, same OCCT); cross-version matching must
    use ``match_signatures`` with tolerances, never hash equality.
    """
    payload = {
        "t": sig.get("surface_type"),
        "a": _round(float(sig["area"]), decimals),
        "c": _round([float(x) for x in sig["centroid"]], decimals),
        "b": _round([float(x) for x in sig["bbox"]], decimals),
        "n": _round([float(x) for x in sig["normal"]], 6) if sig.get("normal") else None,
        "r": _round(float(sig["radius"]), decimals) if sig.get("radius") is not None else None,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def digest_of(hashes: Iterable[str]) -> str:
    h = hashlib.sha256()
    for x in hashes:
        h.update(x.encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class _UF:
    def __init__(self):
        self.p: dict = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def match_signatures(
    a: list[dict],
    b: list[dict],
    scale: float,
    *,
    pos_tol: float = 1e-4,
    measure_tol: float = 1e-3,
    bbox_tol: float = 1e-2,
    group_key: str | None = None,
    type_penalty: float = 1.0,
    ambiguity_margin: float = 0.05,
) -> dict:
    """1:1 matching of signature lists ``a`` -> ``b``.

    Candidates must satisfy (hard gates)
      * centroid distance <= pos_tol * scale
      * relative measure (area/volume) difference <= measure_tol
      * same group (``group_key``), if given
    Cost (soft, dimensionless, ~0 for an exact match)
      dc/(pos_tol*scale) + dm/measure_tol + dbbox/(bbox_tol*scale) + type mismatch.
    Ambiguity: an entity whose best and second-best candidates differ in cost by
    less than ``ambiguity_margin`` (i.e. geometrically indistinguishable within
    tolerance), e.g. coincident contact faces of two touching solids.

    Returns dict with ``pairs`` [(ia, ib, cost)], ``unmatched_a``, ``unmatched_b``,
    ``ambiguous`` [{a, candidates}], ``type_mismatch`` and ``max_dev`` statistics
    (absolute centroid distance, relative measure diff, bbox deviation) over pairs.
    """
    from scipy.optimize import linear_sum_assignment
    from scipy.spatial import cKDTree

    scale = float(scale) if scale and scale > 0 else 1.0
    r_pos = pos_tol * scale
    measure_floor = (1e-9 * scale) ** 2  # area floor for degenerate faces

    def grp(s):
        return s.get(group_key) if group_key else None

    groups_a: dict = defaultdict(list)
    groups_b: dict = defaultdict(list)
    for i, s in enumerate(a):
        groups_a[grp(s)].append(i)
    for j, s in enumerate(b):
        groups_b[grp(s)].append(j)

    pairs: list[tuple[int, int, float]] = []
    ambiguous: list[dict] = []
    matched_a: set[int] = set()
    matched_b: set[int] = set()

    def cost(sa, sb) -> tuple[float, float, float, float]:
        ca, cb = np.asarray(sa["centroid"], float), np.asarray(sb["centroid"], float)
        dc = float(np.linalg.norm(ca - cb))
        ma, mb = float(sa["area"]), float(sb["area"])
        dm = abs(ma - mb) / max(abs(ma), abs(mb), measure_floor)
        ba, bb = np.asarray(sa["bbox"], float), np.asarray(sb["bbox"], float)
        db = float(np.max(np.abs(ba - bb)))
        c = dc / r_pos + dm / measure_tol + db / (bbox_tol * scale)
        if sa.get("surface_type") and sb.get("surface_type") and \
                sa["surface_type"] != sb["surface_type"]:
            c += type_penalty
        return c, dc, dm, db

    for g, ia_list in groups_a.items():
        ib_list = groups_b.get(g, [])
        if not ib_list:
            continue
        cb = np.array([b[j]["centroid"] for j in ib_list], float)
        tree = cKDTree(cb)
        edges: dict[tuple[int, int], float] = {}
        cand: dict[int, list[tuple[float, int]]] = defaultdict(list)
        uf = _UF()
        for i in ia_list:
            near = tree.query_ball_point(np.asarray(a[i]["centroid"], float), r_pos)
            for k in near:
                j = ib_list[k]
                c, dc, dm, db = cost(a[i], b[j])
                if dm > measure_tol:
                    continue
                edges[(i, j)] = c
                cand[i].append((c, j))
                uf.union(("a", i), ("b", j))

        for i, lst in cand.items():
            lst.sort()
            if len(lst) >= 2 and lst[1][0] - lst[0][0] < ambiguity_margin:
                ambiguous.append({"a": i, "candidates": [j for c, j in lst
                                                          if c - lst[0][0] < ambiguity_margin]})

        # connected components -> exact assignment per component
        comps: dict = defaultdict(lambda: ([], []))
        for (i, j) in edges:
            root = uf.find(("a", i))
            ai, bj = comps[root]
            if i not in ai:
                ai.append(i)
            if j not in bj:
                bj.append(j)
        for ai, bj in comps.values():
            if len(ai) == 1 and len(bj) == 1:
                i, j = ai[0], bj[0]
                pairs.append((i, j, edges[(i, j)]))
                continue
            big = 1e9
            M = np.full((len(ai), len(bj)), big)
            for r, i in enumerate(ai):
                for c_, j in enumerate(bj):
                    if (i, j) in edges:
                        M[r, c_] = edges[(i, j)]
            rows, cols = linear_sum_assignment(M)
            for r, c_ in zip(rows, cols):
                if M[r, c_] < big:
                    pairs.append((ai[r], bj[c_], float(M[r, c_])))

    for i, j, _ in pairs:
        matched_a.add(i)
        matched_b.add(j)

    devs = [cost(a[i], b[j]) for i, j, _ in pairs]
    type_mismatch = [(i, j) for i, j, _ in pairs
                     if a[i].get("surface_type") != b[j].get("surface_type")]
    pairs.sort()
    return {
        "pairs": pairs,
        "unmatched_a": sorted(set(range(len(a))) - matched_a),
        "unmatched_b": sorted(set(range(len(b))) - matched_b),
        "ambiguous": ambiguous,
        "type_mismatch": type_mismatch,
        "max_dev": {
            "centroid_abs": max((d[1] for d in devs), default=0.0),
            "centroid_rel": max((d[1] for d in devs), default=0.0) / scale,
            "measure_rel": max((d[2] for d in devs), default=0.0),
            "bbox_abs": max((d[3] for d in devs), default=0.0),
            "cost": max((d[0] for d in devs), default=0.0),
        },
        "tolerances": {"pos_tol": pos_tol, "measure_tol": measure_tol,
                       "bbox_tol": bbox_tol, "scale": scale},
    }


def bbox_diagonal(bbox: list[float]) -> float:
    return math.dist(bbox[:3], bbox[3:])
