# Plan de Implementación: CAE de Nueva Generación

## Premisa Arquitectónica Central

Todo el sistema se organiza en torno a una primitiva única:

```
DesignGraph = (V, E, L, Λ)
  V  = nodos de ingeniería (concepto, geometría, material, carga, resultado, optimización)
  E  = aristas dirigidas con tipo semántico
  L  = etiquetas multinivel (física, manufactura, dependencia)
  Λ  = función de nivel asociada a nodos geométricos (level-set implícita)
```

Cada simulación, optimización y resultado es una **transformación de este grafo**. Nada ocurre fuera de él.

---

## Límites de Modelo por Nivel (Model Tiers)

Estos límites se aplican en backend y frontend y se comunican al usuario antes de iniciar cualquier operación.

| Tier | Nombre | Nodos (FEM) | Elementos | DOF máx | Modo solver | ROM disponible |
|------|--------|-------------|-----------|---------|-------------|----------------|
| 0 | Nano / Conceptual | ≤ 5 K | ≤ 20 K | ≤ 30 K | directo denso | siempre |
| 1 | Interactivo | ≤ 100 K | ≤ 400 K | ≤ 600 K | iterativo (CG/GMRES) | siempre |
| 2 | Estándar escritorio | ≤ 1 M | ≤ 4 M | ≤ 6 M | sparse iterativo | post-ejecución |
| 3 | HPC local | ≤ 10 M | ≤ 40 M | ≤ 60 M | parallel sparse (SciPy + mpi4py opcional) | no |
| 4 | HPC remoto (futuro) | > 10 M | ilimitado | – | petición externa | no |

Límites de archivo: single file ≤ 500 MB (existente), ZIP assembly ≤ 2 GB, graph export (JSON-LD) ≤ 50 MB.

El backend rechaza con 413 + mensaje descriptivo cualquier operación fuera del tier declarado.

---

## Lo que se reutiliza íntegramente

| Módulo existente | Rol en el nuevo sistema |
|-----------------|------------------------|
| `app/__init__.py` + `create_app` | Fábrica Flask — se amplía con nuevos blueprints |
| `app/extensions.py` (db, migrate, compress) | Sin cambios |
| `app/models/base.py` (BaseModel + UUID) | Base de todos los nuevos modelos |
| `app/cae/api/cae_routes.py` | Pasa a ser el visor de **resultados** del nuevo solver |
| `app/cae/services/mesh_parser.py` | Parser de entrada para geometría inicial |
| `app/cae/services/step_mesher.py` | Generador de malla inicial vía GMSH |
| `app/step_view_pro/` (12 blueprints) | Visor STEP — se convierte en fuente de geometría para el grafo |
| `config/config.py` | Se amplía con parámetros del solver |
| `frontend/src/App.jsx` | Se refactoriza para soportar modo "Design" |
| `frontend/src/stores/viewerStore.js` | Se extiende con estado del grafo y solver |
| `frontend/src/components/CAEViewer.jsx` | Visor de resultados FEM (VTK.js) — se mantiene |
| `frontend/src/components/StepViewer3D.jsx` | Importador de geometría — se mantiene |
| Cytoscape.js (ya instalado) | Editor del grafo de diseño |
| React + MUI dark theme | Sin cambios de stack |
| PostgreSQL + JSONB | Almacén del grafo y resultados |
| GMSH (ya en requirements.txt) | Mallado inicial adaptado al grafo |
| meshio + NumPy | Parser entrada + álgebra lineal del solver |

---

## FASE 0 — Infraestructura Base (semana 1-2)

### 0.1 Nuevas dependencias en `requirements.txt`

```
flask-socketio==5.3.6        # WebSocket para streaming de resultados
scipy>=1.11.0                # Sparse solvers (CG, GMRES, SPSOLVE)
networkx>=3.2                # Algoritmos de grafo en Python
scikit-learn>=1.3.0          # PCA/SVD para ROM
h5py>=3.9.0                  # Almacenamiento eficiente de matrices FEM
python-ariadne>=0.21         # GraphQL (opcional, para queries de grafo)
hashlib (stdlib)             # SHA-256 para trazabilidad
```

Frontend (`frontend/package.json`, nuevas entradas en `dependencies`):
```json
"react-flow-renderer": "^10.x",   // Editor de grafo alternativo a Cytoscape (más limpio para flujos)
"socket.io-client": "^4.6.0",     // WebSocket cliente
"d3-contour": "^4.0.0",           // Visualización de level sets / iso-curvas
"@codemirror/react": "^6.x",      // Editor de modelos constitutivos en alto nivel
```

### 0.2 Nueva estructura de carpetas

```
app/
  design/                     # NUEVO — núcleo del nuevo sistema
    models/
      graph.py                # DesignGraph, DesignNode, DesignEdge
      physics.py              # PhysicsConfig, DomainConfig
      material.py             # MaterialModel (paramétrico + NN)
      simulation.py           # SimulationRun + hash de trazabilidad
      result.py               # FieldResult, ConvergenceLog
      validation.py           # ExperimentalRecord, CorrelationEntry
    api/
      graph_routes.py         # CRUD del grafo de diseño
      solver_routes.py        # Lanzar solver, streaming resultados
      material_routes.py      # CRUD modelos de material
      topology_routes.py      # Optimización topológica
      rom_routes.py           # ROM — construcción y evaluación
      validation_routes.py    # Registro experimental y recalibración
      traceability_routes.py  # Hash, versiones, reproducibilidad
    services/
      graph_service.py        # Lógica del grafo (NetworkX)
      fem/
        kernel.py             # Ensamblaje global K, M, C, F
        elements.py           # Librería de elementos (T4, H8, T10, Q4...)
        constitutive.py       # Registro de modelos constitutivos
        assembler.py          # Ensamblador por física (estructural, térmico, fluido, EM)
        solver.py             # Dispatcher: directo / iterativo / no-lineal
        nonlinear.py          # Newton-Raphson + Arc-length
        error_estimator.py    # ZZ error estimator para refinamiento adaptativo
        adaptive.py           # Bucle de refinamiento adaptativo
      topology/
        simp.py               # Optimización topológica SIMP
        levelset.py           # Level set method
        filter.py             # Filtros de densidad (RAMP, filtro Heaviside)
        am_constraints.py     # Restricciones de manufactura aditiva
      rom/
        pod.py                # Proper Orthogonal Decomposition
        hyperreduction.py     # DEIM para ROM no-lineal
        online_solver.py      # Evaluación del ROM en tiempo real
      material/
        parametric.py         # Modelos paramétricos (polynomial, spline)
        neural.py             # Modelo constitutivo como red neuronal
        uncertainty.py        # Propagación Monte Carlo + interval arithmetic
        calibrator.py         # Ajuste de parámetros a datos experimentales
      traceability/
        hasher.py             # SHA-256 de parámetros de simulación
        reporter.py           # JSON-LD + Markdown auto-report
      validation/
        correlator.py         # Búsqueda de casos similares
        recalibrator.py       # Recalibración de modelos con datos reales
    __init__.py

frontend/src/
  components/
    DesignGraph/              # NUEVO
      GraphEditor.jsx         # Editor Cytoscape/ReactFlow del grafo
      NodePanel.jsx           # Panel de propiedades del nodo seleccionado
      EdgePanel.jsx           # Panel de propiedades de arista
      ConceptToolbar.jsx      # Paleta de tipos de nodo
      LevelSetPreview.jsx     # Preview 2D de level set implícita
    Solver/
      SolverPanel.jsx         # Config de solver + lanzar
      ConvergenceMonitor.jsx  # Gráfica de residuos en tiempo real (WebSocket)
      FieldSelector.jsx       # Selección de campo/tiempo para visualización
    Topology/
      TopologyPanel.jsx       # Config SIMP/level-set
      DensityField.jsx        # Visualización de campo de densidad en VTK.js
    ROM/
      ROMExplorer.jsx         # Sliders para modificar parámetros → respuesta inmediata
      ROMBuilder.jsx          # Panel de construcción del ROM
    Material/
      MaterialEditor.jsx      # Editor de modelos constitutivos
      UncertaintyBand.jsx     # Visualización de intervalos de confianza
    Traceability/
      SimHistory.jsx          # Historial de simulaciones con hash
      ReproduceDialog.jsx     # Reproducir exactamente una simulación anterior
    Validation/
      ExperimentUpload.jsx    # Subida de datos experimentales
      CorrelationView.jsx     # Vista de correlación simulación-ensayo
  stores/
    designStore.js            # Zustand — estado del grafo de diseño
    solverStore.js            # Zustand — estado del solver + streaming
    romStore.js               # Zustand — ROM disponibles y estado
```

