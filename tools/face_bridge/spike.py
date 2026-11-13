"""Fase 1a spike CLI.

    python -m tools.face_bridge.spike [--examples examples] [--out data/face_bridge_spike]
                                      [--no-mesh] [--only SUBSTR ...]

Per STEP file:
  (a) import twice (XDE, mm) and compare face indices + signatures (in-process);
      compare digest with the previous run's summary.json if present (cross-process)
  (b) write BREP, import in Gmsh with healing off, match faces 1:1
  (c) optional: physical groups F_<face> on 3 faces, coarse tet mesh, .inp check
Also: version re-matching "Pedestal - copia" vs "Pedestalx".
"""
from __future__ import annotations

import argparse
import json
import re
import time
import traceback
from pathlib import Path

from app.geometry import gmsh_bridge as gb
from app.geometry.occ_import import compute_signatures, read_step, write_brep
from app.geometry.signature import digest_of, match_signatures

VERSION_PAIR = ("Pedestal - copia", "Pedestalx")


def _safe(stem: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)


def _pick_pg_faces(faces: list[dict]) -> list[int]:
    by_area = sorted(faces, key=lambda f: f["area"])
    picks = [by_area[-1]["index"]]
    small = [f for f in by_area if f["area"] > 1e-6]
    if small and small[0]["index"] not in picks:
        picks.append(small[0]["index"])
    cyl = next((f for f in faces if f["surface_type"] == "cylinder"
                and f["index"] not in picks), None)
    if cyl:
        picks.append(cyl["index"])
    return picks


MESH_ATTEMPTS = ((1, 1.0), (10, 1.0), (1, 0.5), (4, 0.5), (1, 0.25))


def _mesh_child(brep, face_to_tag, picks, inp, size, result_path, expected, heal):
    """Forked process: one fresh Gmsh session (re-import) per attempt."""
    import gmsh
    errors = []
    out = None
    for algo, factor in MESH_ATTEMPTS:
        try:
            with gb.gmsh_session("mesh", heal=heal):
                gb.import_brep(brep)
                # the tags of the picked faces must not move in a fresh session
                moved = [fi for fi, c in expected.items()
                         if max(abs(a - b) for a, b in zip(gmsh.model.occ.getCenterOfMass(
                             2, face_to_tag[fi]), c)) > 1e-6 * max(1.0, size)]
                if moved:
                    out = {"mesh_error": f"gmsh tags changed on re-import for faces {moved}"}
                    break
                out = gb.physical_groups_mesh_inp(face_to_tag, picks, inp, size * factor, algo)
                out["size_factor"] = factor
                out["tags_verified_on_reimport"] = True
                break
        except Exception as exc:
            errors.append(f"algo {algo} x{factor}: {type(exc).__name__}: {exc}")
            out = None
        Path(result_path).write_text(json.dumps({"mesh_error": " | ".join(errors),
                                                 "partial": True}))
    if out is None:
        out = {"mesh_error": " | ".join(errors)}
    if errors:
        out["mesh_attempt_errors"] = errors
    Path(result_path).write_text(json.dumps(out))


def _mesh_with_timeout(brep, face_to_tag, picks, inp, size, timeout_s, expected, heal=False) -> dict:
    """Gmsh has no timeout and can stall on hard B-spline faces: isolate it.

    Re-importing the same BREP in a fresh session yields the same Gmsh tags
    — verified in the child against the expected centroids of the picked faces.
    """
    import multiprocessing as mp
    result_path = inp + ".result.json"
    Path(result_path).unlink(missing_ok=True)
    t0 = time.perf_counter()
    proc = mp.get_context("fork").Process(
        target=_mesh_child, args=(brep, face_to_tag, picks, inp, size, result_path, expected, heal))
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.kill()
        proc.join()
        prior = json.loads(Path(result_path).read_text()) if Path(result_path).exists() else {}
        Path(result_path).unlink(missing_ok=True)
        err = f"timeout after {timeout_s}s (killed)"
        if prior.get("mesh_error"):
            err = prior["mesh_error"] + " | " + err
        return {"faces": picks, "mesh_error": err,
                "mesh_seconds": round(time.perf_counter() - t0, 1)}
    if not Path(result_path).exists():
        return {"faces": picks, "mesh_error": f"mesh child exited with code {proc.exitcode}"}
    out = json.loads(Path(result_path).read_text())
    Path(result_path).unlink(missing_ok=True)
    return out


