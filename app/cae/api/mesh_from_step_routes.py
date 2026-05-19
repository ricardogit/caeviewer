"""
POST /api/cae/meshes/from-step

Generates a FEA mesh from an already-uploaded STEP file and registers
the result as a CAEMesh so it immediately appears in the CAEViewer.
"""
import logging
import os
import time

from flask import Blueprint, jsonify, request, current_app

from app.extensions import db
from app.cae.models import CAEMesh

logger = logging.getLogger(__name__)
bp = Blueprint("cae_mesh_from_step", __name__)


def _get_step_path(part_id: str) -> tuple[str, str]:
    """
    Return (file_path, original_filename) for a given Part UUID.
    Tries Part first, then STEPFile as fallback.
    """
    try:
        from app.models.part import Part
        part = Part.query.filter_by(id=part_id).first()
        if part and part.file_path and os.path.exists(part.file_path):
            return part.file_path, part.name or os.path.basename(part.file_path)
    except Exception as exc:
        logger.debug(f"Part lookup failed: {exc}")

    try:
        from app.step_view_pro.models.step_graph import STEPFile
        sf = STEPFile.query.filter_by(id=part_id).first()
        if sf and sf.file_path and os.path.exists(sf.file_path):
            return sf.file_path, sf.original_filename or os.path.basename(sf.file_path)
    except Exception as exc:
        logger.debug(f"STEPFile lookup failed: {exc}")

    raise FileNotFoundError(f"No STEP file found for id={part_id}")


@bp.route("/meshes/from-step", methods=["POST"])
def mesh_from_step():
    """
    Body (JSON):
      part_id    : str   — UUID of the Part / STEPFile record
      refinement : int   — 1 (coarse) … 5 (fine), default 3
      algorithm  : str   — "hxt" | "delaunay" | "frontal", default "hxt"
      optimize   : bool  — run Netgen optimiser (only for tetra), default true
      mesh_type  : str   — "tetra" (default) | "hexa"
    """
    data = request.get_json(force=True, silent=True) or {}

    part_id = data.get("part_id")
    if not part_id:
        return jsonify({"error": 'Missing "part_id"'}), 400

    refinement  = int(data.get("refinement", 3))
    refinement  = max(1, min(5, refinement))          # clamp 1–5
    algorithm   = str(data.get("algorithm", "hxt"))
    optimize    = bool(data.get("optimize", True))
    mesh_type   = str(data.get("mesh_type", "tetra")).lower()
    mesh_family = str(data.get("mesh_family", mesh_type))
    gmsh_extra  = data.get("gmsh_extra") or {}
    if mesh_type not in ("tetra", "hexa", "hybrid"):
        mesh_type = "tetra"

    # Resolve STEP file on disk
    try:
        step_path, original_name = _get_step_path(part_id)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    # Prepare output path
    stem = os.path.splitext(os.path.basename(step_path))[0]
    ts   = int(time.time())
    out_filename = f"{stem}_mesh_{mesh_type}_r{refinement}_{ts}.vtu"

    upload_folder = os.path.join(
        str(current_app.config.get("UPLOAD_FOLDER", "data/uploads")), "cae"
    )
    os.makedirs(upload_folder, exist_ok=True)
    output_vtu = os.path.join(upload_folder, out_filename)

    # Run GMSH
    try:
        from app.cae.services.step_mesher import mesh_step_file
        result = mesh_step_file(
            step_path=step_path,
            output_vtu=output_vtu,
            refinement=refinement,
            algorithm=algorithm,
            optimize=optimize,
            mesh_type=mesh_type,
            gmsh_extra=gmsh_extra,
        )
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503     # GMSH not installed
    except Exception as exc:
        logger.exception(f"Meshing failed for {step_path}")
        return jsonify({"error": f"Meshing failed: {exc}"}), 500

    if result["node_count"] == 0:
        return jsonify({"error": "Meshing produced an empty mesh — check STEP geometry."}), 422

    # Register as CAEMesh
    mesh_record = CAEMesh(
        filename=out_filename,
        original_filename=f"{original_name} (malla {mesh_family}, r={refinement})",
        file_path=output_vtu,
        file_format="vtu",
        node_count=result["node_count"],
        element_count=result["element_count"],
        element_types=result["element_types"],
        bounding_box=result["bounding_box"],
        description=(
            f"Generado desde STEP: {original_name} · "
            f"type={mesh_type} · refinement={refinement} · algorithm={algorithm}"
        ),
    )
    db.session.add(mesh_record)
    db.session.commit()

    return jsonify({
        "mesh_id":        str(mesh_record.id),
        "original_filename": mesh_record.original_filename,
        "node_count":     result["node_count"],
        "element_count":  result["element_count"],
        "element_types":  result["element_types"],
        "mesh_size_used": result["mesh_size_used"],
        "elapsed_s":      result["elapsed_s"],
        "algorithm":      algorithm,
        "refinement":     refinement,
        "mesh_type":      mesh_type,
    }), 201