### 0.3 Registro de blueprints en `app/__init__.py`

Agregar en `_register_blueprints()`:

```python
from app.design.api import (
    graph_routes, solver_routes, material_routes,
    topology_routes, rom_routes, validation_routes, traceability_routes,
)
app.register_blueprint(graph_routes.bp,        url_prefix='/api/design/graph')
app.register_blueprint(solver_routes.bp,       url_prefix='/api/design/solver')
app.register_blueprint(material_routes.bp,     url_prefix='/api/design/material')
app.register_blueprint(topology_routes.bp,     url_prefix='/api/design/topology')
app.register_blueprint(rom_routes.bp,          url_prefix='/api/design/rom')
app.register_blueprint(validation_routes.bp,   url_prefix='/api/design/validation')
app.register_blueprint(traceability_routes.bp, url_prefix='/api/design/traceability')
```

Agregar `flask-socketio` init:

```python
from flask_socketio import SocketIO
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')
```

---

## FASE 1 — Grafo de Diseño (semana 2-4)

Esta es la columna vertebral. Todo lo demás produce o consume nodos/aristas de este grafo.

### 1.1 Modelos de base de datos (`app/design/models/graph.py`)

```python
class DesignNode(BaseModel):
    __tablename__ = 'design_nodes'

    graph_id    = Column(UUID, ForeignKey('design_graphs.id'))
    node_type   = Column(String(50))   # CONCEPT | GEOMETRY | MATERIAL | BC | LOAD | RESULT | OPTIMIZATION
    label       = Column(String(255))
    level       = Column(Integer)      # nivel del grafo (0=sistema, 1=subsistema, 2=componente, 3=feature)
    properties  = Column(JSONB)        # payload específico por tipo de nodo
    # Para nodos GEOMETRY: level set implícita serializada
    level_set   = Column(JSONB)        # {"sdf_func": "sphere", "params": {...}, "bbox": [...]}
    # Para nodos RESULT: referencia al archivo HDF5 de resultados
    result_ref  = Column(String(1000)) # path al .h5
    tier        = Column(Integer)      # 0-4, límite de modelo asignado


class DesignEdge(BaseModel):
    __tablename__ = 'design_edges'

    graph_id    = Column(UUID, ForeignKey('design_graphs.id'))
    source_id   = Column(UUID, ForeignKey('design_nodes.id'))
    target_id   = Column(UUID, ForeignKey('design_nodes.id'))
    edge_type   = Column(String(50))   # FUNCTIONAL | PHYSICAL | DEPENDS_ON | MANUFACTURED_BY | CONSTRAINS | PRODUCES
    weight      = Column(Float, default=1.0)
    properties  = Column(JSONB)


class DesignGraph(BaseModel):
    __tablename__ = 'design_graphs'

    name        = Column(String(255))
    description = Column(Text)
    version     = Column(Integer, default=1)
    parent_id   = Column(UUID, ForeignKey('design_graphs.id'), nullable=True)  # versionado
    hash        = Column(String(64))   # SHA-256 del estado completo del grafo
    tier        = Column(Integer, default=1)
    status      = Column(String(50))   # draft | simulating | optimizing | validated
    metadata    = Column(JSONB)
```

### 1.2 Servicio de grafo (`app/design/services/graph_service.py`)

Usa NetworkX para operaciones de grafo:

```python
import networkx as nx

class DesignGraphService:
    def to_networkx(self, graph_id) -> nx.DiGraph
    def add_node(self, graph_id, node_type, label, properties, level) -> DesignNode
    def add_edge(self, graph_id, source_id, target_id, edge_type) -> DesignEdge
    def get_subgraph_by_level(self, graph_id, level) -> nx.DiGraph
    def get_physics_domain(self, graph_id) -> dict   # extrae nodos BC + LOAD + MATERIAL
    def compute_dependency_order(self, graph_id) -> list  # orden topológico para simulación
    def validate_completeness(self, graph_id) -> list  # errores de completitud
    def to_jsonld(self, graph_id) -> dict   # exporta JSON-LD para trazabilidad
```

### 1.3 API REST (`app/design/api/graph_routes.py`)

```
POST   /api/design/graph/                    → crear nuevo grafo
GET    /api/design/graph/<id>                → leer grafo completo
PUT    /api/design/graph/<id>                → actualizar metadatos
DELETE /api/design/graph/<id>

POST   /api/design/graph/<id>/nodes          → agregar nodo
PUT    /api/design/graph/<id>/nodes/<nid>    → actualizar nodo
DELETE /api/design/graph/<id>/nodes/<nid>

POST   /api/design/graph/<id>/edges          → agregar arista
DELETE /api/design/graph/<id>/edges/<eid>

GET    /api/design/graph/<id>/validate       → validación de completitud
GET    /api/design/graph/<id>/export/jsonld  → exportar JSON-LD

POST   /api/design/graph/<id>/import/step    → importar geometría de STEP existente como nodo GEOMETRY
POST   /api/design/graph/<id>/import/mesh    → importar malla CAE existente como nodo GEOMETRY
```

### 1.4 UI — `GraphEditor.jsx`

Usa ReactFlow (más limpio que Cytoscape para este caso):

