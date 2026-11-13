"""Face bridge spike (Fase 1a): persistent CAD face IDs and the OCC -> Gmsh mapping.

Modules
-------
signature   pure-Python/numpy: signature hashing and generic signature matching
occ_import  pythonOCC: STEP (XDE) import in mm, deterministic face index, face signatures
gmsh_bridge Gmsh: BREP import with healing disabled, face_index <-> surface tag matching,
            physical groups, coarse tet mesh and .inp export check
spike       CLI that runs everything over examples/*.STEP and writes JSON + summary

Designed to be moved into app/ later as a library: occ_import and gmsh_bridge expose
plain functions returning JSON-serialisable dicts; signature.py has no OCC/Gmsh imports.
"""
