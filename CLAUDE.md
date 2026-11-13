# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CAE Viewer is a full-stack engineering platform with three integrated modes:

- **Results mode** (FASE 9): 3D field viewer of the active study's finished runs (Design → Simular → Resultados).
- **Design mode** (FASE 1-3): Engineering concept graph editor + FEM solver. Build design graphs (GEOMETRY, MATERIAL, BC, LOAD, RESULT nodes), run structural simulations with adaptive meshing, stream solver progress via WebSocket.
- **STEP mode**: Upload/view STEP files (.stp/.step/.p21), browse entity graphs, annotate with PMI, measure, section-cut, and export.
- **CAE mode**: Upload FEA mesh files (VTK, Abaqus .inp, Nastran .bdf, GMSH .msh, LS-DYNA .k/.zip, Exodus, XDMF, MED), visualize with field coloring, animate time steps, section-cut, and quality metrics.

**Roadmap:** `PLAN_CAE_NUEVA_GENERACION.md` is the master plan (phases FASE 0-9; "nothing happens outside
the DesignGraph"). The Engineering Hub work (job queue, versioned geometry, catalog) is numbered H0-H1d to
avoid clashing; it is infrastructure for that plan. The own FEM kernel comes before external solver adapters.

## Running the Application

**Backend (Flask, port 8080):**
```
python run.py
# or with env override:
FLASK_ENV=development python run.py
```

**Frontend dev server (Vite, port 3000):**
```
cd frontend
npm run dev
```

**Frontend production build** (output goes to `frontend/dist/`, served by Flask at `/step-view/`):
```
cd frontend
npm run build
```

**Job worker (required for solver runs):** solvers never run in the web process. Jobs live in the
`jobs` table (Postgres queue, `SELECT … FOR UPDATE SKIP LOCKED`) and are executed by:
```
python -m app.jobs.worker --queues default,solve
```
Progress flows worker → `NOTIFY job_events` → web listener (started in `run.py`) → socket.io
(`job_update` broadcast, plus wrapped events like `solver_progress` to their room).

**Geometry (Hub H1b):** `app/geometry/` — STEP files are stored content-addressed under `data/geometry/files/`;
the `geometry.import` job (queue `geometry`, needs pythonOCC → run the worker in the Docker image) fills
`geometry_entities` with one row per face/solid (TopExp index + signature). Re-import keeps entity UUIDs;
a new version (`parent_id`) links faces to the previous version by signature (`parent_entity_id`,
`match_kind`). The import also writes `geometry/<id>/view.glb` (H1c): uncompressed, one vertex block
per CAD face, vertex attribute `_FACE_ID` = 1-based face index (Three.js reads it as `_face_id`). Never
Draco-compress it (Draco reorders vertices). Frontend: **Geometría** mode → `components/Geometry/*` +
`stores/geometryStore.js` (picking/highlight via per-vertex colors). DB file URIs are relative to `DATA_DIR`. `occ_import`/`gmsh_bridge` must never be
imported at module level from web code.

**Hub catalog (H1d):** the Hub (Catálogo mode; Design stays the default mode) renders cards from the `solver_catalog` table. Add or
edit tools in `app/catalog/seed_data.py`, then run `flask catalog seed` (idempotent upsert by slug;
`--prune` disables removed slugs). Run it once after `flask db upgrade` on a fresh database.

**Docker:** `docker/geometry.Dockerfile` (micromamba + pythonocc-core 7.7.2 + Gmsh wheel) is the
image for workers and geometry tools; `docker compose` runs `worker-solve` and `worker-geometry`.
From Git Bash, prefix `docker run -e VAR=/path` with `MSYS_NO_PATHCONV=1`.

The Flask app serves the built SPA from `frontend/dist/` at `/step-view/`. In development, the Vite dev server proxies API calls to Flask on port 8080.

**Database**: PostgreSQL. Default URI: `postgresql://postgres:postgres@localhost:5432/caedb`. **Alembic is the only schema mechanism** — run `flask db upgrade` (startup only warns if the DB is behind head). SQLAlchemy is pinned `<2.1` (2.1 defaults `postgresql://` to psycopg 3).

**Environment**: Copy `.env.example` (in `frontend/`) or create `.env` / `.env.local` at the repo root. Key variables: `DATABASE_URL`, `FLASK_ENV`, `API_PORT`, `MAX_UPLOAD_SIZE_MB`, `CORS_ORIGINS`.

## Frontend Commands

```
cd frontend
npm run lint          # ESLint (0 warnings threshold)
npm run lint:fix      # auto-fix
npm run test          # Vitest
npm run test:coverage # coverage report
npm run format        # Prettier
npm run analyze       # bundle visualizer
```

## Architecture

### Backend (`app/`)

```
app/
  __init__.py             # Flask factory (create_app), registers blueprints + models
  extensions.py           # db, migrate, compress singletons
  models/                 # Core SQLAlchemy models (Part, STEPFileHeader, STEPEntity, etc.)
  cae/
    models/mesh.py        # CAEMesh + CAEField (PostgreSQL + JSONB)
    api/cae_routes.py     # REST: upload/list/get/delete meshes, field data, download
    api/ai_routes.py      # AI analysis endpoints
    api/mesh_from_step_routes.py  # STEP→FEA mesh generation trigger
    services/mesh_parser.py       # Parses VTK/INP/BDF/MSH/EXO/MED/XDMF/LS-DYNA via meshio + native parsers
    services/step_mesher.py       # STEP→mesh via GMSH (tetra/hexa/hybrid strategies)
  design/                 # FASE 1-3: Design Graph + FEM Solver
    models/
      graph.py            # DesignGraph, DesignNode, DesignEdge (SQLAlchemy)
      simulation.py       # SimulationRun (solver state, convergence log, results ref)
      material.py         # MaterialModel (E, nu, rho, model_type)
      physics.py          # PhysicsConfig (solver type, tolerance, adaptive_meshing flag)
      validation.py       # ExperimentalRecord, SimExperimentCorrelation
    services/
      graph_service.py    # DesignGraphService (CRUD, topological sort, validation, hash)
      fem/
        mesh.py           # FEMMesh (nodes, elements, node_sets); generate_cantilever()
        elements.py       # T4 stiffness matrix, B matrix, von Mises stress
        constitutive.py   # LinearElasticIsotropic, Fourier, stubs for FASE 2+
        assembler.py      # assemble K (COO→CSR), F, apply_bcs (penalty method)
        solver.py         # FEMSolverDispatcher (direct spsolve, CG-ILU, tier enforcement)
        nonlinear.py      # NewtonRaphson (NR iteration for material non-linearity)
        kernel.py         # FEMKernel (orchestrates mesh→assembly→solve→postprocess→HDF5)
      traceability/
        hasher.py         # SHA-256 graph/simulation hashing for reproducibility
    api/
      graph_routes.py     # POST/GET/PUT/DELETE graph/nodes/edges; validate; import
      solver_routes.py    # POST /<graph_id>/run (async), /test/cantilever (validation)
  step_view_pro/
    __init__.py           # register_step_view_blueprints() — 12 blueprints at /api/step-view/*
    backend/api/          # viewer, upload, graph, features, pmi, geometry, analysis,
                          # measurement, export, comparison, performance, markup routes
    backend/step_processor.py     # STEP parsing pipeline
    backend/geometry_processor.py # Geometry extraction → GLB via trimesh
    backend/step_to_glb_converter.py
    backend/pmi_parser.py
    backend/feature_extractor.py / advanced_feature_extractor.py
    backend/cache_manager.py      # In-process mesh cache (capacity 8, keyed by path+mtime)
config/config.py          # DevelopmentConfig / ProductionConfig / TestingConfig
              # DESIGN_DATA_DIR, SOLVER_DATA_DIR, TIER_LIMITS, SOLVER_* params
```

**Key backend patterns:**
- Each `app/cae/api/` and `app/step_view_pro/backend/api/` file exports a Flask `Blueprint` named `bp`.
- `cae_routes.py` has a per-process in-memory mesh cache (`_mesh_cache`, capacity 8) keyed by `(file_path, mtime)` to avoid re-parsing on every GET.
- STEP geometry is converted to GLB via `trimesh`; full pythonocc-core support requires `conda install -c conda-forge pythonocc-core=7.7.2` (not available via pip).
- LS-DYNA multi-file assemblies are uploaded as ZIP; the backend extracts them, identifies the master `.k`/`.key` file via `*INCLUDE` analysis, then parses normally.
- GMSH mesh generation is protected by a process-level `threading.Lock()` (`_gmsh_lock` in `step_mesher.py`) because GMSH is not thread-safe.

### Frontend (`frontend/src/`)

```
src/
  App.jsx              # Root: appMode (workspaceStore) design|results|geometry|step|cae|hub, drawers
  main.jsx
  components/
    DesignGraph/
      GraphEditor.jsx  # ReactFlow canvas with drag-drop nodes, connections (FASE 1)
      GraphProjectList.jsx  # Sidebar: list design graphs, create new
      NodePanel.jsx    # Right drawer: edit selected node properties
      EdgePanel.jsx    # Right drawer: edit selected edge properties
      EdgeTypeDialog.jsx  # Select semantic type when connecting nodes
      ConceptToolbar.jsx  # Draggable node type palette
      DesignNodeComponent.jsx  # Custom ReactFlow node renderer (color by type)
      DesignEdgeComponent.jsx  # Custom ReactFlow edge renderer
      ValidationOverlay.jsx  # Graph completeness errors + warnings
    Solver/
      SolverPanel.jsx  # FEM solver config + launcher; toggle: graph mode | cantilever test
      ConvergenceMonitor.jsx  # Recharts: residual log10 vs iteration
      FieldSelector.jsx  # Dropdown to choose result field (von Mises, displacement, etc)
    CAEViewer.jsx      # VTK.js-based FEA mesh viewer (field coloring, animation, section cut)
    StepViewer3D.jsx   # Three.js/R3F-based STEP GLB viewer (entity picking, PMI labels)
    CAEFileList.jsx    # Left sidebar for CAE mode
    FileList.jsx       # Left sidebar for STEP mode
    EntityTree.jsx     # STEP entity graph browser
    EntityDetails.jsx
    FeaturePanel.jsx   # Manufacturing feature list
    PMIPanel.jsx       # PMI annotations panel
    MeasurementTools.jsx
    SectionCutPanel.jsx
    MarkupPanel.jsx    # 2D SVG markup overlay
    MeshFromStepDialog.jsx  # Triggers STEP→FEA mesh generation
    ...
  stores/
    designStore.js     # Zustand: graph CRUD, node/edge ops, validation (FASE 1)
    solverStore.js     # Zustand: simulation runs, WebSocket streaming, results (FASE 2)
    viewerStore.js     # Zustand: CAE/STEP viewer state
  hooks/
    useModelLoader.js     # GLB model loading logic
    useSelection.js       # Entity selection state
    useUploadNotifications.js
  utils/raycasting.js     # Three.js raycasting for entity/point picking
  config/draco.js         # DRACOLoader path configuration (served from /draco/)
```

**Key frontend patterns:**
- `appMode`, the solver context panel (open + section), the history dialog and the study preflight live in
  `stores/workspaceStore.js` (FASE 9) so TopBar actions can drive other modes; the STEP-viewer panels are still
  local state in `App.jsx`. `caeMode` switches between `CAEViewer` (vtk.js) and `StepViewer3D` (Three.js/R3F).
- `CAEViewer.jsx` uses `@kitware/vtk.js` directly (not R3F) — requires `import '@kitware/vtk.js/Rendering/Profiles/Geometry'` as the first VTK import to register rendering classes.
- `StepViewer3D.jsx` uses `@react-three/fiber` + `three`. STEP files are served as Draco-compressed GLB from `/api/step-view/geometry/<header_id>/glb`. The Draco decoder WASM files live in `public/draco/` and `dist/draco/`.
- State management: mostly React `useState` in `App.jsx` + Zustand in `viewerStore.js` for viewer-specific state.
- API calls use `axios` with relative URLs (e.g., `/api/cae/meshes`).

### API Routes Summary

| Prefix | Module | Purpose |
|--------|--------|---------|
| `/api/jobs` | `app/jobs/api.py` | Job list/get/log/cancel/stats; POST only for `dummy` |
| `/api/catalog` | `app/catalog/api.py` | Hub tool catalog (`solver_catalog`) + filter facets |
| `/api/geometry` | `app/geometry/api.py` | Versioned STEP upload → `geometry.import` job (OCC worker); entities, versions, remap |
| `/api/auth` | `app/auth/api.py` | Login/logout/me, projects (`AUTH_REQUIRED` env gates `/api/*`, default off) |
| `/api/design/graph` | `graph_routes.py` | Design graph CRUD, validation, topological sort |
| `/api/design/validation` | `validation_routes.py` | Experiments, correlation, recalibration (FASE 8) |
| `/api/design/solver` | `solver_routes.py` | Launch FEM simulations (async), stream progress, results, `/surface`, `/preflight` |
| `/api/cae` | `cae_routes.py` | Mesh CRUD, field data, download |
| `/api/cae` | `ai_routes.py` | AI analysis |
| `/api/cae` | `mesh_from_step_routes.py` | STEP→mesh trigger |
| `/api/step-view` | `viewer_routes.py` | STEP file listing, GLB serving |
| `/api/step-view/upload` | `upload_routes.py` | STEP file upload + parsing |
| `/api/step-view/graph` | `graph_routes.py` | Entity graph |
| `/api/step-view/features` | `feature_routes.py` | Manufacturing features |
| `/api/step-view/pmi` | `pmi_routes.py` | PMI annotations |
| `/api/step-view/geometry` | `geometry_routes.py` | Geometry queries |
| `/api/step-view/analysis` | `analysis_routes.py` | Analysis tools |
| `/api/step-view/measurement` | `measurement_routes.py` | Measurement storage |
| `/api/step-view/export` | `export_routes.py` | Export |
| `/api/step-view/comparison` | `comparison_routes.py` | File comparison |
| `/api/step-view/performance` | `performance_routes.py` | Perf metrics |
| `/api/step-view/markup` | `markup_routes.py` | Markup/annotations |

## FEM Solver (FASE 2+)

**Mesh & Elements:**
- `FEMMesh(nodes, elements, node_sets, face_sets)`: element type inferred from columns (4 → T4, 10 → T10).
  Elements are canonicalized on construction (positive orientation; T10 mids in VTK order
  4:(0,1) 5:(1,2) 6:(0,2) 7:(0,3) 8:(1,3) 9:(2,3); Gmsh tet10 swaps 8/9 → `GMSH_TET10_TO_INTERNAL`).
  `face_sets` = boundary triangles (T4: 3 nodes, T10: 6) and also create matching `node_sets`.
- `tet_batch.py`: vectorized T4/T10 kernels (stiffness, volumes, Gauss-point strains, consistent
  surface/body loads, outward-normal orientation). T10 nodal stress = Gauss-point extrapolation (vertex
  Jacobians of curved elements may be negative, never evaluate there).
- `T4` locks in bending (−58 % at L/h=20). **T10 is the default** for CAD geometry.

**CAD meshing (`cad_mesh.py`):** `mesh_geometry(geometry_id, mesh_size_mm, order)` meshes the stored BREP
with Gmsh, maps Gmsh surfaces to persistent CAD faces through the H1a bridge (DB signatures, no pythonOCC),
converts mm → m and caches the result in `DATA_DIR/meshes/<geometry_id>/<key>.npz` (key includes Gmsh
version and `MESHER_VERSION`; bump it when options change). `NumThreads=1` (multithreaded Gmsh is not
deterministic). Curved T10 falls back to straight mids if any Jacobian ≤ 0. Mesh options per order in
`MESH_OPTS`. `estimate_size()` is only an estimate (observed −25 %…+140 %); exact size once cached.
Some parts (e.g. examples "tapa entredos", "Cuerpo") cannot be meshed: self-intersecting surface mesh.

**BC/LOAD on CAD faces:** BC/LOAD nodes store `entity_ids` (persistent face UUIDs from `geometry_entities`).
`app/geometry/resolve.py` resolves them to the study geometry version (following `parent_entity_id`);
`graph_to_solver_spec.py` turns them into `face_set` entries and raises `GraphSpecError` (→ 422) for
missing faces. Loads: `force` (total force spread by area; units N/kN/MN/lbf), `pressure` (normal,
positive pushes inward), `gravity` (uses material rho). Solid elements have translational DOFs only.

**Constitutive Models:**
- `LinearElasticIsotropic`: 6×6 D matrix; E, nu, rho. Fully implemented.
- `LinearElasticOrthotropic`, `Fourier`, `Thermoelastic`, etc.: Stubs with correct registry for FASE 2+.

**Assembly & Solving:**
- `assemble_K()`: batched, chunked COO→CSR. `assemble_F()`: face_set force/pressure, body force/gravity,
  node/node_set forces; records applied resultant.
- Linear solves eliminate Dirichlet DOFs (`dirichlet()` + `reduce_system()`); the penalty `apply_bcs()`
  is only used by Newton-Raphson. The kernel reports reactions and an equilibrium check.
- `solve_linear`: direct `spsolve` up to 6000 DOF, else PCG (AMG preconditioner with rigid-body
  near-nullspace via `pyamg`, in requirements; Jacobi fallback if missing). Jacobi does not converge in reasonable time
  on large/slender CAD models (shaft 75K DOF: AMG 155 it, 11 s). SciPy 1.11: `cg` uses `tol`, pass `atol=0`.
- Tier check before enqueue: `sizing.estimate_problem_size(spec)` → `413 TierLimitExceeded`
  (`POST /api/design/solver/<graph_id>/run`); the worker re-checks the exact size.
- `simulation_runs.hash` is not unique (migration `a7c9e2f4b6d1`): the same graph can be run again.

**Tier Limits** (non-negotiable):
```python
Tier 0: ≤30K DOF    Tier 1: ≤600K DOF    Tier 2: ≤6M DOF    Tier 3: ≤60M DOF
```
Exceeded limits raise `TierLimitExceeded` with suggestion for higher tier.

**WebSocket Streaming:**
- Backend: `flask-socketio` with `start_background_task()` for async solves.
- Frontend: `socket.io-client` in `solverStore.js`; emits `solver_progress`, `solver_done`, `solver_error` per-run room.

**Validation Hito (FASE 2):** Cantilever T10, L/h=20, n_div=20: −0.64 % vs Timoshenko (requirement ±1 %).
Run `python validate_fem.py` and `python -m pytest tests/test_fem_fase2.py` (patch tests, load resultants,
CG vs direct, hito, conforming bisection).

## Topology Optimization (FASE 4)

`app/design/services/topology/`: **SIMP** (`simp.py`) on linear tets — modified SIMP (ε = 1e-6),
volume-weighted density filter (`filter.py`, KD-tree, r = 2 × mean edge by default), Heaviside
projection with β continuation 1 → 16, OC update with bisection evaluated through filter+projection.
Ke⁰ of every element is stored once; each iteration rescales it into a fixed reduced (free-DOF) CSR
pattern with one `bincount`. Solves: direct ≤ 3000 DOF, else PCG with a seeded pyamg hierarchy reused
for a few iterations (warm start). Limit `MAX_ELEMENTS` = 150 000. T10 study meshes are reduced to T4.
- Elements touching BC/load sets are passive solid, except BCs flagged `symmetry` or `keep_solid: False`
  (`graph_to_solver_spec` sets them; plane/symmetry constraints must not freeze material).
- Not supported (clear 422): gravity/body loads, non-zero prescribed displacements. Level Set and AM
  constraints are still stubs (501 / disabled in UI).
- `isosurface.py`: marching tetrahedra on nodal density + clipped domain-boundary caps → watertight,
  outward-oriented surface (STL/GLB export, mm).
- Job `topology.simp` (queue `solve`, `runner.py`): files in `SOLVER_DATA_DIR/topology/<run_id>/`
  (`mesh.npz`, `latest.npz` snapshots, `result.npz`, cached `iso_*.npz`); socket events
  `topology_progress|snapshot|done|error` in room = run_id. Runs are `SimulationRun(purpose='topology')`
  with the settings under `spec['topology']` (hashed, reproducible bit for bit).
- API `/api/design/topology`: `POST /<graph_id>/run-simp` (settings from the body over the graph's
  OPTIMIZATION node, which is created/updated), `GET /<run>/state|densities|isosurface|domain`,
  `POST /<run>/extract-mesh` (STL + GEOMETRY node, edge OPTIMIZATION -PRODUCES-> GEOMETRY).
- Parametric `FEMMesh.generate_plate()` (mesh_source `plate`, optional hole) for the hito.
- UI: SolverPanel → "Topología" (`TopologyPanel.jsx`, `stores/topologyStore.js`, `DensityField.jsx`).
- Hito: `python validate_topology.py` — plate with pinned bottom supports and deck load gives the
  deck-arch bridge (volume, grayness, compliance, symmetry, connectivity checks). ~100 s.

## Reduced-Order Models (FASE 5)

`app/design/services/rom/`: **POD-Galerkin** with an exact affine decomposition. Isotropic
D = λ·m mᵀ + μ·diag(2,2,2,1,1,1) (engineering shear) → K = λK_λ + μK_μ; F = Σ (pᵢ/pᵢ⁰)·Fᵢ, gravity loads
also scaled by ρ/ρ₀. Parameters: `E`, `nu`, `load_<i>`, `rho` (only with gravity) — `describe_parameters(spec)`.
- `pod.py`: `PODROMBuilder` — LHS snapshots (normalized) → SVD, energy threshold 1−1e-12 (lower thresholds
  keep too few modes: 0.999999 gave 1 mode / 0.5 % error) → projected r×r operators, element-centroid strain
  modes, surface displacement/strain modes (float32) for the browser; validation vs full solves at fresh LHS points.
- `online_solver.py`: process-wide LRU (4 ROMs); `evaluate()` = r×r solve + whole-volume max u/σvM (<1 ms).
  The `residual` is a force-norm indicator (~1e-2), not an error: the UI shows the validation error.
- `runner.py`: job `rom.build` (queue `solve`) → `SOLVER_DATA_DIR/rom/<run_id>/rom.npz`; runs are
  `SimulationRun(purpose='rom')` with settings under `spec['rom']` (hashed); socket `rom_build_progress|done|error`.
- API `/api/design/rom`: `GET /<graph_id>/parameters`, `POST /<graph_id>/build`, `GET /<graph_id>/list`,
  `GET /<rom_id>`, `GET /<rom_id>/pack` (binary surface pack: uint32 header len + JSON + pad + xyz mm/tris/phi/strain),
  `POST /<rom_id>/evaluate`, `POST /<rom_id>/full-run` + `GET /<rom_id>/compare/<run_id>` (ROM vs full solve).
  Socket `rom_evaluate` (ack) is what the explorer uses; the client coalesces requests while one is in flight.
- UI: SolverPanel → "ROM" (`ROMPanel.jsx`, `ROMExplorer.jsx`, `stores/romStore.js`, `utils/romPack.js`
  rebuilds the surface field from the reduced coefficients in the browser).
- Hito: `python validate_rom.py [--server http://127.0.0.1:8080 --rom-id <id>]` (use 127.0.0.1 on Windows:
  `localhost` adds ~2 s per request via IPv6 fallback). Measured: cantilever error 1e-7, eval+field p95 <1 ms;
  CAD shaft 56K DOF: 3 modes, build 210 s, socket round-trip p95 30 ms, full run 22 s vs ROM 3 ms.

## Active Materials and Uncertainty (FASE 6)

`app/design/services/material/`:
- `calibrator.py`: `least_squares_fit` (scipy TRF, bounds, optional weights) → params, std from Σ = s²(JᵀJ)⁻¹
  computed in **column-scaled** variables (unscaled pinv truncated directions: E ~1e5 MPa vs ε0 ~1e-4), R², RMSE,
  AICc; `prediction_band` (delta method); `MaterialCalibrator` object interface.
- `parametric.py`: tensile σ-ε models `linear`, `bilinear`, `ramberg_osgood`, `ludwik`, `voce`, `polynomial_3`
  (internal MPa; implicit laws inverted by vectorized bisection). Every model is fitted as σ = f(ε − ε0) with the
  **toe offset ε0 as a parameter** (pre-shifting the data biased E by up to 27 % on gradual-yield curves), residuals
  weighted by normalized arc length, data truncated at UTS. Best model by AICc. Several specimens → mean ± std
  across specimens; one → fit standard error. `parse_curve_csv`: delimiter/decimal comma, %, Pa/MPa/GPa/psi/ksi,
  force-displacement (needs area + gauge length); header keys match at word start (`tensi` ≠ `extension`).
- `uncertainty.py`: Monte Carlo with truncated normals (inverse CDF, one RNG per variable → prefix-stable samples).
  `ROMEvaluator` (batched: σvM² = μ² uᵣᵀQuᵣ with per-element Q precomputed → one GEMM per block; 2000 samples on a
  56K-DOF ROM ≈ 2.5 s) — only for variables varied in the ROM training (E always exact); `FullEvaluator`
  (affine full solves). Outputs: stats/histograms of max σvM and |u|, Pf with Wilson interval, β (Cornell and
  −Φ⁻¹(Pf)), Spearman sensitivities, convergence, surface mean/std/upper-quantile fields.
- `runner.py`: job `uncertainty.mc` (queue `solve`), `SimulationRun(purpose='uncertainty')`, setup under
  `spec['uncertainty']` (`rom_id`/`material_id` are label keys; `rom_hash` is hashed); files in
  `SOLVER_DATA_DIR/uncertainty/<run_id>/result.npz`; socket `uncertainty_progress|done|error`.
  Sample caps: full solves 100/100/500/2000 by tier, ROM 2000 (413 above).
- API `/api/design/material`: library CRUD (`material_models`, soft delete), `POST /fit-curves`, `POST /<id>/fit`
  (multipart CSV `files`, optional `model`), `/<id>/predict`, `/<id>/assign` (MATERIAL node gets E, ν, ρ, σy and
  `*_std`, `yield_strength/yield_std`, `material_id`), `GET /uncertainty/<graph_id>/setup|list`,
  `POST /uncertainty/<graph_id>/run`, `/<id>/propagate-uncertainty`, `GET /uncertainty/run/<id>[/surface]`.
  The FEM kernel stays linear elastic: the fitted plastic law supplies σy for the failure criterion.
- UI: NodePanel MATERIAL → "Biblioteca y ajuste de ensayo…" (`components/Material/MaterialEditor.jsx`,
  `stores/materialStore.js`); SolverPanel → "Incertidumbre" (`UncertaintyPanel.jsx`, `UncertaintyBand.jsx`,
  `stores/uncertaintyStore.js`). `services/binpack.py` is the shared binary pack (ROM + uncertainty surfaces).
- Hito: `python validate_material.py` — synthetic CSV tensile curves (4 materials/formats, noise, toe, necking):
  elastoplastic model, R² > 0.99, σ0.2 within 3 %, E within 5 % (AISI 304 gradual yield: E −4.4 %, only 10 elastic
  points); MC Pf vs analytic normal reliability, ROM vs full solves.

## Traceability (FASE 7)

`app/design/services/traceability/hasher.py`: the run hash = SHA-256 of **canonical physical inputs**
(spec without graph/node ids, labels, tier; numbers as floats; defaults made explicit; bcs/loads sorted;
CAD geometry replaced by the STEP file sha256, inline meshes by their bytes) + **numerical environment**
(`FEM_KERNEL_VERSION`, `MESHER_VERSION`, numpy, scipy, pyamg, gmsh, Python major.minor). Same parameters →
same hash, even across graphs (hito). Provenance (host, git commit, platform) is stored, not hashed.
**Bump `FEM_KERNEL_VERSION`** whenever a code change alters numerical results for the same inputs.

- `simulation_runs` (migration `b3d5f7a9c2e4`): `purpose` (run|reproduce|adaptive), `inputs`, `environment`,
  `provenance`, `summary`, `mesh_hash` (exact bytes of nodes+elements), `result_hash` (exact bytes of u).
  Lineage: a run's `parent_run_id` is the previous finished run of the graph and `parameter_delta` lists
  changed inputs (`material.E: [old, new]`); a reproduction's parent is the reproduced run.
- The worker re-fingerprints at solve start (its environment is what counts).
- Solves are bitwise deterministic: Gmsh `NumThreads=1`, and the pyamg setup is seeded (it uses random
  vectors) while restoring the global RNG. Keep it that way: `tests/test_traceability.py` checks it.
- API (`/api/design/solver`): `GET /runs?graph_id=`, `GET /<run>/report?format=markdown|jsonld[&download=1]`
  (`reporter.py`, schema.org/Dataset), `POST /<run>/reproduce` (409 `EnvironmentMismatch` unless
  `{"force": true}`), `GET /<run>/reproducibility[?against=]`, `GET /environment`.
- UI: History button in `SolverPanel` → `components/Solver/SimHistory.jsx` (hash colours, deltas,
  report, reproduce dialog with environment check; test `SimHistory.test.jsx`).

## Unified Workspace (FASE 9)

The study (DesignGraph) is the context of the whole UI; tools are modes around it.
- `TopBar.jsx`: 1) mode chips Design | Resultados | Geometría | STEP | CAE/FEA | Catálogo; 2) project context
  (name · version · status · ✓ listo / ⚠ n · tier needed vs declared); 3) actions Validar · Simular (validates, opens
  the solver panel, launches the run; an incomplete graph shows the validation instead) · Historial · Exportar
  (Markdown / JSON-LD report of the latest run, graph JSON-LD).