```
Tipos de nodo con color semántico:
  CONCEPT       → azul índigo  (hexágono)
  GEOMETRY      → verde        (cilindro)
  MATERIAL      → naranja      (cubo)
  BC            → rojo         (triángulo invertido)
  LOAD          → amarillo     (flecha)
  RESULT        → verde agua   (diamante)
  OPTIMIZATION  → púrpura      (estrella)

Tipos de arista con trazo semántico:
  FUNCTIONAL    → sólida azul
  PHYSICAL      → sólida gris
  DEPENDS_ON    → punteada
  MANUFACTURED_BY → dash-dot verde
  CONSTRAINS    → roja
  PRODUCES      → sólida verde agua
```

Controles del editor:

- Click en nodo → abre `NodePanel.jsx` en el drawer derecho
- Doble click en lienzo → diálogo "Agregar concepto"
- Drag desde puerto de salida de nodo A a puerto de entrada de nodo B → crea arista con selector de tipo
- Botón "Validar grafo" → muestra errores de completitud en overlay
- Botón "Iniciar simulación" → activo solo cuando el grafo está completo

### 1.5 Cambio en `App.jsx`

La barra superior pasa de dos modos (CAE / STEP) a tres:

```
[ Design Graph ]  [ STEP Viewer ]  [ CAE Results ]
```

Design Graph es el modo por defecto para proyectos nuevos. Los otros dos modos son ahora "sub-herramientas" accesibles desde nodos del grafo.

---

## FASE 2 — Kernel FEM Unificado (semana 3-8)

El solver más importante. Se construye sobre NumPy + SciPy sparse. No requiere compilar nada.

### 2.1 Librería de elementos (`app/design/services/fem/elements.py`)

Implementar en orden de prioridad:

**Tier 0/1 (interactivos):**
- `T3` — triángulo lineal 2D (3 nodos, plano stress/strain)
- `T6` — triángulo cuadrático 2D
- `T4` — tetraedro lineal 3D (4 nodos) ← clave para geometrías complejas
- `T10` — tetraedro cuadrático 3D (10 nodos) ← precisión

**Tier 2 (estándar):**
- `H8` — hexaedro trilineal 3D (8 nodos)
- `H20` — hexaedro cuadrático 3D (20 nodos)
- `Q4` — cuadrilátero 2D
- `B2` — barra (Euler-Bernoulli) 1D
- `B3` — barra cuadrática 1D

Cada elemento implementa:

```python
class BaseElement:
    def shape_functions(xi, eta, zeta) -> np.ndarray      # N(ξ,η,ζ)
    def shape_derivatives(xi, eta, zeta) -> np.ndarray    # dN/dξ
    def jacobian(coords, xi, eta, zeta) -> np.ndarray
    def stiffness_matrix(coords, D) -> np.ndarray         # Ke = ∫ B^T D B dV
    def mass_matrix(coords, rho) -> np.ndarray            # Me = ∫ N^T ρ N dV
    def thermal_load_vector(coords, q) -> np.ndarray
    def surface_load_vector(face_coords, traction) -> np.ndarray
    def gauss_points() -> list[(weight, xi, eta, zeta)]
```

### 2.2 Modelos constitutivos (`app/design/services/fem/constitutive.py`)

Registro centralizado. El usuario declara en alto nivel; el sistema genera D(σ,ε,T,B,...):

```python
CONSTITUTIVE_REGISTRY = {
    # Estructural
    'linear_elastic_isotropic':    LinearElasticIsotropic,
    'linear_elastic_orthotropic':  LinearElasticOrthotropic,
    'elastoplastic_vonmises':      ElastoplasticVonMises,
    'hyperelastic_neohookean':     HyperelasticNeoHookean,
    'viscoelastic_maxwell':        ViscoelasticMaxwell,

    # Térmico
    'fourier_isotropic':           FourierIsotropic,
    'fourier_orthotropic':         FourierOrthotropic,

    # Acoplado
    'thermoelastic':               Thermoelastic,        # ε = C:σ + α ΔT
    'piezoelectric':               Piezoelectric,        # σ = C:ε - e^T E
    'thermopiezoelectric':         ThermoPiezoelectric,

    # Fluido (Stokes / Navier-Stokes linealizado)
    'newtonian_fluid':             NewtonianFluid,

    # Electromagnético (quasi-estático)
    'linear_magnetic':             LinearMagnetic,
}
```

Cada modelo implementa:

```python
class ConstitutiveModel:
    def get_D_matrix(self, state: dict) -> np.ndarray   # estado: σ, ε, T, E, B, etc.
    def get_coupling_terms(self, physics_list: list) -> dict  # acoplamiento automático
    def update_internal_variables(self, strain_inc) -> dict  # para modelos inelásticos
    def is_linear(self) -> bool
```

### 2.3 Ensamblador (`app/design/services/fem/assembler.py`)

```python
class GlobalAssembler:
    """
    Ensambla K, M, C, F para todos los DOF de un grafo de diseño.
    Los DOF disponibles por nodo dependen de la física:
      estructural:    u_x, u_y, u_z
      térmico:        T
      fluido:         p, u_x, u_y, u_z
      electromagnético: φ (potencial), A_x, A_y, A_z

    Los DOF se asignan automáticamente según los modelos constitutivos
    de los nodos MATERIAL del grafo de diseño.
    """
    def assign_dofs(self, mesh, physics_list) -> dict    # node_id → [dof_ids]
    def assemble_K(self, mesh, materials, dof_map) -> scipy.sparse.csr_matrix
    def assemble_M(self, mesh, materials, dof_map) -> scipy.sparse.csr_matrix
    def assemble_F(self, mesh, loads, dof_map) -> np.ndarray
    def apply_boundary_conditions(self, K, F, bcs) -> (K_mod, F_mod, penalty_map)
```

### 2.4 Solver dispatcher (`app/design/services/fem/solver.py`)

```python
class FEMSolver:
    def solve(self, run: SimulationRun) -> FieldResult:
        tier = run.graph.tier
        is_linear = self._detect_linearity(run)

        if tier <= 1 and is_linear:
            return self._solve_direct(run)          # scipy.linalg.spsolve
        elif tier <= 2 and is_linear:
            return self._solve_iterative_cg(run)    # CG con precondicionador ILU
        elif not is_linear:
            return self._solve_nonlinear(run)        # Newton-Raphson + Arc-length
        else:
            return self._solve_parallel(run)         # scipy sparse + opcional mpi4py

    def _detect_linearity(self, run) -> bool:
        # Revisa si todos los modelos constitutivos son lineales
        # y si todas las BCs son independientes de la solución
        ...

    def stream_progress(self, run_id, socketio):
        # Emite eventos por WebSocket:
        # { event: "progress", iter: n, residual: r, time: t }
        ...
```

### 2.5 No-linealidad (`app/design/services/fem/nonlinear.py`)