def run_file(step: Path, out_dir: Path, do_mesh: bool, previous: dict | None,
             mesh_timeout: int = 300, heal: bool = False) -> tuple[dict, dict]:
    rec: dict = {"file": step.name, "size_mb": round(step.stat().st_size / 2**20, 2)}
    t = time.perf_counter()
    g1 = read_step(step)
    s1 = compute_signatures(g1)
    rec["import1_s"] = round(g1.import_seconds, 2)
    rec["sig_s"] = round(time.perf_counter() - t - g1.import_seconds, 2)
    rec.update(n_faces=g1.n_faces, n_solids=g1.n_solids, is_assembly=g1.is_assembly,
               n_free_shapes=g1.n_free_shapes, n_named_faces=len(g1.face_names),
               n_named_solids=len(g1.solid_names), scale_mm=round(s1["scale"], 3),
               bbox=[round(x, 3) for x in s1["bbox"]])
    types: dict = {}
    for f in s1["faces"]:
        types[f["surface_type"]] = types.get(f["surface_type"], 0) + 1
    rec["surface_types"] = types

    # (a) determinism -------------------------------------------------------
    g2 = read_step(step)
    s2 = compute_signatures(g2)
    rec["import2_s"] = round(g2.import_seconds, 2)
    h1 = [f["hash"] for f in s1["faces"]]
    h2 = [f["hash"] for f in s2["faces"]]
    rec["digest"] = digest_of(h1)
    rec["determinism_in_process"] = (g1.n_faces == g2.n_faces and h1 == h2)
    if not rec["determinism_in_process"]:
        rec["determinism_diff"] = [i + 1 for i, (a, b) in enumerate(zip(h1, h2)) if a != b][:50]
    prev = (previous or {}).get(step.name)
    rec["determinism_cross_run"] = None if prev is None else (prev.get("digest") == rec["digest"])
    del g2, s2

    # (b) Gmsh bridge -------------------------------------------------------
    brep = out_dir / f"{_safe(step.stem)}.brep"
    write_brep(g1, brep)
    try:
        rec["gmsh_heal"] = heal
        with gb.gmsh_session(_safe(step.stem), heal=heal):
            t0 = time.perf_counter()
            gb.import_brep(str(brep))
            rec["gmsh_import_s"] = round(time.perf_counter() - t0, 2)
            gm = gb.gmsh_signatures()
            res = gb.match_faces(s1, gm, strict=False)
            rec["bridge"] = {k: v for k, v in res.items() if k != "face_to_tag"}
            rec["bridge"]["n_type_mismatch"] = len(res["type_mismatch"])
            rec["bridge"]["type_mismatch"] = res["type_mismatch"][:20]
            rec["bridge"]["gmsh_scale_mm"] = round(gm["scale"], 3)
            face_to_tag = res["face_to_tag"]
        # (c) PG + mesh + inp, in a child process with a hard timeout ----------
        if do_mesh and res["ok"]:
            picks = _pick_pg_faces(s1["faces"])
            rec["mesh"] = _mesh_with_timeout(
                str(brep), face_to_tag, picks, str(out_dir / f"{_safe(step.stem)}.inp"),
                s1["scale"] / 15, mesh_timeout,
                {fi: s1["faces"][fi - 1]["centroid"] for fi in picks}, heal)
        elif do_mesh:
            rec["mesh"] = {"skipped": "bridge not ok"}
    except Exception as exc:
        rec["bridge_error"] = f"{type(exc).__name__}: {exc}"
        rec["bridge_traceback"] = traceback.format_exc()
        face_to_tag = {}

    detail = {"file": step.name, "signatures": s1, "face_to_gmsh_tag": face_to_tag}
    return rec, detail