- `GET /api/design/solver/<graph_id>/preflight`: completeness issues, physics, size estimate + smallest tier that
  fits vs declared, confidence factor (FASE 8 correlator), latest run. Shown by `Workspace/GraphStatusStrip.jsx`
  (plan §9.4, bottom-left of the graph editor, refreshed debounced on graph content changes) and the TopBar.
- Results mode: `Results/ResultsRunList.jsx` (runs `run|reproduce|adaptive` of the study; opens the newest done) +
  `Results/ResultsViewer.jsx` (Three.js; σvM, |u|, ux/uy/uz with symmetric range for components, deformed shape:
  auto = max |u| drawn as 8 % of the model, never < 1×, 1:1 button). Data: `GET /api/design/solver/<run>/surface`
  (binpack: xyz mm, tris, u mm, vm MPa over compacted surface nodes). "Ver resultados 3D" in the solver panel.
- GEOMETRY node `shape: 'beam'` (`length_mm`, `width_mm`, `height_mm`, `n_div`, `element_order` default 2 = T10):
  parametric beam defined in the graph (faces `fixed` x = 0, `tip` x = L). Without `shape`, no geometry_id and no
  mesh_id the legacy default (50×10×10 mm T4 cantilever) is kept.
- `DELETE /api/design/graph/<id>`: 409 when the study has runs or experiments; `?cascade=1` deletes runs (+ h5 and
  topology/rom/uncertainty dirs), field results, correlations, experiments (+ files), physics configs; library
  materials are kept (graph_id cleared), jobs keep their log. The project list asks before both steps.
