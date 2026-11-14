# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CAE Viewer is a full-stack engineering platform with three integrated modes:

- **Results mode** (FASE 9): 3D field viewer of the active study's finished runs (Design → Simular → Resultados).
- **Design mode** (FASE 1-3): Engineering concept graph editor + FEM solver. Build design graphs (GEOMETRY, MATERIAL, BC, LOAD, RESULT nodes), run structural simulations with adaptive meshing, stream solver progress via WebSocket.
- **STEP mode**: Upload/view STEP files (.stp/.step/.p21), measure, section-cut, markup and export. There is
  **no STEP entity graph** (entity tree, manufacturing features, PMI, analysis): the Part 21 → relational storage
  lives in CAPP and was never ported; its UI, blueprints, parsers and extractors were deleted on 2026-11-14 (not
  needed for simulation — CAD faces come from `app/geometry`). The `step_entities`/`step_entity_edges`/… tables and
  models stay (schema unchanged). Files found in the upload folder without a Part row are registered when listed
  (`register_step_file`).
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

**Material catalog:** `app/design/services/material/seed_data.py` = 40 typical-value materials (steels, stainless,
cast irons, Al, Ti, Ni, Cu, Mg, polymers, elastomers, concrete, glass, alumina; mechanical E ν ρ σy σu σc elongation +
thermal k α cp, SI, ± std from a CV per category, `source_ref` per entry). `flask materials seed [--prune]` upserts by
`seed_key` (idempotent; run after `flask db upgrade`). `material_models` columns `category`, `source`
(seed|user|test|import|capp), `source_ref`, `seed_key` (migration `a1f3c5e7b9d2`). **Catalog rows are read-only**
(`is_locked`: PUT / DELETE / fit / tensile recalibration → 409); `POST /api/design/material/<id>/duplicate` makes an
editable user copy (UI "Duplicar para editar"). A fit sets `source = 'test'`. Assigning to a MATERIAL node also
copies k and α (used only by thermal studies; hashes unchanged) and drops a stale σy for brittle materials.

**Docker:** `docker/geometry.Dockerfile` (micromamba + pythonocc-core 7.7.2 + Gmsh wheel) is the
image for workers and geometry tools; `docker compose` runs `worker-solve` and `worker-geometry`.
From Git Bash, prefix `docker run -e VAR=/path` with `MSYS_NO_PATHCONV=1`.

The Flask app serves the built SPA from `frontend/dist/` at `/step-view/`. In development, the Vite dev server proxies API calls to Flask on port 8080.

**Database**: PostgreSQL. Default URI: `postgresql://postgres:postgres@localhost:5432/caedb`. **Alembic is the only schema mechanism** — run `flask db upgrade` (startup only warns if the DB is behind head).
`flask db upgrade` builds an empty database (root `9f0e1d2c3b4a` creates the pre-Alembic tables; `downgrade base`
works too). `tests/test_migrations.py` checks upgrade head = models (no autogenerate diff) on a scratch DB: declare
every index/constraint a migration adds in the model too. `.env.local` overrides `DATABASE_URL`/`FLASK_ENV`, so
`DATABASE_URL=… flask db …` from the shell still targets `caedb`. SQLAlchemy is pinned `<2.1` (2.1 defaults `postgresql://` to psycopg 3).

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
    __init__.py           # register_step_view_blueprints() — 8 blueprints at /api/step-view/*
    backend/api/          # viewer, upload, files, geometry, measurement, export, comparison,
                          # performance, markup routes
    backend/step_processor.py     # STEP parsing pipeline
    backend/geometry_processor.py # Geometry extraction → GLB via trimesh
    backend/step_to_glb_converter.py
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
  App.jsx              # Root: appMode (designStore) design|results|geometry|step|cae|hub, drawers
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
    CAEViewer.jsx      # VTK.js-based FEA mesh viewer (field coloring, animation, section cut)
    StepViewer3D.jsx   # Three.js/R3F-based STEP GLB viewer (measurement picking, section cut, markup)
    CAEFileList.jsx    # Left sidebar for CAE mode
    FileList.jsx       # Left sidebar for STEP mode
    MeasurementTools.jsx
    SectionCutPanel.jsx
    MarkupPanel.jsx    # 2D SVG markup overlay
    MeshFromStepDialog.jsx  # Triggers STEP→FEA mesh generation
    ...
  stores/
    designStore.js     # Zustand: THE study store (plan §9.3) = graph slice (CRUD, selection, validation)
    design/runSlice.js        # + run slice: simulation launch, WebSocket streaming (ex solverStore)
    design/workspaceSlice.js  # + workspace slice: appMode, solver panel, history, preflight (ex workspaceStore)
  utils/               # colormap, romPack (ROM surface pack decoder)
