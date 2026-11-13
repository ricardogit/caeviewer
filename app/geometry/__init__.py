"""Geometry with persistent entity IDs (Engineering Hub, Fase 1b).

  signature    pure numpy/scipy — signature hashing and 1:1 matching (safe to import anywhere)
  occ_import   pythonOCC — STEP (XDE) import in mm, TopExp face index, signatures, BREP
  gmsh_bridge  Gmsh — BREP import, face_index <-> surface tag, physical groups
  models       Geometry / GeometryEntity tables
  handlers     'geometry.import' job (runs in the geometry worker, needs OCC)

Do NOT import occ_import / gmsh_bridge at module level from web code: the web
process may not have pythonOCC (it is conda-only).
"""