def compare_versions(details: dict) -> dict | None:
    a_name, b_name = VERSION_PAIR
    a = next((d for k, d in details.items() if Path(k).stem == a_name), None)
    b = next((d for k, d in details.items() if Path(k).stem == b_name), None)
    if not a or not b:
        return None
    sa, sb = a["signatures"], b["signatures"]
    scale = max(sa["scale"], sb["scale"])
    out = {"a": a["file"], "b": b["file"], "n_a": len(sa["faces"]), "n_b": len(sb["faces"])}
    out["exact_hash_equal"] = len({f["hash"] for f in sa["faces"]} & {f["hash"] for f in sb["faces"]})
    out["same_index_same_hash"] = sum(1 for fa, fb in zip(sa["faces"], sb["faces"])
                                      if fa["hash"] == fb["hash"])
    for label, tol in (("tight", {}), ("loose", {"pos_tol": 1e-3, "measure_tol": 1e-2})):
        m = match_signatures(sa["faces"], sb["faces"], scale, **tol)
        out[label] = {
            "matched": len(m["pairs"]),
            "index_preserved": sum(1 for i, j, _ in m["pairs"] if i == j),
            "unmatched_a": [sa["faces"][i]["index"] for i in m["unmatched_a"]][:50],
            "unmatched_b": [sb["faces"][j]["index"] for j in m["unmatched_b"]][:50],
            "n_ambiguous": len(m["ambiguous"]),
            "max_dev": m["max_dev"],
            "tolerances": m["tolerances"],
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", default="examples")
    ap.add_argument("--out", default="data/face_bridge_spike")
    ap.add_argument("--no-mesh", action="store_true")
    ap.add_argument("--mesh-timeout", type=int, default=300)
    ap.add_argument("--heal", action="store_true",
                    help="keep Gmsh OCC healing defaults (OCCAutoFix=1) instead of disabling it")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = sorted(p for p in Path(args.examples).iterdir()
                   if p.suffix.lower() in (".step", ".stp"))
    if args.only:
        steps = [p for p in steps if any(s.lower() in p.name.lower() for s in args.only)]

    summary_path = out_dir / "summary.json"
    previous = None
    if summary_path.exists():
        previous = {r["file"]: r for r in json.loads(summary_path.read_text()).get("files", [])}

    records, details = [], {}
    for step in steps:
        print(f"== {step.name}", flush=True)
        try:
            rec, det = run_file(step, out_dir, not args.no_mesh, previous, args.mesh_timeout, args.heal)
            details[step.name] = det
            (out_dir / f"{_safe(step.stem)}.json").write_text(json.dumps(det))
        except Exception as exc:
            rec = {"file": step.name, "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()}
        records.append(rec)
        b = rec.get("bridge", {})
        print(json.dumps({k: rec.get(k) for k in ("n_faces", "n_solids", "is_assembly",
                                                  "determinism_in_process",
                                                  "determinism_cross_run", "error",
                                                  "bridge_error")}
                         | {"matched": b.get("matched"), "problems": b.get("problems"),
                            "same_order": b.get("same_order"),
                            "inp_ok": rec.get("mesh", {}).get("inp_ok"),
                            "mesh_error": rec.get("mesh", {}).get("mesh_error")}),
              flush=True)

    # version pair may come from earlier per-file runs: load their JSON from disk
    for stem in VERSION_PAIR:
        p = out_dir / f"{_safe(stem)}.json"
        if not any(Path(k).stem == stem for k in details) and p.exists():
            det = json.loads(p.read_text())
            details[det["file"]] = det
    versions = compare_versions(details)
    if previous is not None and args.only:
        # keep records of files not re-run this time
        seen = {r["file"] for r in records}
        records += [r for f, r in previous.items() if f not in seen]
    summary = {"files": records, "version_compare": versions}
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    if versions:
        print("== versions", json.dumps({k: versions[k] for k in
                                         ("n_a", "n_b", "exact_hash_equal")}
                                        | {"tight": versions["tight"]["matched"],
                                           "loose": versions["loose"]["matched"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