```

**Key frontend patterns:**
- **Single study store** (`stores/designStore.js`, plan §9.3): graph + run + workspace slices in one Zustand store.
  `appMode`, the solver context panel, the history dialog and the preflight live there so TopBar actions can drive
  other modes. Opening another study (`loadGraph` with a different id, deleting the active one) calls `_leaveStudy`:
  run state reset, socket listeners off + `leave_run`, preflight/history cleared; socket handlers also check
  `activeRunId`, so a late event of an old run never lands. The graph's `error`/`clearError` and the run's
  `runError`/`clearRunError` are separate. **Subscribe with selectors**: `useDesignStore(s => s.x)` or
  `useStudy('a', 'b')` (shallow) — never `useDesignStore()` whole, run progress would re-render the graph editor.
  Tool stores (topology, ROM, uncertainty, validation, results, material, geometry, hub, jobs) stay separate.
  The STEP-viewer panels are still local state in `App.jsx`. `caeMode` switches between `CAEViewer` (vtk.js) and `StepViewer3D` (Three.js/R3F).
- `CAEViewer.jsx` uses `@kitware/vtk.js` directly (not R3F) — requires `import '@kitware/vtk.js/Rendering/Profiles/Geometry'` as the first VTK import to register rendering classes.
- `StepViewer3D.jsx` uses `@react-three/fiber` + `three`. STEP files are served as Draco-compressed GLB from `/api/step-view/geometry/<header_id>/glb`. The Draco decoder WASM files live in `public/draco/` and `dist/draco/`.
- State management: Zustand stores (`designStore` = the study, per-tool stores) + local `useState`
  in `App.jsx` for the STEP-viewer panels. Draco decoder path is set in `StepViewer3D.jsx` (`/step-view/draco/`).
- Lint: ESLint 9 flat config `frontend/eslint.config.js` (R3F props are allow-listed in `react/no-unknown-property`).
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
| `/api/step-view/geometry` | `geometry_routes.py` | Geometry queries |
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
- `LinearElasticIsotropic`: 6×6 D matrix; E, nu, rho. Fully implemented. `Thermoelastic` = isotropic + α, T_ref
  (the kernel's one-way coupling uses them).
- `LinearElasticOrthotropic`: E1..E3, G12/G13/G23 [Pa], ν12/ν13/ν23 (νij = −εj/εi, tension along i) along the
  material axes `axis_1`/`axis_2` (global/CAD frame; axis 2 re-orthogonalised, 3 = 1 × 2; default global axes).
  Compliance → D in the material axes → `rotate_D` (Tᵀ D T, engineering-shear Voigt xx yy zz xy yz xz);
  non-positive-definite constants raise. Thermal: material `k` and `alpha` may be lists [v1, v2, v3] along the
  material axes → `conductivity(mat)` (3×3 tensor, `FourierOrthotropic`) / `thermal_expansion(mat)` (Voigt
  6-vector); scalars keep the isotropic code path (hashes unchanged). Graph: MATERIAL `model_type:
  'linear_elastic_orthotropic'` + those keys, `axis_1`/`axis_2` [x,y,z], optional `k1..k3`, `alpha1..3`
  (`graph_to_solver_spec._orthotropic_material`); UI `DesignGraph/OrthotropicFields.jsx`. Adaptive and topology
  use D as is; ROM and uncertainty parametrise E/ν → 422 (`prepare_spec(isotropic_only=True)`); structural
  recalibration (effective E) → 422. Hito `python validate_orthotropic.py [--server …]`: isotropic equivalence,
  off-axis tension exact (Ex(θ), γxy coupling), CFRP cantilever L/h = 40 −0.09 % / −0.21 % vs Timoshenko
  (fibres along / across), rotated conduction patch and free expansion exact. Tests `tests/test_orthotropic.py`.
- `HyperelasticNeoHookean` (`fem/hyperelastic.py`): compressible Neo-Hookean W = μ/2(I₁−3) − μ ln J + λ/2(ln J)²,
  μ/λ from the small-strain E, ν; total Lagrangian (B_NL = sym(Fᵀ∇₀N), material + geometric tangent, checked
  against finite differences), Newton with load steps (`n_load_steps`, node `load_steps`), tangent predictor for
  prescribed displacements, cut-backs (a trial J ≤ 0 is a failed iteration). **Dead loads** (pressure keeps the
  reference normal/area). Thermal coupling → ValueError. Summary `hyperelastic` {min_J, max_green_strain,
  load_factor, curve}; nodal σvM from the Cauchy stress. Hito `python validate_hyperelastic.py [--server …]`:
  uniaxial ±50 %/−30 % and simple shear exact, small-load = linear, large-deflection cantilever α = PL²/EI = 2
  vs Euler elastica +0.03 % (deflection) / +0.02 % (shortening), Newton order ≈ 2. Tests `tests/test_hyperelastic.py`.
- `ViscoelasticMaxwell` (`fem/viscoelastic.py`): generalized Maxwell, E(t) = E₀[g∞ + Σgᵢe^{−t/τᵢ}] with ν
  constant (the whole D relaxes), small strain, quasi-static. Exact recursion of the internal stresses for
  strain linear in the step → each step is (c K₀)Δu = …: K₀ factorised once (splu ≤ 60K free DOF, else AMG-PCG
  per step). Spec: material `prony` [{g, tau}] (Σg < 1), top-level `time` {t_end, n_steps, history [[t, λ]…]}
  (a repeated time = jump, solved instantaneously); graph node `prony_terms`, `t_end`, `time_steps`,
  `load_history` creep|ramp (`t_ramp`)|recovery (`t_unload`). Results = final time; summary `viscoelastic`
  {E0, E_inf, curve (t, λ, max |u|, reactions), creep_ratio}. Hito `python validate_viscoelastic.py [--server …]`:
  relaxation exact (1e-15), SLS creep O(Δt²) (rates 2.00), creep + recovery, cantilever = u_el·E₀J(t) (0.005 %).
  Tests `tests/test_viscoelastic.py`.
- Non-linear / history models (`NONLINEAR_MATERIALS` in solver_routes: J2, Neo-Hookean, Maxwell) run only through
  the plain kernel run: topology / ROM / uncertainty / adaptive get 422. Preflight labels in `MATERIAL_LABELS`.
  UI: `HyperelasticFields.jsx`, `ViscoelasticFields.jsx`; test `MaterialModelFields.test.jsx`.
- `Piezoelectric` (`fem/piezo.py`): linear, stress-charge form σ = cᴱε − eᵀE, D = eε + εˢE, hexagonal 6mm class
  (keys c11 c12 c13 c33 c44 c66 [Pa], e31 e33 e15 [C/m²], eps11 eps33 relative at constant strain; poling = material
  axis 3, optional `axis_1`/`axis_2` like orthotropic: e_g = Rᵀe_mT, κ_g = Rᵀκ_mR). Coupled u + φ (4 DOF/node), one
  symmetric indefinite system [[Kuu, Kuφ], [Kuφᵀ, −Kφφ]] solved directly with symmetric diagonal scaling (without it
  the residual stalls at ~1e-6; `PIEZO_MAX_DOF` 400K). Spec: `physics ['piezoelectric']`, BC `{'voltage': V,
  face_set}` (electrode; the face's φ is fixed), load `{'surface_charge': C/m², face_set}`; electrode charge =
  −reaction of the φ equations. Graph: MATERIAL `model_type: 'piezoelectric'`, BC `bc_type: 'voltage'` (default face
  z0), LOAD `load_type: 'surface_charge'` (C/m², mC/m², µC/m²; default z1); thermal + piezo → 422, electrodes without
  a piezo material → 422. `generate_cantilever` also tags the side faces `y0 y1 z0 z1`. Summary `piezo`
  {electrodes [{voltage_V, charge_C}], min/max potential, max_field_V_m, d_pC_N}. UI `DesignGraph/PiezoFields.jsx`
  (PZT-5H preset). Hito `python validate_piezo.py [--server …]`: datasheet d31/d33/d15/ε33ᵀ within 0.5 %, converse
  effect + free capacitance, open-circuit sensor voltage, d15 shear, blocked stress, poling along x — all exact
  (1e-13); server: graph → run → φ field → |u| exact. Tests `tests/test_piezo.py`.
- **Generic extra result fields** (newer physics): the kernel result may carry `extra_fields {key: nodal array}`
  + summary `extra_fields [{key, label, unit}]` → HDF5 `fields/x_<key>/step_0` → `/surface` packs `x_<key>` with
  header `extra_fields` (min/max) → Results viewer lists them (`resultsField.availableFields/fieldMeta`).
- Mechanical BC nodes honour `face_set` on parametric meshes (before, only `node_set` was read, default `fixed`).
- `NewtonianFluid` (`fem/stokes.py`): steady incompressible **Stokes** flow (creeping, inertia neglected),
  Taylor-Hood P2-P1 (velocity on all T10 nodes, pressure on corners; T4 → ValueError), Laplacian form μ∫∇w:∇v, so
  a face without velocity BCs is a "do nothing" outlet (μ∂v/∂n − p n = 0, i.e. p = 0) or carries a `pressure` load
  (inlet pressure, positive pushes into the fluid). Velocity BCs reuse `dofs`/`values` (no-slip = fixed, slip =
  roller, inlet = values [m/s]); `gravity` uses ρ. Saddle system solved directly (μ-normalised, `FLUID_MAX_DOF` 400K);
  if every boundary node has its normal velocity prescribed the first corner pressure is pinned to 0
  (`stokes.is_enclosed`). Summary `fluid` {mu, rho, max_velocity_m_s, min/max pressure, flow_rates per referenced
  face set (outward ∫v·n dA), mass_balance_error, reynolds (ρ·vmax·smallest bbox extent/μ; `warnings` when > 1),
  wall_force_N, max_shear_rate_1_s}; extra fields vmag/vx/vy/vz [mm/s] and p [Pa]; no displacement field.
  Graph: MATERIAL `model_type: 'newtonian_fluid'` + `mu` (rho default 1000), BC `bc_type: 'velocity'` (vx, vy, vz,
  `unit` m/s|mm/s), pressure LOAD on the parametric beam via `face_set`; thermal / electrodes → 422. Topology / ROM /
  uncertainty / adaptive → 422. UI `DesignGraph/FluidFields.jsx` (presets). Hito `python validate_fluid.py
  [--server …]`: plane Poiseuille (profile, Q, linear p, wall force Δp·A), Couette (wall shear μU/H·A) and
  hydrostatics in a closed box exact (1e-10); square duct vs Fourier series −0.125 % at h = a/3, order 3.9; mass
  balance 1e-12. Tests `tests/test_fluid.py`. Not Navier-Stokes: no convection term, no turbulence, steady only.
- `LinearMagnetic` (`fem/magnetic.py`): linear **magnetostatics in current-free regions** with the total scalar
  potential ψ [A]: H = −∇ψ, B = μ₀μr H + Br, ∇·B = 0 → the conduction operators of `thermal` (scaled by 1/μ₀) with
  the magnet source ∫∇w·Br/μ₀. One material region (scalar μr, uniform remanence Br [T] in global axes), no coils /
  currents, no saturation. BC `{'magnetic_potential': ψ, face_set}` = equipotential pole face against ideal iron
  (B normal); the ψ difference between two faces is the MMF (a coil's N·I enters as the jump across a cut, e.g. the
  toroid hito); load `{'magnetic_flux': Bn [T], face_set}` (positive enters); free faces are flux walls (Bn = 0).
  No potential BC → node 0 pinned (imposed fluxes must balance, else ValueError). Mechanical/thermal conditions →
  error. Summary `magnetic` {mu_r, Br_T, max_B_T, max_H_A_m, min/max potential, poles [{potential_A, flux_in_Wb}]
  (flux = reaction ×μ₀), flux_loads, field_energy_J = ½∫μ|H|², and with two potential levels, no magnet and no
  flux load: mmf_A, flux_Wb, permeance_H (= inductance for 1 turn), reluctance}; extra fields Bmag/Bx/By/Bz [T],
  Hmag [kA/m], psi [A]. Graph: MATERIAL `model_type: 'linear_magnetic'` + `mu_r`, `Br_x/Br_y/Br_z`; BC `bc_type:
  'magnetic_potential'` (default face `fixed`), LOAD `load_type: 'magnetic_flux'` (T | mT, default `tip`); magnetic
  conditions without the material → 422. Topology / ROM / uncertainty / adaptive → 422. UI
  `DesignGraph/MagneticFields.jsx` (presets steel, NdFeB, ferrite, air). Hito `python validate_magnetic.py
  [--server …]`: bar circuit (B, permeance μA/L, energy), magnet short / open circuit (tilted Br), imposed flux,
  harmonic quadratic ψ — all exact (1e-13); quarter toroidal core permeance μt·ln(b/a)/(π/2) to 1e-6, order 3.7.
  Tests `tests/test_magnetic.py`.
- Stub still: `ThermoPiezoelectric` (not listed in the MATERIAL selector).

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
- Frontend: `socket.io-client` in `stores/design/runSlice.js`; emits `solver_progress`, `solver_done`, `solver_error` per-run room.

**Validation Hito (FASE 2):** Cantilever T10, L/h=20, n_div=20: −0.64 % vs Timoshenko (requirement ±1 %).
Run `python validate_fem.py` and `python -m pytest tests/test_fem_fase2.py` (patch tests, load resultants,
CG vs direct, hito, conforming bisection).

## Thermal and Thermo-Mechanical (FASE 2 multiphysics)

`app/design/services/fem/thermal.py`: steady conduction on T4/T10 (1 DOF/node, `assemble_thermal`), uniform
source ∫QN dV, heat flux ∫qN dA (positive = into the body), convection ∫hNNᵀ dA + ∫hT∞N dA (Dunavant degree-4
rule: exact for T6), Dirichlet temperature; heat flux q = −k∇T (T10 via Gauss points like stress).
One-way coupling: ε_th = α(T − T_ref)[1,1,1,0,0,0], load ∫BᵀDε_th dV, stress σ = D(ε − ε_th)
(`tb.nodal_stress(..., eps0=)`; default unchanged → structural hashes unchanged, no kernel version bump).
- Spec: `physics` ['thermal'] | ['structural','thermal']; thermal entries live in the same `bcs`/`loads` lists,
  recognised by key: BC `temperature` (°C), loads `heat_flux` (W/m²), `convection` {h, T_inf}, `heat_source` (W/m³).
  Material `k`, `alpha`, `T_ref` (only added to the spec when thermal is active).
- Face set `@free` = boundary faces not referenced by any other BC/LOAD (resolved per spec in the kernel,
  `resolve_free_faces`); `@all` = whole boundary.
- `graph_to_solver_spec` infers the physics: BC `bc_type: 'temperature'`, LOAD `heat_flux|convection|heat_source`
  → thermal; supports/mechanical loads → structural; both → thermo-mechanical. Missing k (or α when coupled) → 422.
  Convection without faces = `@free`; heat flux without faces = `tip` (parametric beam).
- Summary: `thermal` {min/max T, heat_balance_W (source, flux_in, fixed_T_in, convection_out), heat_balance_error},
  `max_temperature`, `min_temperature`, `max_heat_flux_w_m2`. HDF5 fields `temperature`, `heat_flux_nodal`;
  `/surface` adds `T` [°C] and `q` [W/m²] (header `fields`, `min_T`/`max_T`/`max_q`). Results viewer shows only
  the stored fields. Preflight `physics_label`. The coupled equilibrium check is scaled by the gross thermal load.
- Topology / ROM / uncertainty / adaptive are structural only: thermal studies get 422 (`prepare_spec(allow_thermal=)`).
- Hito: `python validate_thermal.py [--server http://127.0.0.1:8080] [--keep]` — linear conduction, internal source
  (parabolic, exact), imposed flux, tip convection (exact to 1e-9), lateral-convection fin (0.15 % vs 1-D theory),
  free expansion (stress-free), constrained bar σ = −EαΔT (1e-8); server: thermal and thermo-mechanical studies
  through the queue. With a full clamp the mid-span σ is +1.7 % over EαΔT (lateral restraint at the end; physical).
  Tests: `tests/test_thermal.py`.

## Material Non-Linearity (FASE 2.5)

`app/design/services/fem/plasticity.py`: small-strain J2 (von Mises) plasticity, isotropic hardening
(`perfect`, `linear` H, `voce` Q/b/H, `table` piecewise linear and flat after the last point), backward-Euler
radial return with the **consistent tangent** (checked against finite differences) → quadratic Newton convergence.
- `solve_plastic`: `load_path` (default [1.0]; [1, 0] = load + unload) × `n_load_steps`, Newton per step
  (`nl_tolerance` 1e-8 on the residual relative to the **peak** load/reaction scale, so unloading to λ = 0 works),
  step growth after easy steps, cut-backs on divergence/stagnation; after 8 halvings the run stops at the last
  converged λ (`plasticity.limit_load_reached`, run still `done`, `converged: false`). Newton systems use the
  direct solver up to 20K DOF (near a limit load PCG crawls), then AMG-PCG with a cap (non-convergence = cut-back).
- Kernel: `material.type = 'elastoplastic_vonmises'` (`constitutive.ElastoplasticVonMises` wraps `J2Material`)
  → `FEMKernel._solve_plastic`; thermal strain (one-way coupling) is supported as an initial strain ramped with λ.
  Outputs: `equivalent_plastic_strain` (nodal/elemental, HDF5 + `/surface` field `ep`), summary `plasticity`
  {load_factor, curve (λ, max |u|, reactions, plastic fraction), cutbacks, plastic_volume_fraction, …}.
  The old penalty Newton path (`apply_bcs` + `NewtonRaphson.solve_assembled`) is no longer reached for J2.
- Graph: MATERIAL `model_type: 'elastoplastic_vonmises'` + `yield_strength`, `hardening_type`
  (perfect|linear|voce|fit), `H`, `hardening_Q`, `hardening_b`, `load_steps`, `unload`. `fit` uses
  `hardening_table`, written by the material library (`node_props_from_material`) from the tensile-test fit
  (`hardening_table_from_fit`: εp = ε − σ/E of the fitted curve); assigning a library material keeps a node's
  elastoplastic model type. UI: `DesignGraph/PlasticityFields.jsx`; Results shows εp, load reached, plastic zone.
- Topology / ROM / uncertainty / adaptive reject elastoplastic studies (422, `prepare_spec(full_kernel=)`).
- Parametric mesh `mesh_source: 'ring'` (`FEMMesh.generate_ring`: quarter thick-walled cylinder, faces inner,
  outer, x0, y0, z0, z1).
- Hito: `python validate_plasticity.py [--server …]` — uniaxial bar exact (linear and Voce hardening, permanent
  elongation after unloading, no residual stress), Newton order ≈ 2, uniaxial limit σ = σy; thick-walled cylinder
  (plane strain): first-yield pressure, elastic-zone hoop stress vs Hill (ν = 0.49, Hill assumes incompressibility),
  collapse pressure (2/√3) σy ln(b/a) within 0.01 %. Tests: `tests/test_plasticity.py`.

## Topology Optimization (FASE 4)

`app/design/services/topology/`: **SIMP** (`simp.py`) on linear tets — modified SIMP (ε = 1e-6),
volume-weighted density filter (`filter.py`, KD-tree, r = 2 × mean edge by default), Heaviside
projection with β continuation 1 → 16, OC update with bisection evaluated through filter+projection.
Ke⁰ of every element is stored once; each iteration rescales it into a fixed reduced (free-DOF) CSR
pattern with one `bincount`. Solves: direct ≤ 3000 DOF, else PCG with a seeded pyamg hierarchy reused
for a few iterations (warm start; a reused hierarchy gets at most 5× the fresh iteration count, and after two
stale failures it is rebuilt every solve — before, β = 16 made every stale attempt run 2000 CG iterations and the
AM hito took 28 min instead of 69 s); if PCG fails the hierarchy is rebuilt once, then the run switches to
direct solves (≤ `DIRECT_FALLBACK_DOF` = 100K; near-void regions, e.g. AM early on, make K too
ill-conditioned). Limit `MAX_ELEMENTS` = 150 000. T10 study meshes are reduced to T4.
- Elements touching BC/load sets are passive solid, except BCs flagged `symmetry` or `keep_solid: False`
  (`graph_to_solver_spec` sets them; plane/symmetry constraints must not freeze material).
- Not supported (clear 422): gravity/body loads, non-zero prescribed displacements.
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

### Level set and AM overhang constraint (FASE 4.2–4.3)

- **AM filter** (`am_constraints.py`, Langelaar's printing filter on unstructured meshes): elements are
  sorted into layers along `build_direction`; supporters of an element = elements of earlier layers inside
  the `max_overhang_angle` cone (angle from the horizontal, 45° default). ξ = smin(ρ, p-norm max of the
  supporters' ξ) layer by layer (P = 40); exact adjoint `backprop`. Chain in SIMP: x → density filter → AM
  (passive solid acts as support) → Heaviside → ρ̄ (`SIMPOptimizer.physical` / `chain_rule`).
  Settings `am_constraint`, `build_direction`, `max_overhang_angle`; `to_dict` drops them when off, so plain
  SIMP hashes are unchanged. `overhang_area_fraction` = down-facing iso-surface area steeper than the angle,
  off the build plate. Every topology summary gets `am` {unsupported_volume_fraction (sharp recursion),
  overhang_area_fraction, build_direction (default +Z), constrained}.
- **Level set** (`levelset.py`): **reaction-diffusion level set** (Yamada et al. 2010), *not* the
  Hamilton-Jacobi transport + re-initialisation of the plan (fragile on unstructured tets). Nodal φ ∈ [−1, 1],
  (M/Δt + τL²K_L)φⁿ⁺¹ = M(φⁿ/Δt + w) with w = normalised strain-energy density of the **ersatz** design
  (full-stiffness energy makes the void look valuable and the design flip-flops); constant matrix factorised
  once, volume follows a ramp (`ramp_iter`) via bisection on λ (φ = a − λb, no extra solves). Holes nucleate
  anywhere. Defaults τ 2e-4, Δt 0.1 (Δt 0.5 oscillates).
  Densities are cut elements → grayness ~25 % (one-element band); the 0/1 check uses `black_white` (the
  volume-matched φ contour). Needs several elements across each member, otherwise the 0/1 design can come
  out disconnected. Level set has no AM option.
- Same job kind `topology.simp`, method in `spec['topology']['method']` (`simp` | `levelset`); API
  `POST /<graph_id>/run-levelset` (keys `LEVELSET_KEYS`); the OPTIMIZATION node stores `method`.
  UI: method selector, AM switch + build direction (±X/±Y/±Z) + angle in `TopologyPanel.jsx`.
- The AM filter keeps, per layer, only its supporters' columns (`S_cols`), so a layer costs O(its supports).
- Hito: `python validate_am_levelset.py [h] [png prefix]` (see its docstring for the measured numbers; ~2 min).
  Tests: `tests/test_am_levelset.py`.

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
- Versions (plan §9.1 tree): `POST /api/design/graph/<id>/versions {note}` copies the study (new node ids, same
  creation order so "first MATERIAL" etc. hold; `meta.version_of` = new → source node ids), `parent_id` = source,
  `version` = max of the tree + 1 (PUT no longer bumps it). `GET /<id>/versions` (tree with run counts),
  `GET /<id>/diff[?against=<ancestor>]` (nodes added/removed/changed with old → new properties, edges). The first
  run of a version links to the latest run of the earlier versions (parameter_delta). Deleting a version re-attaches
  later ones to its parent. UI: `GraphProjectList.jsx` groups projects by tree (`versionTree.js`), per version:
  changes (`VersionDiffDialog.jsx`), new version, delete. Tests: `GraphProjectList.test.jsx`.
- Single study store §9.3: done 2026-11-14 (see Key frontend patterns).
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
  Study similarity = **study embedding** (`embedding.py`, plan's "embedding semántico", no language model): named
  vector blocks — geometry (CAD/mesh identity → 1, else bbox size + aspect ratios, max 0.8), material (constitutive
  model group, *family* from the material name via a keyword taxonomy — library name/description, else the MATERIAL
  node's `material_name`/label; RBF-encoded log E, ν, log ρ, log σy; μ for fluids, μr/|Br| for magnets), physics,
  loading (load + support kinds), discretization (order, log DOF) — weighted per-block cosine (weights `WEIGHTS`;
  a block missing on either side drops out, unknown family is no penalty); another physics caps the similarity at
  0.45. `find_similar_runs` returns `similarity_breakdown` + the case's `material_family` (shown in the Validation
  panel). Tests `tests/test_embedding.py` (taxonomy, ranking: other steel > stainless > aluminium > PLA; thermal /
  fluid ≤ 0.45).
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

Loop (`FEMKernel.solve_adaptive`): solve → ZZ estimate → Dörfler marking → conforming bisection, until the
**estimated relative energy-norm error** η = √(Σηₑ² / (‖u_h‖²_E + Σηₑ²)) < `target_error` or `max_cycles` solves.
Linear elastic structural only (T4 or T10; T10 is the default and the one worth using).
- `error_estimator.py`: `zz_estimate` — T4: nodal averaging; **T10: SPR** (quadratic least-squares fit of the
  Gauss-point stresses on each corner patch, linear on thin boundary patches; mids = mean of the two end
  patches). Indicators integrated with a 14-point degree-5 rule. `mark_dorfler(eta2, theta)`.
  Effectivity (estimate / true) on the FASE 2 beam: 0.70–0.77 on coarse meshes → ~1 above ~15K DOF
  (the clamp singularity is on the boundary). Nodal averaging for T10 gave 0.42–0.55: do not go back.
- `mesh_adaptivity.refine_mesh`: longest-edge bisection of the corner tets (conforming), T10 mids rebuilt;
  a split edge's new corner takes the old mid-node position (follows curved CAD faces), unsplit edges keep
  their mid node. Node sets: new node joins when both edge ends are in the set; face sets rebuilt from the
  boundary faces whose nodes are all in the set. No coarsening (the old random-removal stub was deleted).
- Every refined mesh is tier-checked; at the limit the loop stops with the last solution (`stopped: 'tier'`).
- API `POST /api/design/solver/<graph_id>/run-adaptive` {target_error 0.05, max_cycles 5, theta 0.5 + overrides}:
  uses the study's spec (`prepare_spec`, 422 thermal/elastoplastic, 413 initial tier), `spec['adaptive']` (hashed),
  `SimulationRun(purpose='adaptive')`, job `fem.adaptive` (queue `solve`). Socket `adaptive_progress` per cycle +
  `solver_progress`/`solver_done`. `GET /<run>/status` adds `adaptive` and `adaptive_log`. Results = last mesh
  (Results mode, `/surface`). Adaptive runs are reproducible bit for bit (`/reproduce`).
- UI: SolverPanel "h-Refinar" + error objetivo / ciclos máx. (`designStore.startAdaptiveRun`, `adaptiveSettings`),
  `AdaptiveMonitor.jsx` (estimated error vs target, mesh growth). Test `stores/designStore.test.js`.
- Hito: `python validate_adaptive.py [--server URL]` (~2 min local): true error from an extrapolated reference
  energy; coarse beam estimate < 5 % in 3 cycles (true error 6.5 % then — ask ~3.5 % for a true 5 %); energy rate
  1.3–1.4 vs uniform 0.41; uniform n_div 80 accuracy with 6.8× fewer DOF. Server: queue, log, surface, reproduce.
  Tests: `tests/test_adaptive.py`.

### Supported CAE Mesh Formats

`.vtu`, `.vtk`, `.pvtu` (VTK/ParaView), `.inp` (Abaqus), `.bdf`/`.nas`/`.dat` (Nastran/ANSYS), `.msh` (GMSH), `.med` (Salome MED), `.exo`/`.e` (Exodus II), `.cdb` (ANSYS CDB), `.xdmf`/`.xmf` (XDMF), `.k`/`.key` (LS-DYNA single), `.zip` (LS-DYNA multi-file assembly).

LS-DYNA and Abaqus `.inp` are parsed with native Python parsers; all others go through `meshio`.