- Not done from the plan: graph version tree in the left panel (no versioning API), a single designStore (§9.3:
  kept as designStore + solverStore + workspaceStore on purpose).
- Hito: `python validate_workflow.py [--server http://127.0.0.1:8080] [--keep]` (server + worker): concept →
  graph (beam 500×25×25 T10, steel, fixed, 1 kN) → preflight → run on the job queue → run list + surface pack
  (tip deflection −0.64 % vs Timoshenko, closed surface) → SPA bundle; deletes its study. ~3 s.
  Tests: `components/Workspace/Workspace.test.jsx`.

## Continuous Validation (FASE 8)

`app/design/services/validation/` + API `/api/design/validation` (`validation_routes.py`). Experiments live in
`experimental_records` (`test_type` `tensile` | `structural`, `conditions`, downsampled `raw_data`, `scalar_summary`;
the uploaded file under `DATA_DIR/experiments/<id>/`, relative `file_ref`); comparisons in
`sim_experiment_correlations` (migration `c8e4a6b2d9f1`: `run_id` nullable, `kind` material|structural, `graph_id`,
`material_id`, `details` JSONB with per-sensor values / curves).
- `sensors.py`: `parse_sensor_csv` (label, x, y, z [mm, CAD frame], quantity ux|uy|uz|umag|strain, value [mm | µε],
  optional std, dx/dy/dz gauge direction; Spanish headers, `;` + decimal comma, `[m]` and `mm/mm` scaled).
  `MeshProbe` locates sensors in the run mesh (KD-tree on centroids + barycentric test; outside points projected,
  distance is an upper bound, flagged when > ½ mean edge) and interpolates u / strain with the T4/T10 shape functions.
  The run's field is scaled by `conditions.load_factor` (test load / model load).