```python
class NewtonRaphson:
    """
    Formulación Lagrangiana Total para grandes deformaciones.
    Activa automáticamente si cualquier modelo constitutivo reporta is_linear() = False
    o si las cargas superan el umbral de linealización.
    """
    max_iter = 50
    tol_residual = 1e-8
    tol_displacement = 1e-10

    def solve(self, K_tangent_func, F_ext, u0, constraints) -> (u, converged, history)


class ArcLengthContinuation:
    """
    Método de Riks (longitud de arco cilíndrica).
    Activa automáticamente si Newton-Raphson detecta punto límite o bifurcación.
    """
    def solve(self, system, u0, load_factor0, ds0) -> (u_path, lambda_path)
```

### 2.6 API del solver (`app/design/api/solver_routes.py`)

```
POST /api/design/solver/<graph_id>/run       → lanzar simulación (devuelve run_id)
GET  /api/design/solver/<run_id>/status      → estado (queued|running|done|failed)
GET  /api/design/solver/<run_id>/results     → resultados (field data)
POST /api/design/solver/<run_id>/cancel      → cancelar

WebSocket events (via flask-socketio), room = run_id:
  "solver_progress": { iter, residual, wall_time, percent }
  "solver_done":     { run_id, hash, fields, convergence_log }
  "solver_error":    { run_id, message, traceback }
```

### 2.7 UI — `SolverPanel.jsx` + `ConvergenceMonitor.jsx`

```
SolverPanel:
  ┌─────────────────────────────────────┐
  │ Física: [☑ Estructural] [☑ Térmico] │
  │         [ ] Fluido     [ ] EM       │
  │                                     │
  │ Tier detectado: Tier 1 (100K DOF)   │
  │ Tiempo estimado: ~8 s               │
  │                                     │
  │ Tolerancia: 1e-8  Iter máx: 100     │
  │ No-linealidad: AUTO (detectada)     │
  │                                     │
  │ [ INICIAR SIMULACIÓN ]              │
  └─────────────────────────────────────┘

ConvergenceMonitor:
  Residuo vs iteración → gráfica Recharts en tiempo real
  Línea de tolerancia indicada
  Botón "Cancelar" activo durante la corrida
```

---

## FASE 3 — Mallado Adaptativo Automático (semana 5-9)

El mallado **nunca es responsabilidad del usuario**. El sistema decide cuándo y cómo refinar.

### 3.1 Estimador de error (`app/design/services/fem/error_estimator.py`)

Implementar el estimador de Zienkiewicz-Zhu (ZZ) — el más robusto y ampliamente validado:

```python
class ZZErrorEstimator:
    """
    Para cada elemento calcula el error relativo de la solución.
    Compara la solución FEM con un campo suavizado por mínimos cuadrados.
    """
    def compute_element_errors(self, mesh, solution) -> np.ndarray  # error por elemento
    def global_error_norm(self, mesh, solution) -> float
    def mark_elements(self, errors, strategy='fixed_fraction', theta=0.3) -> np.ndarray  # bool mask
    def estimate_refinement_needed(self, errors, tol=0.05) -> bool
```

### 3.2 Refinador adaptativo (`app/design/services/fem/adaptive.py`)

```python
class AdaptiveRefinementLoop:
    """
    Bucle principal: simular → estimar error → refinar malla → re-simular.
    La solución anterior se usa como condición inicial (warm start).
    Se detiene cuando el error global es < tolerancia o se alcanza el tier máximo.
    """
    max_cycles = 5
    error_tolerance = 0.05   # 5% error relativo global
    max_refinement_factor = 4.0  # no puede crecer más de 4× el tamaño inicial

    def run(self, graph_id, initial_mesh, physics_config, socketio) -> SimulationRun:
        mesh = initial_mesh
        for cycle in range(self.max_cycles):
            result = FEMSolver().solve(...)
            errors = ZZErrorEstimator().compute_element_errors(mesh, result)

            socketio.emit('adaptive_progress', {
                'cycle': cycle,
                'nodes': mesh.n_nodes,
                'global_error': global_error,
                'marked_elements': int(marked.sum()),
            })

            if not ZZErrorEstimator().estimate_refinement_needed(errors):
                break

            mesh = GMSHRefiner().refine(mesh, marked_elements, strategy='h')
            # warm start: proyectar solución anterior sobre nueva malla
            warm_start = self._project_solution(result, mesh)

        return result
```

### 3.3 Integración con GMSH

GMSH ya está integrado en el proyecto. Se amplía `step_mesher.py` con:

```python
def refine_mesh(existing_mesh_path: str, marked_elements: np.ndarray,
                strategy: str = 'h') -> str:
    """
    Toma una malla existente y los elementos marcados para refinar.
    Usa GMSH Refine by subdivision (h-refinement) o cambio de orden (p-refinement).
    Devuelve el path de la nueva malla .vtu.
    """
```

### 3.4 API

```
POST /api/design/solver/<graph_id>/run-adaptive
     body: { error_tolerance: 0.05, max_cycles: 5 }
     → ejecuta el bucle adaptativo completo
     → emite eventos WebSocket por cada ciclo
```

### 3.5 UI

En `SolverPanel.jsx` agregar sección colapsable:

```
▶ Mallado Adaptativo
  [☑] Activar refinamiento automático
  Tolerancia de error: [0.05] (5%)
  Ciclos máximos: [5]
  Estrategia: (●) h-refinement  ( ) p-refinement
```

Durante el bucle, `ConvergenceMonitor.jsx` muestra adicionalmente:

```
Ciclo 1/5 | Nodos: 12,450 | Error: 12.3%  →  refinando...
Ciclo 2/5 | Nodos: 28,900 | Error: 6.1%   →  refinando...
Ciclo 3/5 | Nodos: 51,200 | Error: 4.2%   ✓ convergido
```

---

## FASE 4 — Optimización Topológica (semana 7-12)

### 4.1 Método SIMP (`app/design/services/topology/simp.py`)

El método SIMP (Solid Isotropic Material with Penalization) es el estándar industrial. La variable de diseño es la densidad `ρ ∈ [0,1]` en cada elemento:

```
E(ρ) = ρ^p · E₀    (p=3 típico)
Minimize: C = F^T u   (compliance)
Subject to: K(ρ) u = F
            ∑ ρᵢ Vᵢ ≤ V_f · V_total   (fracción de volumen)
            0 ≤ ρᵢ ≤ 1
```

```python
class SIMPOptimizer:
    p_penalization: float = 3.0
    volume_fraction: float = 0.5
    filter_radius: float = None      # None → auto (2× tamaño medio de elemento)
    max_iter: int = 200
    tol: float = 1e-4                # cambio en densidad entre iteraciones

    # Algoritmo de actualización: OC (Optimality Criteria) — rápido y robusto
    def run(self, mesh, loads, bcs, socketio) -> (densities, compliance_history)

    def _compute_sensitivities(self, u, Ke_list, densities) -> np.ndarray
    def _apply_filter(self, sensitivities, mesh) -> np.ndarray    # filtro de sensibilidad
    def _update_densities_oc(self, densities, sensitivities, volume_fraction) -> np.ndarray
    def _threshold(self, densities, beta=8, eta=0.5) -> np.ndarray  # Heaviside projection
```

