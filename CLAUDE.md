# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CAE Viewer is a full-stack engineering platform with three integrated modes:

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
  App.jsx              # Root: three-mode (appMode: design|step|cae), all state, drawers
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
- `App.jsx` manages all panel open/closed state centrally and passes callbacks down. `caeMode` switches between `CAEViewer` (vtk.js) and `StepViewer3D` (Three.js/R3F).
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
| `/api/design/solver` | `solver_routes.py` | Launch FEM simulations (async), stream progress, get results |
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
- `FEMMesh`: Unified container for nodes + elements + node_sets. Supports inline arrays, GMSH-generated cantilever, CAE mesh imports.
- `T4` (linear tet): 4 nodes, 12 DOFs; complete B-matrix, stiffness, von Mises implementation. **Note:** shear locking in bending; convergence slow but monotone.
- `T10` (quadratic tet): Stub, FASE 2 extension for ±1% accuracy on bending without over-refinement.

**Constitutive Models:**
- `LinearElasticIsotropic`: 6×6 D matrix; E, nu, rho. Fully implemented.
- `LinearElasticOrthotropic`, `Fourier`, `Thermoelastic`, etc.: Stubs with correct registry for FASE 2+.

**Assembly & Solving:**
- `assemble_K()`: COO→CSR sparse stiffness, handles multi-element contributions.
- `assemble_F()`: Distributed loads via node_sets; single-node forces.
- `apply_bcs()`: Dirichlet BCs via penalty method (K_diag = 1e30, F = value × 1e30).
- `FEMSolverDispatcher`: Routes to **direct spsolve** (Tier 0-1) or **CG-ILU** (Tier 2-3).

**Tier Limits** (non-negotiable):
```python
Tier 0: ≤30K DOF    Tier 1: ≤600K DOF    Tier 2: ≤6M DOF    Tier 3: ≤60M DOF
```
Exceeded limits raise `TierLimitExceeded` with suggestion for higher tier.

**WebSocket Streaming:**
- Backend: `flask-socketio` with `start_background_task()` for async solves.
- Frontend: `socket.io-client` in `solverStore.js`; emits `solver_progress`, `solver_done`, `solver_error` per-run room.

**Validation Hito (FASE 2):** Cantilever beam T4 mesh, n_div=35 (2225 nodes, 8938 elements): error <4% (analytical vs FEM). Run via `python validate_fem.py`.

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

**Validation Hito (FASE 3):** Cantilever T4, n_div=5 initial:
- Cycle 0: ~46 nodes, error ~40%
- Cycle 1: ~150 nodes, error ~25%
- Cycle 2: ~400 nodes, error ~12%
- Cycle 3: ~900 nodes, error <5% ✓

### Supported CAE Mesh Formats

`.vtu`, `.vtk`, `.pvtu` (VTK/ParaView), `.inp` (Abaqus), `.bdf`/`.nas`/`.dat` (Nastran/ANSYS), `.msh` (GMSH), `.med` (Salome MED), `.exo`/`.e` (Exodus II), `.cdb` (ANSYS CDB), `.xdmf`/`.xmf` (XDMF), `.k`/`.key` (LS-DYNA single), `.zip` (LS-DYNA multi-file assembly).

LS-DYNA and Abaqus `.inp` are parsed with native Python parsers; all others go through `meshio`.