- `correlator.py`: `correlation_metrics` (R² about the identity line; about zero when n < 3 or the readings barely
  spread (CV < 10 %), else a uniform offset gives R² ≪ 0; max relative error with a 5 %-of-max floor; slope
  measured/simulated; confidence = max(R²,0)·e^(−maxerr/0.25)·(1−e^(−n/3))). **Mixed quantities (mm and µε) are
  normalized per quantity group** (`group_scales`) before pooling. `SimulationCorrelator`: study signatures
  (geometry identity, material, BCs/loads, mesh size) → similarity of past structural correlations (one per
  (experiment, run)) → confidence before simulating C = (Σsᵢcᵢ/Σsᵢ)(1−e^(−Σsᵢ)); recommends a tensile test if the
  material is uncalibrated and sensor positions (max |u|, max σvM surface nodes of the latest run).
  "Semantic embedding" of the plan is replaced by this parameter similarity.
- `recalibrator.py`: tensile → refit (FASE 6 machinery), before/after metrics vs the material's current model,
  `replace` or `bayes` (inverse variance; prior without std gets 5 % CV), δ per parameter, appended to
  `material.calibration.history`, linked MATERIAL nodes synced. Structural → only the stiffness scale is
  identifiable from one load case: E* = E_run / k (exact, u ∝ 1/E), an *effective* E written to the graph's MATERIAL
  node (`E_source`); a poor fit after the correction (R² < 0.9 or error > 15 %) warns that BCs/loads are wrong.
  E_run is the E of the run compared against (latest done `run|reproduce`, or `run_id`), not the node's.