### 4.2 Level Set Method (`app/design/services/topology/levelset.py`)

Para geometrías con bordes nítidos (necesario para manufactura aditiva de precisión):

```python
class LevelSetOptimizer:
    """
    La función de nivel φ(x) < 0 → material, φ(x) > 0 → vacío.
    Se evoluciona con la ecuación de Hamilton-Jacobi:
      ∂φ/∂t + v_n |∇φ| = 0
    donde v_n = velocidad normal = sensibilidad de la función objetivo.
    """
    def evolve(self, phi, sensitivity, dt) -> np.ndarray
    def reinitialize(self, phi) -> np.ndarray   # re-distancia signed distance function
    def extract_isosurface(self, phi, mesh) -> trimesh.Trimesh
```

### 4.3 Restricciones de manufactura aditiva (`app/design/services/topology/am_constraints.py`)

```python
class AMConstraints:
    """
    Restricciones específicas para manufactura aditiva:
    - Overhang constraint: ángulo ≤ 45° sin soporte
    - Minimum feature size
    - Build direction dependency
    """
    build_direction: np.ndarray = np.array([0, 0, 1])
    max_overhang_angle: float = 45.0   # grados
    min_feature_size: float = None     # None → auto (1/20 de bbox)

    def compute_overhang_violation(self, densities, mesh) -> np.ndarray
    def apply_am_filter(self, sensitivities, densities, mesh) -> np.ndarray
```

### 4.4 API

```
POST /api/design/topology/<graph_id>/run-simp
     body: { volume_fraction, p_penalization, am_constraints: bool, build_dir: [0,0,1] }
     → lanza optimización
     → WebSocket: { iter, compliance, volume, densities_delta_max }

POST /api/design/topology/<graph_id>/run-levelset

GET  /api/design/topology/<run_id>/densities     → campo de densidades actual
GET  /api/design/topology/<run_id>/isosurface    → isosuperficie como GLB (threshold=0.5)
POST /api/design/topology/<run_id>/extract-mesh
     body: { threshold: 0.5 }
     → extrae malla STL/VTU del resultado óptimo → crea nodo GEOMETRY en el grafo
```

### 4.5 UI — `TopologyPanel.jsx` + `DensityField.jsx`

```
TopologyPanel:
  ┌─────────────────────────────────────────┐
  │ Método: (●) SIMP  ( ) Level Set         │
  │                                         │
  │ Fracción de volumen: ──●────  50%        │
  │ Penalización p:      ──●────  3.0        │
  │ Iteraciones máx:     [200]              │
  │                                         │
  │ ☑ Restricciones manufactura aditiva    │
  │   Dirección de impresión: +Z ▼          │
  │   Ángulo máximo overhang: 45°           │
  │                                         │
  │ [ OPTIMIZAR TOPOLOGÍA ]                 │
  │                                         │
  │ Progreso: ████████░░ 83% (iter 166)    │
  │ Compliance: 0.0234 → 0.0089 (−62%)    │
  │                                         │
  │ [ EXTRAER GEOMETRÍA ÓPTIMA ]           │
  └─────────────────────────────────────────┘
```

`DensityField.jsx` usa `CAEViewer.jsx` existente con un colormap de densidad (0=azul→vacío, 1=rojo→sólido). Se actualiza cada N iteraciones vía WebSocket.

---

## FASE 5 — ROM e Interactividad en Tiempo Real (semana 10-15)

### 5.1 Construcción del ROM (`app/design/services/rom/pod.py`)

```python
class PODROMBuilder:
    """
    Proper Orthogonal Decomposition (SVD) para construir una base reducida.

    Flujo:
    1. Correr N_snapshots simulaciones con parámetros variados (muestreo LHS)
    2. Apilar las soluciones como columnas de la snapshot matrix S ∈ ℝ^(N_dof × N_snap)
    3. SVD: S = U Σ V^T → retener los r modos más significativos (Φ ∈ ℝ^(N_dof × r))
    4. Proyectar: K_r = Φ^T K Φ (r×r), F_r = Φ^T F (r×1)
    5. Resolver: K_r u_r = F_r en microsegundos
    6. Reconstruir: u = Φ u_r

    El ROM es válido para cualquier parámetro dentro del rango muestreado.
    Parámetros típicos: magnitude de carga, propiedades de material, geometría paramétrica.
    """
    n_snapshots_default: int = 50
    energy_threshold: float = 0.9999   # retener modos que capturen 99.99% de energía

    def build(self, graph_id, parameter_space: dict, socketio) -> ROMDatabase
    def estimate_error(self, rom, test_params) -> float
    def save_rom(self, rom, graph_id) -> str   # path al .h5 del ROM
```

### 5.2 Evaluación online (`app/design/services/rom/online_solver.py`)

```python
class ROMOnlineSolver:
    """
    Evalúa el ROM en < 100ms para Tier 0/1.
    Se carga una vez en memoria al activar el explorador de ROM.
    """
    def load_rom(self, rom_path: str)
    def evaluate(self, params: dict) -> FieldResult   # < 100ms para r < 50
    def get_parameter_ranges(self) -> dict
```

### 5.3 API

```
POST /api/design/rom/<graph_id>/build
     body: { parameter_space: { load_magnitude: [100, 1000], E: [70e9, 210e9] }, n_snapshots: 50 }

GET  /api/design/rom/<graph_id>/list        → ROMs disponibles para este grafo
POST /api/design/rom/<rom_id>/evaluate
     body: { params: { load_magnitude: 450, E: 140e9 } }
     → respuesta < 100ms con campo completo
```

### 5.4 UI — `ROMExplorer.jsx`

El componente más innovador de la UI:

```
┌────────────────────────────────────────────────────────────────────┐
│ ROM Explorer — Respuesta en tiempo real                            │
│                                                                    │
│ Carga F [N]:   100 ─────────●──────────── 1000        [450 N]    │
│ Módulo E [GPa]:  70 ──────────────●─────── 210        [140 GPa]  │
│ Temperatura [°C]: 20 ─●─────────────────── 200        [25 °C]    │
│                                                                    │
│ ← Mueve el slider → el modelo 3D se actualiza en < 100ms          │
│                                                                    │
│ Tensión máx: 234.5 MPa    Despl. máx: 0.23 mm                    │
│ Factor seguridad: 1.45    [⚠ Cercano al límite]                   │
│                                                                    │
│ Tiempo respuesta: 12 ms   Modos ROM: 24/50   Error est: 0.3%     │
│                                                                    │
│ [ CORRER SIMULACIÓN COMPLETA CON ESTOS PARÁMETROS ]               │
└────────────────────────────────────────────────────────────────────┘
```

El visor 3D VTK.js se conecta directamente al `ROMOnlineSolver` vía WebSocket. Al mover cualquier slider, se emite un evento que el backend procesa y responde con el campo actualizado en < 100ms para Tier 0/1.

### 5.5 Implementación WebSocket de sliders

