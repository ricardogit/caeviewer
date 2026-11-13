"""OCC face index <-> Gmsh surface tag bridge (option C: BREP + signature matching).

Gmsh bundles its own OCCT, so we never rely on tag order or native pointers. The
BREP written by pythonOCC is imported with every Gmsh healing option disabled,
then each Gmsh entity is matched to the OCC signature by (solid group, centroid,
area, bbox, type). Any unmatched or ambiguous face is an error in strict mode:
a load must never land on the wrong face.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from pathlib import Path

import gmsh

from .signature import bbox_diagonal, match_signatures, normalise_type

HEALING_OFF = {
    "Geometry.OCCFixDegenerated": 0,
    "Geometry.OCCFixSmallEdges": 0,
    "Geometry.OCCFixSmallFaces": 0,
    "Geometry.OCCSewFaces": 0,
    "Geometry.OCCMakeSolids": 0,
    "Geometry.OCCAutoFix": 0,
}

DEFAULT_TOL = {"pos_tol": 1e-4, "measure_tol": 1e-3, "bbox_tol": 1e-2}


class FaceBridgeError(RuntimeError):
    def __init__(self, message: str, details: dict):
        super().__init__(message)
        self.details = details


@contextmanager
def gmsh_session(name: str = "bridge", verbosity: int = 1, heal: bool = False):
    """Gmsh session. heal=False disables every OCC healing option (the default for
    the bridge); heal=True keeps Gmsh defaults (OCCAutoFix=1). Matching is done
    after import either way, so it stays valid as long as faces are preserved."""
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", verbosity)
        for k, v in ({} if heal else HEALING_OFF).items():
            try:
                gmsh.option.setNumber(k, v)
            except Exception:
                pass
        gmsh.model.add(name)
        yield gmsh
    finally:
        gmsh.finalize()


def import_brep(brep_path: str) -> list[tuple[int, int]]:
    tags = gmsh.model.occ.importShapes(str(brep_path), highestDimOnly=False)
    gmsh.model.occ.synchronize()
    return tags


def gmsh_signatures() -> dict:
    """Signatures of all Gmsh surfaces and volumes in the current model."""
    vols = []
    surf_owner: dict[int, int] = {}
    for _, vt in gmsh.model.getEntities(3):
        c = gmsh.model.occ.getCenterOfMass(3, vt)
        vols.append({"index": vt, "surface_type": None,
                     "area": gmsh.model.occ.getMass(3, vt),
                     "centroid": list(c),
                     "bbox": list(gmsh.model.getBoundingBox(3, vt))})
        _, down = gmsh.model.getAdjacencies(3, vt)
        for st in down:
            surf_owner.setdefault(int(st), vt)
    surfs = []
    for _, st in gmsh.model.getEntities(2):
        c = gmsh.model.occ.getCenterOfMass(2, st)
        surfs.append({"index": st,
                      "gmsh_type": gmsh.model.getType(2, st),
                      "surface_type": normalise_type(gmsh.model.getType(2, st)),
                      "area": gmsh.model.occ.getMass(2, st),
                      "centroid": list(c),
                      "bbox": list(gmsh.model.getBoundingBox(2, st)),
                      "volume_tag": surf_owner.get(st, 0)})
    bbox = list(gmsh.model.getBoundingBox(-1, -1))
    return {"surfaces": surfs, "volumes": vols, "bbox": bbox, "scale": bbox_diagonal(bbox)}


def match_faces(occ: dict, gm: dict, *, strict: bool = True, tol: dict | None = None) -> dict:
    """Match OCC faces to Gmsh surfaces. Returns face_index -> gmsh tag plus a report.

    Strategy: solids first (volume, centroid), then faces restricted to the
    matched solid group, which separates coincident contact faces of touching
    solids. Falls back to ungrouped face matching if solids cannot be paired 1:1.
    """
    tol = {**DEFAULT_TOL, **(tol or {})}
    scale = occ["scale"]
    report: dict = {"n_occ_faces": len(occ["faces"]), "n_gmsh_surfaces": len(gm["surfaces"]),
                    "n_occ_solids": len(occ["solids"]), "n_gmsh_volumes": len(gm["volumes"]),
                    "grouped_by_solid": False}

    # --- solids -------------------------------------------------------------
    vol_to_solid: dict[int, int] = {}
    if occ["solids"] and len(occ["solids"]) == len(gm["volumes"]):
        sm = match_signatures(occ["solids"], gm["volumes"], scale, **tol)
        report["solid_match"] = {k: sm[k] for k in ("unmatched_a", "unmatched_b",
                                                    "ambiguous", "max_dev")}
        if not sm["unmatched_a"] and not sm["unmatched_b"] and not sm["ambiguous"]:
            for i, j, _ in sm["pairs"]:
                vol_to_solid[gm["volumes"][j]["index"]] = occ["solids"][i]["index"]
            report["grouped_by_solid"] = True

    occ_faces = [dict(f) for f in occ["faces"]]
    gm_faces = [dict(s) for s in gm["surfaces"]]
    if report["grouped_by_solid"]:
        for s in gm_faces:
            s["solid"] = vol_to_solid.get(s["volume_tag"], 0)
        group_key = "solid"
    else:
        group_key = None

    t0 = time.perf_counter()
    fm = match_signatures(occ_faces, gm_faces, scale, group_key=group_key, **tol)
    report["match_seconds"] = time.perf_counter() - t0

    face_to_tag = {occ_faces[i]["index"]: gm_faces[j]["index"] for i, j, _ in fm["pairs"]}
    report.update({
        "matched": len(face_to_tag),
        "unmatched_occ": [occ_faces[i]["index"] for i in fm["unmatched_a"]],
        "unmatched_gmsh": [gm_faces[j]["index"] for j in fm["unmatched_b"]],
        "ambiguous": [{"face": occ_faces[x["a"]]["index"],
                       "gmsh_candidates": [gm_faces[j]["index"] for j in x["candidates"]]}
                      for x in fm["ambiguous"]],
        "type_mismatch": [(occ_faces[i]["index"], gm_faces[j]["index"],
                           occ_faces[i]["surface_type"], gm_faces[j]["surface_type"])
                          for i, j in fm["type_mismatch"]],
        "max_dev": fm["max_dev"],
        "tolerances": fm["tolerances"],
        "same_order": all(f == t for f, t in face_to_tag.items()),
    })

    problems = []
    if report["n_occ_faces"] != report["n_gmsh_surfaces"]:
        problems.append(f"face count differs: OCC {report['n_occ_faces']} "
                        f"vs Gmsh {report['n_gmsh_surfaces']}")
    if report["unmatched_occ"]:
        problems.append(f"{len(report['unmatched_occ'])} OCC faces unmatched")
    if report["unmatched_gmsh"]:
        problems.append(f"{len(report['unmatched_gmsh'])} Gmsh surfaces unmatched")
    if report["ambiguous"]:
        problems.append(f"{len(report['ambiguous'])} ambiguous faces")
    report["problems"] = problems
    report["ok"] = not problems
    if strict and problems:
        raise FaceBridgeError("; ".join(problems), {"face_to_tag": face_to_tag, **report})
    return {"face_to_tag": face_to_tag, **report}


def physical_groups_mesh_inp(face_to_tag: dict[int, int], face_indices: list[int],
                             out_inp: str, mesh_size: float, algo: int = 1) -> dict:
    """One attempt: F_<face_index> physical groups, tet mesh, write .inp and check it.

    Raises on failure (including an empty volume mesh, which HXT can return
    silently). Call in a fresh session per attempt: retrying generate() after a
    failed tetgen run in the same session never produced tets in the spike.
    """
    t0 = time.perf_counter()
    out: dict = {"faces": face_indices, "algorithm3d": algo, "mesh_size": mesh_size}
    for fi in face_indices:
        gmsh.model.addPhysicalGroup(2, [face_to_tag[fi]], name=f"F_{fi}")
    vtags = [t for _, t in gmsh.model.getEntities(3)]
    if vtags:
        gmsh.model.addPhysicalGroup(3, vtags, name="SOLID")
    gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
    gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size * 0.05)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
    gmsh.option.setNumber("Mesh.Algorithm3D", algo)
    gmsh.option.setNumber("Mesh.SaveGroupsOfNodes", 1)
    gmsh.option.setNumber("General.NumThreads", 4)
    gmsh.model.mesh.generate(3 if vtags else 2)
    n_tets = len(gmsh.model.mesh.getElementsByType(4)[0]) if vtags else 0
    if vtags and not n_tets:
        raise RuntimeError("no tetrahedra generated")
    _, ntags, _ = gmsh.model.mesh.getNodes()
    out["n_nodes"] = int(len(ntags))
    out["n_tets"] = int(n_tets)
    per_face = {}
    for d, pg in gmsh.model.getPhysicalGroups(2):
        nodes, _ = gmsh.model.mesh.getNodesForPhysicalGroup(d, pg)
        per_face[gmsh.model.getPhysicalName(d, pg)] = int(len(nodes))
    out["nodes_per_group"] = per_face
    gmsh.write(str(out_inp))
    text = Path(out_inp).read_text(errors="ignore")
    out["inp_nsets"] = sorted(set(re.findall(r"\*NSET,\s*NSET=(F_\d+)", text, re.I)))
    out["inp_elsets"] = sorted(set(re.findall(r"\*ELSET,\s*ELSET=(F_\d+)", text, re.I)))
    expected = {f"F_{fi}" for fi in face_indices}
    out["inp_ok"] = expected <= set(out["inp_nsets"]) and all(v > 0 for v in per_face.values())
    out["mesh_seconds"] = time.perf_counter() - t0
    return out