- API: `GET /status`, `POST /experiments/preview|/experiments` (multipart; `calibrate=1` recalibrates tensile /
  correlates structural), `GET|DELETE /experiments[/<id>]`, `POST /<graph_id>/correlate`, `GET /<graph_id>/correlations`,
  `GET /correlations/<id>`, `GET /<graph_id>/confidence`, `POST /<graph_id>/recalibrate` (`apply: false` = preview).
- UI: SolverPanel → "Validación" (`components/Validation/ValidationPanel.jsx`, `ExperimentUpload.jsx`,
  `CorrelationView.jsx`, `stores/validationStore.js`; test `ValidationPanel.test.jsx`).
- Hito: `python validate_validation.py` (synthetic data with known truth): tensile recalibration E error 0.14 %
  (replace) / 0.22 % (bayes, 3 specimens, std shrinking); structural E* within 1.2 % with 1 % sensor noise; a
  flexible-clamp control case is flagged instead of calibrating a false E. Tests: `tests/test_validation.py`.

## Adaptive Meshing (FASE 3)

**Strategy:** Longest-edge bisection h-refinement with Zienkiewicz-Zhu stress recovery error estimation.

**Backend modules:**
- `error_estimator.py`: Zienkiewicz-Zhu L2 projection recovery + energy-norm element error indicators
  * `compute_error_indicators(nodes, elements, stress_elemental, E, nu)` → per-element error
  * `mark_elements_for_refinement()` → fraction or absolute threshold marking