```javascript
// romStore.js
const useROMStore = create((set, get) => ({
  activeROM: null,
  params: {},
  result: null,
  responseTime: 0,

  setParam: debounce(async (key, value) => {
    const start = performance.now();
    const result = await socket.emitWithAck('rom_evaluate', {
      rom_id: get().activeROM.id,
      params: { ...get().params, [key]: value },
    });
    set({ result, responseTime: performance.now() - start });
  }, 16),  // ~60fps máximo
}));
```

---

## FASE 6 — Modelos de Material Activos (semana 12-17)

### 6.1 Modelos paramétricos (`app/design/services/material/parametric.py`)

```python
class ParametricMaterialModel:
    """
    El usuario sube datos de ensayo (σ-ε, k-T, etc.) y el sistema
    ajusta automáticamente el modelo constitutivo más apropiado.
    """
    def fit(self, experimental_data: dict, model_candidates: list) -> dict:
        # Prueba: linear, polynomial, spline, Ramberg-Osgood, Prony series, etc.
        # Devuelve el mejor ajuste con métricas de calidad
        ...

    def predict(self, strain, temperature=293) -> dict   # σ, dσ/dε
    def get_uncertainty_bounds(self, strain, confidence=0.95) -> (lower, upper)
```

### 6.2 Propagación de incertidumbre (`app/design/services/material/uncertainty.py`)

```python
class UncertaintyPropagator:
    """
    Monte Carlo o Interval Arithmetic para propagar incertidumbre
    de propiedades de material a los campos de resultado.

    Límites de modelo:
    - Tier 0/1: Monte Carlo 100 samples (en paralelo con ThreadPool)
    - Tier 2: Monte Carlo 500 samples
    - Tier 3+: Monte Carlo 2000 samples (o PCE — Polynomial Chaos Expansion)
    """
    def propagate_monte_carlo(self, graph_id, n_samples: int, rom_id=None) -> dict:
        # Si hay ROM disponible, usarlo para velocidad
        # Si no, correr n_samples simulaciones completas
        # Devuelve: mean_field, std_field, confidence_bands
        ...

    def compute_reliability_index(self, result_dist, failure_criterion) -> float
```

### 6.3 Calibración desde datos experimentales

```python
class MaterialCalibrator:
    """
    Ajusta parámetros del modelo constitutivo minimizando el error
    entre la simulación y los datos experimentales subidos por el usuario.

    Optimizador: scipy.optimize.minimize con gradiente numérico.
    """
    def calibrate(self, model, experimental_data, initial_params) -> dict:
        # Devuelve parámetros calibrados + incertidumbre (Hessiana inversa)
        ...
```

### 6.4 API

```
POST /api/design/material/                         → crear modelo de material
POST /api/design/material/<id>/fit                 → ajustar modelo a datos experimentales
POST /api/design/material/<id>/predict             → evaluar modelo en punto dado
POST /api/design/material/<id>/propagate-uncertainty
     body: { graph_id, n_samples, confidence }
GET  /api/design/material/<id>/uncertainty-results  → campos con bandas de confianza
```

### 6.5 UI — `MaterialEditor.jsx`

```
┌──────────────────────────────────────────────────────────┐
│ Material: Aluminio 6061-T6                              │
│                                                          │
│ Modelo constitutivo:                                     │
│ (●) Elastoplástico von Mises  ( ) Neo-Hookean           │
│ ( ) Viscoelástico Maxwell     ( ) Daño continuo         │
│                                                          │
│ Parámetros:                                              │
│ E = 69 ± 2 GPa        ν = 0.33 ± 0.01                  │
│ σ_y = 276 ± 8 MPa     H = 1.2 ± 0.3 GPa               │
│                                                          │
│ [ Subir datos de ensayo (.csv) ]                        │
│ → Ajuste automático: R² = 0.998 (Excelente)            │
│                                                          │
│ Incertidumbre:                                          │
│ [☑] Propagar a resultados   Muestras: [100]            │
│ Nivel confianza: [95%]                                  │
│                                                          │
│ [ Guardar ] [ Asignar a nodo geométrico ]              │
└──────────────────────────────────────────────────────────┘
```

`UncertaintyBand.jsx` muestra en VTK.js una visualización de doble campo: valor medio + semitransparente para la desviación estándar.

---

## FASE 7 — Trazabilidad y Reproducibilidad (semana 15-18)

### 7.1 Hash de simulación (`app/design/services/traceability/hasher.py`)

```python
import hashlib, json

class SimulationHasher:
    """
    SHA-256 de todos los inputs que determinan el resultado.
    Garantiza reproducibilidad: mismo hash = mismo resultado numérico.
    """
    def compute_hash(self, graph_id, solver_config, mesh_stats) -> str:
        payload = {
            'graph_state': self._serialize_graph(graph_id),
            'solver': {
                'type': solver_config.type,
                'tol': solver_config.tol,
                'max_iter': solver_config.max_iter,
                'nonlinear_method': solver_config.nl_method,
            },
            'mesh': {
                'n_nodes': mesh_stats.n_nodes,
                'n_elements': mesh_stats.n_elements,
                'element_types': mesh_stats.element_types,
                'mesh_hash': mesh_stats.geometry_hash,
            },
            'python_versions': {
                'numpy': np.__version__,
                'scipy': scipy.__version__,
            },
            'constitutive_models': self._serialize_constitutive(graph_id),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def check_reproducible(self, hash1, hash2) -> bool:
        return hash1 == hash2
```

### 7.2 Modelo de simulación con versionado (`app/design/models/simulation.py`)

```python
class SimulationRun(BaseModel):
    __tablename__ = 'simulation_runs'

    graph_id        = Column(UUID, ForeignKey('design_graphs.id'))
    graph_version   = Column(Integer)
    hash            = Column(String(64), unique=True)
    status          = Column(String(50))   # queued|running|done|failed
    tier            = Column(Integer)
    physics         = Column(JSONB)        # list of physics activated
    solver_config   = Column(JSONB)
    mesh_stats      = Column(JSONB)
    result_ref      = Column(String(1000)) # path .h5

    wall_time       = Column(Float)        # segundos
    n_iterations    = Column(Integer)
    final_residual  = Column(Float)
    converged       = Column(Boolean)
    convergence_log = Column(JSONB)        # [(iter, residual, time), ...]

    # Trazabilidad
    parent_run_id   = Column(UUID, ForeignKey('simulation_runs.id'), nullable=True)
    parameter_delta = Column(JSONB)        # qué cambió respecto al padre
```

### 7.3 Reportes automáticos (`app/design/services/traceability/reporter.py`)

