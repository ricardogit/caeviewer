# CAE Viewer — Estado actual y workflow detallado

> Fecha: 2026-05-20  
> Stack: Flask + pythonocc-core + GMSH + meshio · React + VTK.js + MUI · PostgreSQL · Docker

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Modo STEP Viewer](#2-modo-step-viewer)
3. [Modo CAE / FEA](#3-modo-cae--fea)
4. [Pipeline STEP → Malla → Solver](#4-pipeline-step--malla--solver)
5. [Visualización de campos de resultados](#5-visualización-de-campos-de-resultados)
6. [Análisis IA de hotspots](#6-análisis-ia-de-hotspots)
7. [Exportación](#7-exportación)
8. [Arquitectura técnica](#8-arquitectura-técnica)
9. [Formatos soportados](#9-formatos-soportados)
10. [Limitaciones conocidas y pendientes](#10-limitaciones-conocidas-y-pendientes)

---

## 1. Arquitectura general

La aplicación tiene **dos modos** que se conmutan con el botón en la barra superior:

```
┌──────────────────────────────────────────────────────────────────┐
│  Top Bar: [☰ menú]  [nombre archivo / malla]  [toggle CAE/STEP]  │
├──────────────┬───────────────────────────────────────────────────┤
│              │                                                    │
│  Panel izq.  │              Visor 3D principal                   │
│  (300 px)    │         (VTK.js / Three.js / pythonocc)           │
│              │                                                    │
│  - Modo STEP │  Panel de control flotante (derecha, 270 px)      │
│    FileList  │  Drawers opcionales:                               │
│              │    Feature · EntityTree · PMI                      │
│  - Modo CAE  │    Measurement · SectionCut · Markup               │
│    CAEFileList│                                                   │
└──────────────┴───────────────────────────────────────────────────┘
```

**Backend** — Flask + Gunicorn (2 workers, timeout 1200 s):

| Blueprint | Prefijo | Responsabilidad |
|-----------|---------|-----------------|
| `files_api` | `/api/step-view` | Gestión de archivos STEP |
| `geometry_api` | `/api/step-view/geometry` | Geometría B-Rep (OCC) |
| `feature_api` | `/api/step-view/feature` | Detección de features de fabricación |
| `measurement_api` | `/api/step-view/measurement` | Mediciones 3D |
| `pmi_api` | `/api/step-view/pmi` | Anotaciones PMI |
| `markup_api` | `/api/step-view/markup` | Markups sobre la vista |
| `export_api` | `/api/step-view/export` | Exportación STL/IGES/GLB |
| `comparison_api` | `/api/step-view/comparison` | Comparación de geometrías |
| `cae_api` | `/api/cae` | Gestión de mallas FEA |
| `cae_mesh_from_step` | `/api/cae` | Generación de malla desde STEP |
| `ai_routes` | `/api/cae/ai` | Análisis IA de campos |

---

## 2. Modo STEP Viewer

### 2.1 Carga de archivos STEP

1. Clic en **"Cargar archivo"** en el panel izquierdo → seleccionar `.step` / `.stp`.
2. El backend (pythonocc-core) parsea el archivo:
   - Extrae entidades B-Rep (sólidos, caras, aristas, vértices).
   - Tesela la geometría para visualización WebGL (malla de triángulos ligera).
   - Detecta features de fabricación (agujeros, pockets, chaflanes).
   - Extrae anotaciones PMI si existen en el STEP.
   - Almacena la malla teselada y metadatos en PostgreSQL.
3. La pieza aparece en el visor 3D con navegación orbital (rotar, zoom, pan).

### 2.2 Navegación 3D

- **Rotar**: clic izquierdo + arrastrar.
- **Pan**: clic central o `Shift` + arrastrar.
- **Zoom**: rueda del ratón.
- **Selección de entidad**: clic sobre una cara/arista → abre el panel de detalles.

### 2.3 Árbol de entidades (Entity Tree)

Botón `AccountTree` → drawer lateral derecho.

Muestra la jerarquía del ensamblaje:
- Productos / subensamblajes.
- Sólidos (BREP_SHAPE).
- Caras, aristas, vértices individuales.

Seleccionando una entidad se resalta en el visor y abre `EntityDetails` con:
- Tipo, ID, propiedades geométricas (área, volumen, longitud).
- Entidades relacionadas con hipervínculos de navegación.

### 2.4 Features de fabricación

Botón `Build` → drawer `FeaturePanel`.

Detecta y clasifica automáticamente:
- **HOLE** — agujeros cilíndricos (diámetro, profundidad, tipo: pasante/ciego).
- **POCKET** — cajeras rectangulares o de forma libre.
- **CHAMFER** / **FILLET** — chaflanes y redondeos.
- **BOSS** / **RIB** — salientes y nervios.

Dos métodos de extracción:
- `entity` (rápido): análisis topológico de entidades STEP en BD.
- `geometric` (preciso): análisis B-Rep con pythonocc (requiere OCC disponible).

### 2.5 Anotaciones PMI

Botón `Straighten` → drawer `PMIPanel`.

Lee las anotaciones de tolerancias y dimensiones embebidas en el STEP (GD&T):
- Cotas lineales y angulares.
- Tolerancias geométricas (planitud, circularidad, etc.).
- Notas de texto.

Las anotaciones se renderizan como etiquetas 3D flotantes sobre la geometría.

### 2.6 Herramientas de medición

Botón `SquareFoot` → drawer `MeasurementTools`.

Permite crear mediciones interactivas:
- **Distancia** entre dos puntos (clic "Pick from 3D" → selecciona punto en el visor).
- **Ángulo** entre dos vectores definidos por tres puntos.

Las mediciones se persisten en BD y se renderizan como anotaciones 3D con líneas y etiquetas de valor.

### 2.7 Corte de sección

Botón `ContentCut` → drawer `SectionCutPanel`.

Define un plano de corte (normal X/Y/Z, posición) que actúa sobre toda la geometría visible. Se puede invertir el lado recortado.

### 2.8 Markup / Anotaciones libres

Botón `Draw` → drawer `MarkupPanel`.

Dibuja sobre el canvas del visor 3D:
- **Herramientas**: lápiz libre, línea, rectángulo, círculo, texto.
- Ajuste de color y grosor de trazo.
- Los trazos se almacenan por archivo en BD y se pueden borrar.

### 2.9 Comparación y exportación

Desde el menú de exportación:

| Formato | Notas |
|---------|-------|
| **STL** | ASCII o binario; parámetros de deflexión controlables |
| **IGES** | Intercambio B-Rep neutro |
| **GLB / glTF** | 3D web, texturas opcionales |
| **Comparación B-Rep** | Diferencias geométricas entre dos archivos STEP |

---

## 3. Modo CAE / FEA

### 3.1 Panel de mallas (CAEFileList)

El panel izquierdo muestra todas las mallas FEA almacenadas. Para cada malla se indica:
- Nombre del archivo.
- Número de nodos y elementos.
- Formato (VTU, INP, MSH…).
- **Solver recomendado principal** (chip verde/gris) — calculado automáticamente según los tipos de elemento de la malla.

#### Acciones disponibles
- **Cargar malla FEA** — subir un archivo de malla directamente.
- **Generar malla desde STEP** — seleccionar un archivo STEP ya cargado y generar la malla con GMSH.
- **Eliminar** malla (con confirmación).
- **Actualizar** la lista.

### 3.2 Panel de control del visor (CAEViewer)

Flotante sobre el visor, esquina superior derecha. Contiene todas las herramientas de análisis:

#### Información de la malla
- Nombre del archivo.
- Conteo de nodos y elementos.
- Tipos de elementos presentes, p.ej. `hexahedron(76252) · wedge(1204)`.

#### Solvers recomendados (sección desplegable)
Muestra hasta 6 solvers con nivel de compatibilidad automáticamente calculado:

| Color chip | Nivel | Significado |
|-----------|-------|-------------|
| 🟢 Verde | excellent | El tipo de elemento es nativo/óptimo del solver |
| 🔵 Azul | good | Compatible, calidad aceptable |
| ⬜ Gris | compatible | Funciona pero no es el punto fuerte |

Hover sobre cada chip muestra descripción y porcentaje de confianza.

Solvers cubiertos: OpenFOAM · CalculiX · Abaqus · Code_Aster · FEniCS · Elmer · Star-CCM+ · Fluent · LS-DYNA · Kratos.

#### Métricas de calidad de malla
Calculadas automáticamente al cargar (sampling de hasta 20 k elementos para mallas grandes):

| Métrica | Umbral alerta |
|---------|---------------|
| A.R. medio (max_arista / min_arista) | > 5 → ámbar |
| A.R. P95 | > 10 → ámbar |
| Elem. deficientes (%) | > 5% → ámbar |

#### Campo de resultados
- Selector de campo disponible en la malla (nodal o elemental).
- Selector de colormap: `viridis` · `rainbow` · `coolwarm` · `jet` · `grayscale`.
- Barra de colores con valor mín/máx.
- Para campos vectoriales: visualiza magnitud euclídea, indica "magnitud vectorial".

#### Estadísticas del campo (desplegable)
- Histograma en miniatura (24 bins).
- Slider de umbral (threshold) para recortar el rango de color activo sin recargar datos.
- Tabla estadística: Min, Max, Media, Desv. estándar, P5, P25, Mediana, P75, P95.

#### Deformación (warp)
Solo disponible para campos vectoriales (tipicamente desplazamiento).
- Slider 0 → 1.
- A escala 1, el desplazamiento máximo equivale a ~20% de la diagonal de la caja envolvente.
- La geometría de la superficie se reconstruye en tiempo real con las coordenadas desplazadas.

#### Corte de sección
- Toggle activo/inactivo.
- Selección de eje: X / Y / Z.
- Slider de posición a lo largo del eje seleccionado.
- Botón de inversión del lado recortado.
- Implementado como plano de clipping en el mapper VTK.js (no recorta la geometría real).

#### Pasos de tiempo (animación)
Para mallas con resultados multi-step (Exodus II, XDMF, MED):
- Texto indicando paso actual y tiempo si está disponible.
- Controles: primer paso · play/pause · último paso.
- Slider de paso manual.
- Play automático: avanza 1 paso cada 300 ms; se detiene al llegar al último.

#### Análisis IA de hotspots
Botón "Analizar IA" (requiere campo cargado).
- Detecta nodos con valor ≥ 90% del máximo global.
- Clasifica el riesgo estructural (low / medium / high).
- Muestra: conteo de hotspots, % de nodos críticos, recomendación textual.
- Renderiza los hotspots como puntos rojos superpuestos sobre la superficie.

#### Controles de vista
- `GridOn` — activa/desactiva aristas de la malla (wireframe overlay).
- `GpsFixed` — modo pick: al hacer clic sobre el visor selecciona el nodo más cercano al rayo de cámara y muestra índice, coordenadas XYZ y valor del campo.

---

## 4. Pipeline STEP → Malla → Solver

### 4.1 Diálogo de generación (MeshFromStepDialog)

Se abre desde:
- **CAEFileList** → botón "Generar malla desde STEP" (seleccionar el STEP en una lista).
- **Modo STEP Viewer** → botón `Hub` con el archivo ya seleccionado (flujo directo).

Al finalizar, el botón "Abrir en CAEViewer" cambia automáticamente al modo CAE con la malla recién generada activa.

#### Paso 1 — Tipo de elemento

| Tipo | Descripción | Calidad num. | Facilidad auto | Uso típico |
|------|-------------|:---:|:---:|---------|
| **TET4** | Tetraédrico lineal | ★★☆☆☆ | ★★★★★ | FEA general, geometría compleja, biomédica |
| **TET10** | Tetraédrico cuadrático (10 nodos) | ★★★★☆ | ★★★★☆ | FEA alta precisión, gradientes curvos |
| **HEX+TET** | Hexaédrico dominante + residual tet/wedge | ★★★☆☆ | ★★★☆☆ | CFD industrial, balance calidad/tiempo |
| **HEX8** | Hexaédrico puro (subdivisión AllHex) | ★★★★★ | ★★☆☆☆ | Crash, turbomáquinas, problemas de contacto |
| **PRISM** | Capas límite prismáticas + TET interior | ★★★★★ | ★★★☆☆ | CFD turbulento (resolución capa límite) |

Hovering sobre cada card muestra descripción detallada y solvers compatibles.

#### Paso 2 — Fineza de malla

| Nivel | Etiqueta | Elementos aprox. |
|-------|----------|-----------------|
| 1 | Muy gruesa | 1 k – 5 k |
| 2 | Gruesa | 5 k – 20 k |
| 3 | Media | 20 k – 100 k |
| 4 | Fina | 100 k – 500 k |
| 5 | Muy fina | 500 k+ (lento) |

Fórmula: `mesh_size = diagonal_bbox / (refinement × 10)`.

#### Paso 3 — Algoritmo 3D

| Algoritmo | Velocidad | Calidad | Compatible con |
|-----------|-----------|---------|----------------|
| **HXT** | ★★★★★ (paralelo) | ★★★☆☆ | TET4, híbrido, HEX8 |
| **Delaunay** | ★★★★☆ | ★★★☆☆ | TET4, híbrido, HEX8 |
| **Frontal** | ★★☆☆☆ | ★★★★★ | TET4, TET10, híbrido, PRISM |

#### Paso 4 — Optimización post-generación
- **Activada** (por defecto):
  - TET: optimizador Netgen (mejora ángulos diedros).
  - HEX/Híbrido: Relocate3D + UntangleMeshGeometry.
- **Desactivada**: más rápido, calidad menor.

#### Proceso interno de generación

```
STEP file (disco)
      │
      ▼
  GMSH  ─── mutex de proceso (no thread-safe)
    ├── gmsh.open()
    ├── bounding_box → mesh_size
    ├── Opciones por tipo (tetra / hexa / hybrid)
    │     hexa:   RecombineAll + Frontal-Hex + SubdivisionAlgorithm=2
    │     hybrid: RecombineAll + Frontal-Hex (sin subdivisión)
    │     tetra:  Algorithm3D según elección
    ├── gmsh.model.mesh.generate(3)
    ├── Optimización post-generación (Netgen / Relocate3D)
    └── Exportar .msh formato 2.2 (IDs contiguos 1-based)
      │
      ▼  (fuera del mutex)
  meshio
    ├── Leer .msh2
    ├── Filtrar solo elementos sólidos (tetra/hex/wedge/pyramid)
    ├── Squeeze: eliminar nodos no referenciados, reindexar 0-based
    └── Exportar .vtu
      │
      ▼
  parse_mesh()
    ├── Nodos, elementos, bounding box
    ├── Sets (node_sets, element_sets)
    ├── Campos (node_fields, element_fields)
    ├── Extracción de triángulos de superficie
    │     - Si hay elementos superficie explícitos → usar directamente
    │     - Si no → caras de frontera (count=1) de tet/hex/wedge/pyramid
    ├── Corrección de normales salientes (_ensure_outward_normals)
    │     check centroide: dot(normal, face_center - centroid) > 0
    ├── compute_mesh_quality(): aspect ratio tet/hex/wedge
    └── recommend_solvers(): scoring 10 solvers vs tipos de elemento
      │
      ▼
  CAEMesh (PostgreSQL) + .vtu (disco)
      │
      ▼
  "Abrir en CAEViewer" → modo CAE, malla seleccionada
```

**Timeout configurado**: 1200 s (20 min). Mallas HEX8 complejas pueden tardar 5–10 min.

### 4.2 Recomendación de solvers

El sistema puntúa cada solver en base a los tipos de elemento presentes:

```
score = (n_excellent × 3 + n_good × 2 - n_poor × 2) / (n_tipos × 3)
```

| Score | Nivel |
|-------|-------|
| ≥ 0.80 | excellent |
| ≥ 0.50 | good |
| > 0.10 | compatible |

Ejemplo para malla puramente hexaédrica:
- OpenFOAM → excellent (hex es nativo)
- CalculiX → excellent (C3D8 = hexahedron soportado)
- FEniCS → good (hex soportado pero tet es el nativo)

### 4.3 Carga directa de malla FEA

Sin necesidad de STEP. Soporta cualquier formato leído por meshio (ver sección 9).

```
Archivo FEA (upload) → parse_mesh() → CAEMesh (BD) + archivo original (disco)
```

Los campos de resultados embebidos en el archivo (p.ej. un `.vtu` de resultado de solver) se extraen automáticamente y quedan disponibles en el selector de campos.

---

## 5. Visualización de campos de resultados

### 5.1 Tipos de campo soportados

| Tipo | Descripción | Ejemplo |
|------|-------------|---------|
| Nodal escalar | Un float por nodo | Temperatura, presión estática |
| Nodal vectorial | [vx, vy, vz] por nodo | Desplazamiento, velocidad |
| Elemental escalar | Un float por elemento | Esfuerzo equivalente Von Mises |

Para campos vectoriales se colorea por **magnitud** (norma euclidiana).

### 5.2 Multi-step

Para archivos con múltiples instantes de tiempo (Exodus II, XDMF, MED):
- Los pasos se descubren al cargar la malla.
- Cada paso se solicita individualmente al backend con `?step=N`.
- La animación avanza cargando un paso nuevo cada 300 ms.

### 5.3 Warp (deformación amplificada)

Solo para campos vectoriales (desplazamiento `U`):
- Reemplaza las coordenadas de superficie: `x' = x + U·scale`.
- `scale = warp_slider × (diagonal_bbox / (U_max × 5))`.
- A slider=1 el desplazamiento máximo visible es ~20% del tamaño del modelo.

---

## 6. Análisis IA de hotspots

**Objetivo**: identificar zonas de concentración de esfuerzo, temperatura o velocidad sin necesidad de un solver externo.

**Algoritmo**:
1. Para cada nodo: calcular magnitud (vectores) o tomar valor escalar absoluto.
2. Threshold = 0.90 × max_global.
3. Hotspots = nodos con valor ≥ threshold.
4. Clasificar riesgo por porcentaje de concentración:

| Concentración | Riesgo | Recomendación |
|---------------|--------|---------------|
| < 1% nodos | **low** | Carga eficiente, no se requieren cambios |
| 1–5% nodos | **medium** | Añadir filetes, redistribuir BC |
| > 5% nodos | **high** | Rediseño estructural necesario |

**Salida visual**: puntos rojos superpuestos sobre la superficie en las posiciones de los nodos hotspot (renderizados como esferas mediante `vtkActor` con `renderPointsAsSpheres`).

---

## 7. Exportación

### Desde modo STEP

| Formato | Descripción |
|---------|-------------|
| **STL** | ASCII o binario; deflexión lineal y angular controlables |
| **IGES** | B-Rep neutro para intercambio CAD |
| **GLB / glTF** | Visualización web 3D |
| **Comparación B-Rep** | Análisis de diferencias entre dos archivos STEP |

### Desde modo CAE

| Acción | Resultado |
|--------|-----------|
| Captura PNG (`CameraAlt`) | Imagen del render actual con resolución de pantalla |
| CSV (`TableChart`) | Coordenadas de todos los nodos + valor del campo activo |
| Descarga malla (`FileDownload`) | Archivo original (.vtu, .inp, .msh, etc.) |

---

## 8. Arquitectura técnica

### Backend

```
app/
├── __init__.py                    Flask factory, registro blueprints
├── extensions.py                  SQLAlchemy
├── models/
│   ├── part.py                    Part — archivos STEP cargados
│   └── step_storage.py            STEPFileHeader, STEPEntity
├── cae/
│   ├── models/mesh.py             CAEMesh, CAEField
│   ├── api/
│   │   ├── cae_routes.py          CRUD mallas + campos + caché
│   │   ├── mesh_from_step_routes.py  GMSH pipeline
│   │   └── ai_routes.py           hotspot detection
│   └── services/
│       ├── mesh_parser.py         meshio wrapper, surface extraction,
│       │                          outward normals, solvers, quality
│       └── step_mesher.py         GMSH → .vtu con squeeze/reindex
└── step_view_pro/backend/
    ├── step_processor.py          carga STEP (pythonocc)
    ├── geometry_processor.py      teseleado B-Rep → JSON
    ├── feature_extractor.py       features básica (topología)
    ├── advanced_feature_extractor.py  features (OCC B-Rep)
    ├── pmi_parser.py              anotaciones PMI
    ├── measurement_tools.py       distancia, ángulo
    ├── export_tools.py            STL, IGES, GLB
    └── comparison_tools.py        diff B-Rep
```

### Frontend

```
frontend/src/
├── App.jsx                    layout, toggle CAE/STEP, drawers
└── components/
    ├── TopBar.jsx             barra superior
    ├── FileList.jsx           lista STEP
    ├── CAEFileList.jsx        lista mallas FEA + solver badge
    ├── StepViewer3D.jsx       visor CAD (Three.js + OCC teseleado)
    ├── CAEViewer.jsx          visor FEA (VTK.js surface rendering)
    ├── MeshFromStepDialog.jsx wizard de generación de malla
    ├── EntityTree.jsx         árbol B-Rep
    ├── EntityDetails.jsx      propiedades de entidad
    ├── FeaturePanel.jsx       features de fabricación
    ├── PMIPanel.jsx           anotaciones GD&T
    ├── MeasurementTools.jsx   distancia/ángulo interactivos
    ├── SectionCutPanel.jsx    plano de corte STEP
    └── MarkupPanel.jsx        trazos libres
```

### Infraestructura Docker

```
Stage 1: node:18-alpine → npm build (React/Vite → /dist)
Stage 2: condaforge/miniforge3
  conda: python=3.11 + pythonocc-core=7.7.2
  pip:   meshio, numpy, gmsh, flask, gunicorn, sqlalchemy, …
  COPY app/ config/ run.py docker-entrypoint.sh
  COPY --from=stage1 /frontend/dist → /app/frontend/dist

Gunicorn: 2 workers · timeout 1200 s · sync worker class
Datos:    /app/data/uploads/  (mallas FEA + STEP files)
          /app/data/processed/
BD:       PostgreSQL (variable DATABASE_URL)
```

> **Importante**: el código Python está copiado en la imagen, no montado.  
> Todo cambio de código requiere `docker-compose up --build -d app`.

### Caché de mallas en memoria

```python
_mesh_cache: dict  # clave: (file_path, mtime)
_CACHE_CAPACITY = 8   # LRU simple — pop del primer elemento
```

Cada worker Gunicorn tiene su propia caché (sin compartir entre procesos, intencional). Con 2 workers la misma malla puede parsearse dos veces en el arranque.

---

## 9. Formatos soportados

### Mallas FEA (carga directa y generación)

| Extensión | Formato | Campos multi-step |
|-----------|---------|:-----------------:|
| `.vtu` | VTK Unstructured | ✓ |
| `.vtk` | VTK Legacy | — |
| `.pvtu` | VTK paralelo | ✓ |
| `.inp` | Abaqus Input | — |
| `.bdf` `.nas` `.dat` | Nastran | — |
| `.msh` | GMSH (MSH2 y MSH4) | — |
| `.med` | Salome MED | ✓ |
| `.exo` `.e` | Exodus II | ✓ |
| `.cdb` | ANSYS CDB | — |
| `.xdmf` `.xmf` | XDMF + HDF5 | ✓ |

### Geometría CAD

| Extensión | Estándar |
|-----------|---------|
| `.step` `.stp` | STEP AP203 / AP214 / AP242 |

### Exportación disponible

| Formato | Desde |
|---------|-------|
| `.stl` | STEP Viewer |
| `.iges` | STEP Viewer |
| `.glb` | STEP Viewer |
| `.png` | CAE Viewer (screenshot render) |
| `.csv` | CAE Viewer (nodos + campo activo) |
| Malla original | CAE Viewer (descarga del archivo subido) |

---

## 10. Limitaciones conocidas y pendientes

### Limitaciones actuales

| Área | Descripción |
|------|-------------|
| Normales outward | Check basado en centroide global: correcto para formas convexas. En geometrías muy cóncavas (toroides, perfiles en L/C) puede haber normales inconsistentes residuales. |
| Generación HEX8 | Puede tardar > 5 min para geometrías complejas (SubdivisionAlgorithm=2 multiplica el número de elementos × 4). |
| Caché multi-worker | Los 2 workers Gunicorn tienen cachés independientes; una malla puede parsearse dos veces tras un restart. |
| Pick mode (nodo) | Búsqueda O(n) por rayo; lento en mallas > 200 k nodos (sin BVH). |
| Campos elementales | Se visualizan como valor constante por elemento, no interpolado a nodos. |
| PMI | Solo lectura de anotaciones embebidas en STEP; no escritura ni edición. |
| Comparación STEP | Funciona sobre malla teselada, no B-Rep exacto. |

### Próximos pasos sugeridos

- [ ] Exportar malla al formato nativo del solver recomendado (`.inp` para CalculiX, `case/` para OpenFOAM, `.bdf` para Nastran).
- [ ] Definir condiciones de contorno (BC) visualmente: seleccionar caras/nodos y asignar restricciones o cargas.
- [ ] BVH / KD-tree para pick mode en mallas grandes.
- [ ] Interpolación de campos elementales a nodos (suavizado de discontinuidades).
- [ ] Soporte de mallas polyhedral nativas (OpenFOAM `polyMesh`).
- [ ] Comparación deformada vs. indeformada (overlay de dos mallas del mismo modelo).
- [ ] Exportación de imagen PNG con escala de colores embebida y metadatos del campo.
- [ ] Integración directa con CalculiX: enviar malla + BC → recibir resultados `.frd` → cargar automáticamente en el visor.