- `mesh_adaptivity.py`: Refinement and coarsening operators
  * `refine_marked_elements_bisection()` → split marked elements along longest edge
  * `coarsen_mesh()` → random node removal (stub for FASE 3+)
- `kernel.py` addition:
  * `solve_adaptive_sync(spec, max_cycles=5, target_error=0.05, refinement_fraction=0.2)` → iterative solve loop

**Frontend:**
- `AdaptiveMonitor.jsx`: Visualizes error reduction and mesh growth across cycles
  * Error vs cycle chart (log scale, 5% target line)
  * Node/element growth chart
  * Detailed cycle table with global error, displacements, stresses

**API:**
- `POST /<graph_id>/run-adaptive` → synchronous adaptive solve, returns `adaptive_log` array

**Validation (FASE 3), measured:** adaptive runs use T4 (bisection is T4-only). `validate_adaptive.py`
gives ZZ error 21.9 % → 18.3 % over 5 cycles; the old "<5 % at cycle 3" claim does not reproduce.
Refinement is conforming (recursive longest-edge bisection); node/face sets are carried to new meshes.

### Supported CAE Mesh Formats

`.vtu`, `.vtk`, `.pvtu` (VTK/ParaView), `.inp` (Abaqus), `.bdf`/`.nas`/`.dat` (Nastran/ANSYS), `.msh` (GMSH), `.med` (Salome MED), `.exo`/`.e` (Exodus II), `.cdb` (ANSYS CDB), `.xdmf`/`.xmf` (XDMF), `.k`/`.key` (LS-DYNA single), `.zip` (LS-DYNA multi-file assembly).

LS-DYNA and Abaqus `.inp` are parsed with native Python parsers; all others go through `meshio`.