```python
class AutoReporter:
    def generate_jsonld(self, run: SimulationRun) -> dict:
        """
        JSON-LD compatible con schema.org/Dataset para indexación semántica.
        """
        return {
            "@context": "https://schema.org",
            "@type": "Dataset",
            "identifier": run.hash,
            "name": f"CAE Simulation {run.hash[:12]}",
            "dateCreated": run.created_at.isoformat(),
            "description": "...",
            "hasPart": [
                {"@type": "PropertyValue", "name": "maxVonMises", "value": ...},
                {"@type": "PropertyValue", "name": "maxDisplacement", "value": ...},
            ],
            "softwareVersion": {...},
            "variableMeasured": [...],
        }

    def generate_markdown(self, run: SimulationRun) -> str:
        """
        Reporte legible: inputs, resultados clave, warnings, hash, reproducibility note.
        """
```

### 7.4 UI — `SimHistory.jsx`

```
┌──────────────────────────────────────────────────────────────────────┐
│ Historial de Simulaciones                                          │
│                                                                      │
│  # │ Hash     │ Fecha     │ Tier │ Física     │ Estado │ Acción    │
│  1 │ a3f7c2.. │ 2026-05-30│  1   │ Estructural│ ✓ ok   │ [Ver][Re] │
│  2 │ 8b12e9.. │ 2026-05-30│  1   │ Termo+Est  │ ✓ ok   │ [Ver][Re] │
│  3 │ d44a01.. │ 2026-05-31│  2   │ Estructural│ ✗ div  │ [Ver]     │
│                                                                      │
│  [Re] = Reproducir exactamente esta simulación                      │
└──────────────────────────────────────────────────────────────────────┘
```

`ReproduceDialog.jsx` carga el hash, valida que el entorno de software coincida y lanza exactamente la misma simulación.

---

## FASE 8 — Validación Continua (semana 17-21)

### 8.1 Modelos de base de datos (`app/design/models/validation.py`)

```python
class ExperimentalRecord(BaseModel):
    __tablename__ = 'experimental_records'

    graph_id        = Column(UUID, ForeignKey('design_graphs.id'))
    material_id     = Column(UUID, ForeignKey('material_models.id'), nullable=True)
    test_type       = Column(String(100))  # tensile, fatigue, thermal, vibration, etc.
    conditions      = Column(JSONB)        # temperatura, velocidad de deformación, etc.
    raw_data        = Column(JSONB)        # datos crudos del ensayo
    scalar_summary  = Column(JSONB)        # E, σ_y, σ_uts, etc.
    file_ref        = Column(String(1000)) # CSV/Excel original
    source          = Column(String(255))  # "usuario" | "literatura" | "base_interna"


class SimExperimentCorrelation(BaseModel):
    __tablename__ = 'sim_experiment_correlations'

    run_id             = Column(UUID, ForeignKey('simulation_runs.id'))
    experiment_id      = Column(UUID, ForeignKey('experimental_records.id'))
    correlation_r2     = Column(Float)   # R² entre campo simulado e interpolado experimental
    max_relative_error = Column(Float)
    field_compared     = Column(String(100))  # "displacement", "strain", "stress"
    confidence_factor  = Column(Float)        # 0-1, usado para futuras recomendaciones
```

### 8.2 Servicio de correlación (`app/design/services/validation/correlator.py`)

```python
class SimulationCorrelator:
    """
    Antes de simular, busca en la base de datos casos similares.
    Similitud basada en:
    - Tipo de material (embedding semántico)
    - Tipo de elemento y carga
    - Rango de DOF

    Devuelve un "factor de confianza" basado en el historial:
    0.0 → sin datos históricos
    1.0 → caso idéntico con correlación perfecta
    """
    def find_similar_runs(self, graph_id, top_k=5) -> list[dict]
    def compute_confidence_factor(self, similar_runs) -> float
    def recommend_validation_test(self, graph_id) -> str   # tipo de ensayo recomendado
```

### 8.3 Recalibrador (`app/design/services/validation/recalibrator.py`)

```python
class ModelRecalibrator:
    """
    Después de que el usuario sube datos experimentales post-simulación,
    recalibra automáticamente el modelo constitutivo.
    """
    def recalibrate(self, material_id, experiment_id) -> dict:
        # 1. Carga el modelo constitutivo actual
        # 2. Carga los datos experimentales
        # 3. Minimiza el error con scipy.optimize
        # 4. Guarda los nuevos parámetros + δ (cuánto cambió)
        # 5. Actualiza SimExperimentCorrelation
        ...
```

### 8.4 API

```
POST /api/design/validation/experiments           → subir datos experimentales
GET  /api/design/validation/experiments           → listar
POST /api/design/validation/<graph_id>/correlate  → correlacionar run + experimento
GET  /api/design/validation/<graph_id>/confidence → factor de confianza antes de simular
POST /api/design/validation/<graph_id>/recalibrate → recalibrar modelo con datos nuevos
```

### 8.5 UI — `ExperimentUpload.jsx` + `CorrelationView.jsx`

```
ExperimentUpload:
  ┌──────────────────────────────────────────────────┐
  │ Subir datos experimentales                       │
  │                                                  │
  │ Tipo de ensayo: [Tracción ▼]                    │
  │ Material:       [Aluminio 6061-T6 ▼]            │
  │ Condiciones: T = [25] °C  v_ε = [0.001] s⁻¹   │
  │                                                  │
  │ [ Arrastrar CSV aquí o hacer click ]            │
  │                                                  │
  │ Columnas detectadas: ε (col A), σ (col B)       │
  │ Puntos: 150  Rango ε: 0 – 0.18                 │
  │                                                  │
  │ [ SUBIR Y CALIBRAR ]                            │
  └──────────────────────────────────────────────────┘

CorrelationView:
  Gráfica doble: simulación (línea) vs experimento (puntos)
  Métrica R² prominente
  Lista de casos similares con factor de confianza
```

---

## FASE 9 — UI Final: Nuevo Paradigma (semana 18-24, paralelo con fases anteriores)

### 9.1 Refactorización de `App.jsx`

El layout pasa de "modos" a "espacio de trabajo por proyecto":

```
┌────────────────────────────────────────────────────────────────────────┐
│ [≡] CAE Lab  ·  Project: Bracket_v3           [STEP][DESIGN][RESULTS] │
└────────────────────────────────────────────────────────────────────────┘
│ LEFT PANEL │                    CENTRAL VIEWPORT                       │
│            │                                                            │
│ Proyectos  │   [DESIGN MODE]                                           │
│ ──────────│   ┌───────────────────────────────────────────────────┐   │
│ Concept A  │   │                                                   │   │
│ Concept B  │   │     Graph Editor (ReactFlow)                      │   │
│ ▶ Bracket  │   │                                                   │   │
│   ├─ v1   │   │   [MATERIAL]──FUNCTIONAL──▶[GEOMETRY]             │   │
│   ├─ v2   │   │       │                        │                  │   │
│   └─▶v3  │   │   CONSTRAINS                PRODUCED_BY           │   │
│            │   │       │                        │                  │   │
│ [+ Nuevo] │   │   [BC/LOAD]────DEPENDS_ON──▶[RESULT]             │   │
│            │   │                                                   │   │
│            │   └───────────────────────────────────────────────────┘   │
│            │                                                            │
│ RIGHT PANEL│   [RESULTS MODE]                                          │
│ (context)  │   CAEViewer (VTK.js) ← resultado de la simulación         │
│            │                                                            │
│ Properties │   [STEP MODE]                                             │
│ Solver     │   StepViewer3D (Three.js) ← importar geometría al grafo  │
│ Material   │                                                            │
│ History    │                                                            │
│ Validation │                                                            │
└────────────────────────────────────────────────────────────────────────┘
```

### 9.2 `TopBar.jsx` — nuevo diseño

Tres secciones:
1. Modo de trabajo: `Design` | `STEP Viewer` | `Results`
2. Contexto de proyecto: nombre + versión + estado del grafo
3. Acciones contextuales: `[ Validar grafo ]` `[ Simular ]` `[ Historial ]` `[ Exportar ]`

### 9.3 `designStore.js` — nuevo Zustand store

```javascript
const useDesignStore = create((set, get) => ({
  // Grafo activo
  activeGraphId: null,
  graphData: null,           // { nodes: [], edges: [] } formato ReactFlow
  selectedNodeId: null,
  selectedEdgeId: null,

  // Estado de física
  activePhysics: ['structural'],

  // Estado de solver
  activeRunId: null,
  runStatus: 'idle',         // idle|queued|running|done|failed
  convergenceLog: [],

  // ROM
  activeROMId: null,
  romParams: {},

  // Actions
  loadGraph: async (graphId) => { ... },
  addNode: async (type, label, position) => { ... },
  addEdge: async (sourceId, targetId, edgeType) => { ... },
  validateGraph: async () => { ... },
  runSimulation: async (config) => { ... },
  evaluateROM: debounce(async (params) => { ... }, 16),
}));
```

### 9.4 Sistema de notificaciones de grafo

En el editor, overlay contextual no intrusivo:

```
⚠ El nodo [LOAD: Fuerza_z] no está conectado a ningún nodo GEOMETRY
⚠ No hay nodo MATERIAL asignado a [GEOMETRY: Soporte]
✓ Grafo válido para física: Estructural 3D
✓ Tier estimado: 1 (< 100K DOF)
ℹ Factor de confianza: 0.72 (3 simulaciones similares encontradas)
```

---

## Secuencia de implementación y dependencias entre fases

```
Semana  1-2:   FASE 0  → Infraestructura, dependencias, estructura carpetas
Semana  2-4:   FASE 1  → Grafo de diseño (DB + API + GraphEditor básico)
Semana  3-8:   FASE 2  → Kernel FEM (paralelo con FASE 1 desde semana 3)
Semana  5-9:   FASE 3  → Mallado adaptativo (requiere FASE 2 base)
Semana  7-12:  FASE 4  → Optimización topológica (requiere FASE 2 + FASE 3)
Semana 10-15:  FASE 5  → ROM (requiere FASE 2 operativa + WebSocket)
Semana 12-17:  FASE 6  → Materiales activos (paralelo con FASE 5)
Semana 15-18:  FASE 7  → Trazabilidad (puede ir en paralelo con cualquier fase)
Semana 17-21:  FASE 8  → Validación (requiere FASE 6 + FASE 7)
Semana 18-24:  FASE 9  → UI final (integración continua desde FASE 1)
```

---

## Hitos verificables por fase

| Fase | Hito de verificación |
|------|---------------------|
| FASE 0 | `python run.py` arranca sin errores con los 7 nuevos blueprints registrados |
| FASE 1 | Crear un grafo con 3 nodos y 2 aristas vía API + verlo en GraphEditor |
| FASE 2 | Simular una viga en voladizo T4 con carga puntual y obtener desplazamiento correcto comparado con solución analítica (±1%) |
| FASE 3 | La viga anterior con refinamiento adaptativo converge en ≤ 3 ciclos |
| FASE 4 | Optimización topológica de una placa con agujero produce resultado tipo "puente" (forma clásica de validación SIMP) |
| FASE 5 | Mover el slider de carga en ROMExplorer actualiza el campo en < 100ms |
| FASE 6 | Ajustar un modelo elastoplástico a datos CSV de ensayo tracción con R² > 0.99 |
| FASE 7 | Dos ejecuciones con los mismos parámetros producen el mismo hash SHA-256 |
| FASE 8 | Subir datos de un ensayo de tracción simple recalibra el módulo E con error < 2% |
| FASE 9 | Flujo completo conceptual → grafo → simulación → resultado en UI unificada |

---

## Criterios de límite de modelo aplicados en código

En `app/design/services/fem/solver.py`, antes de cualquier ejecución:

```python
TIER_LIMITS = {
    0: {'max_dof': 30_000,    'max_nodes': 5_000,     'max_elements': 20_000},
    1: {'max_dof': 600_000,   'max_nodes': 100_000,   'max_elements': 400_000},
    2: {'max_dof': 6_000_000, 'max_nodes': 1_000_000, 'max_elements': 4_000_000},
    3: {'max_dof': 60_000_000,'max_nodes': 10_000_000,'max_elements': 40_000_000},
}

def check_tier_limits(n_nodes, n_elements, n_dof, declared_tier):
    limits = TIER_LIMITS[declared_tier]
    violations = []
    if n_dof > limits['max_dof']:
        violations.append(
            f"DOF {n_dof:,} excede límite Tier {declared_tier}: {limits['max_dof']:,}"
        )
    if n_nodes > limits['max_nodes']:
        violations.append(
            f"Nodos {n_nodes:,} excede límite Tier {declared_tier}: {limits['max_nodes']:,}"
        )
    if n_elements > limits['max_elements']:
        violations.append(
            f"Elementos {n_elements:,} excede límite Tier {declared_tier}: {limits['max_elements']:,}"
        )
    if violations:
        raise TierLimitExceeded(violations, suggested_tier=declared_tier + 1)
```

En frontend, `SolverPanel.jsx` muestra el tier estimado antes de lanzar y bloquea el botón si el modelo excede el tier seleccionado por el usuario.

---

## Resumen de carencias que resuelve cada fase

| Carencia original | Fase que la resuelve |
|-------------------|---------------------|
| CAE posterior a CAD — simulación desacoplada del diseño conceptual | FASE 1 (grafo) + FASE 4 (topología integrada) |
| Multifísica débilmente acoplada | FASE 2 (kernel FEM unificado con DOF mixtos) |
| Mallado manual independiente | FASE 3 (mallado adaptativo automático ZZ) |
| Linealidad por defecto con convergencia frágil | FASE 2 §2.5 (Newton-Raphson + Arc-length por defecto) |
| Simulación batch sin exploración | FASE 5 (ROM + explorador interactivo < 100ms) |
| Materiales como tabla de valores fijos | FASE 6 (modelos paramétricos + incertidumbre propagada) |
| No trazabilidad ni reproducibilidad | FASE 7 (hash SHA-256 + versionado + JSON-LD) |
| Sin aprendizaje de ensayos experimentales | FASE 8 (validación continua + recalibración automática) |
