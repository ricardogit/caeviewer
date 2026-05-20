# CAE Viewer — Estado actual y hoja de ruta

## ¿Qué es?

Visor de mallas FEA (Finite Element Analysis) integrado en el sistema CAPP.
Permite cargar, visualizar e inspeccionar resultados de simulaciones estructurales
directamente en el navegador, sin software adicional.

Stack: Flask + PostgreSQL (backend) · React + vtk.js 28 (frontend) · meshio + GMSH (procesamiento).

Desplegado en: `http://72.62.87.215/cae/step-view/` (VPS Hostinger, puerto 8080, gunicorn + nginx).

---

## Formatos de malla soportados

| Formato | Extensión |
|---------|-----------|
| VTK / ParaView | `.vtu` `.vtk` `.pvtu` |
| Abaqus | `.inp` |
| Nastran / ANSYS | `.bdf` `.nas` `.dat` |
| GMSH | `.msh` |
| Salome MED | `.med` |
| Exodus II | `.exo` `.e` |
| ANSYS CDB | `.cdb` |
| XDMF | `.xdmf` `.xmf` |

---

## Funcionalidades implementadas

### Gestión de mallas
- Subir archivos FEA directamente (drag & drop o selector)
- Listar mallas almacenadas con conteo de nodos y elementos
- Eliminar mallas (con confirmación)
- **Generar malla desde STEP**: selecciona un archivo STEP ya cargado → GMSH produce una malla tetraédrica `.vtu` con control de refinamiento (1–5) y algoritmo (Delaunay / Frontal / HXT)

### Visualización 3D (vtk.js)
- Renderizado WebGL de la superficie de la malla (triángulos de contorno)
- Cámara orbital trackball (rotar, zoom, pan)
- Coloreado por campo escalar o vectorial con 5 colormaps: `viridis`, `rainbow`, `jet`, `coolwarm`, `grayscale`
- Barra de color con valores mín/máx

### Feature 1 — Wireframe overlay
- Botón de aristas en el panel de control (icono GridOn)
- Activa/desactiva `actor.getProperty().setEdgeVisibility()` sin reconstruir la geometría
- Aristas en color casi negro, grosor 0.8 px

### Feature 2 — Node picking
- Modo crosshair activable con icono GpsFixed
- Al hacer clic, un overlay transparente captura el evento (sin interferir con el interactor de vtk.js)
- Ray-casting puro en JS: construye un rayo desde la cámara con matemáticas de perspectiva, encuentra el nodo más cercano al rayo
- Panel inferior izquierdo muestra: índice del nodo, coordenadas X/Y/Z y valor del campo en ese nodo

### Feature 3 — Pasos de tiempo / animación
- El parser detecta datos multi-paso en formatos Exodus II / XDMF (arrays 3-D de meshio)
- La API expone `time_steps: [0, 1, 2, …]` en el endpoint de geometría
- UI: slider de paso, botones ◄ Play/Pause ► y saltar al primero/último
- Reproducción automática cada 300 ms, se detiene en el último paso
- Para mallas estáticas (1 paso) los controles aparecen deshabilitados como referencia

### Feature 4 — Corte seccional
- Plano de corte sobre el mapper vía `vtkPlane` + `mapper.addClippingPlane()`
- Selector de eje: X / Y / Z (ToggleButtonGroup)
- Slider de posición: 0 % a 100 % del rango del bounding box en el eje elegido
- Botón de inversión: muestra la mitad opuesta del corte
- Se limpia con `mapper.removeAllClippingPlanes()` al desactivar o cambiar de malla

### Feature 5 — Estadísticas de campo
- `useMemo` calcula: min, max, media, desviación estándar, P5/P25/P50/P75/P95
- Histograma SVG inline de 24 bins
- Slider de umbral de doble punta (rango) que reasigna `mapper.setScalarRange(lo, hi)` en tiempo real para aislar zonas de interés
- Tabla de percentiles en notación científica
- Se resetea automáticamente al cambiar de campo

### Feature 6 — Exportar resultados
| Botón | Acción |
|-------|--------|
| 📷 Captura PNG | `renderWindow.captureImages()[0]` → descarga PNG |
| 📊 CSV | Nodos (id, x, y, z) + valores del campo activo; vectores incluyen fx/fy/fz + magnitud |
| ⬇ Malla | `GET /api/cae/meshes/{id}/download` → archivo original con su nombre original |

### IA — Análisis de hotspots
- `POST /api/cae/ai/analyze` recibe los valores del campo y devuelve índices de nodos críticos, nivel de riesgo (low/medium/high), ratio de concentración y recomendación textual
- Los hotspots se dibujan como puntos rojos sobre la malla
- Chip de riesgo con color semántico en el panel

---

## Arquitectura técnica clave

### Backend
- `app/cae/services/mesh_parser.py` — wraps meshio; detecta multi-paso; extrae triángulos de superficie de mallas volumétricas
- `app/cae/services/step_mesher.py` — GMSH headless (`-nopopup`, `LIBGL_ALWAYS_SOFTWARE=1`); exporta `.vtu` vía meshio
- `app/cae/api/cae_routes.py` — CRUD mallas, campos por paso, descarga, caché LRU de 8 entradas
- `app/cae/models/` — `CAEMesh`, `CAEField` (PostgreSQL + SQLAlchemy)

### Frontend
- `CAEViewer.jsx` — componente principal; pipeline vtk.js: `vtkPolyData` → `vtkMapper` → `vtkActor`; efectos React independientes por feature para evitar rebuilds innecesarios
- `CAEFileList.jsx` — lista, subida y generación desde STEP
- `MeshFromStepDialog.jsx` — configuración de refinamiento y algoritmo antes de mallar
- `vite.config.js` — `manualChunks` excluye React/MUI/Emotion para evitar TDZ en Rollup; vtk.js en chunk propio

### Infraestructura
- Docker multi-stage: Node 18 Alpine (build frontend) → condaforge/miniforge3 (Python 3.11 + pythonocc-core 7.7.2 + Flask)
- Libs X11/FLTK en el contenedor para GMSH headless (`libfltk1.3`, `libosmesa6`, etc.)
- nginx en el VPS hace proxy `/cae/step-view/` → `localhost:8080`

---

## Posibles features siguientes

### Alta prioridad / alto valor
| # | Feature | Descripción |
|---|---------|-------------|
| 7 | **Comparación de mallas** | Cargar dos mallas del mismo dominio y mostrar la diferencia de un campo (campo A − campo B) coloreado |
| 8 | **Deformed shape overlay** | Mostrar la malla deformada semitransparente encima de la original, con control de escala |
| 9 | **Anotaciones** | Click en nodo → etiqueta flotante en la escena 3D con valor; múltiples etiquetas simultáneas |
| 10 | **Isosuperficie** | Generar superficie de nivel para un valor umbral (usando marching cubes en JS o backend) |

### Mediana prioridad
| # | Feature | Descripción |
|---|---------|-------------|
| 11 | **Streamlines** | Visualización de campo vectorial (velocidades, flujo) con líneas de corriente |
| 12 | **Soporte `.pvd`** | Colección ParaView de `.vtu` con índice de tiempo real; animación de archivos múltiples |
| 13 | **Reporte PDF** | Generar un PDF con captura, estadísticas, hotspots y metadatos de la malla |
| 14 | **Filtro de sets** | Activar/desactivar `node_sets` / `element_sets` (grupos de Abaqus) en la visualización |

### Baja prioridad / exploratorio
| # | Feature | Descripción |
|---|---------|-------------|
| 15 | **Clipping plano múltiple** | Hasta 3 planos de corte simultáneos (esquina/cuadrante) |
| 16 | **Medición de distancia** | Pick de dos nodos → distancia en unidades del modelo |
| 17 | **Integración con CAPP** | Asociar una malla a una parte del sistema CAPP; vincular resultados FEA al plan de fabricación |
| 18 | **Colaboración en tiempo real** | Compartir vista 3D con otro usuario vía WebSocket (cámara sincronizada) |

---

## Correcciones backend STEP Viewer (round 2)

Bug raíz: `STEPFileHeader` no tiene columna `file_path`; la ruta vive en `Part.file_path` vía la relación `header.part`. Todos los endpoints que cargaban la geometría OCC usaban el atributo inexistente `header.file_path` o el atributo de backref erróneo `header.legacy_file` (el backref real es `step_view_file` pero solo se popula cuando existe un registro `STEPFile`).

### Archivos corregidos
| Archivo | Bug | Fix |
|---------|-----|-----|
| `api/measurement_routes.py` | `header.file_path` en 5 endpoints (area, volume, bbox, CoM, inertia) | `_get_file_path(header)` → `header.part.file_path` |
| `api/export_routes.py` | `header.file_path` y `header.legacy_file` en STL/OBJ/IGES/STEP/batch; `/step` llamaba `export_to_iges` en lugar de `export_to_step` | `_get_file_path(header)` en todos; corregida llamada en `/step` |
| `api/geometry_routes.py` | `header.legacy_file` en 3 endpoints (geometry, all-lods, bbox) | Reemplazado con `header.part.file_path`; variables locales renombradas |
| `api/comparison_routes.py` | Búsqueda de header por `legacy_file_id` (FK a `step_view_files`, no `parts`); `header.legacy_file` para shape loading | Resolución dual: UUID directo → fallback `part_id`; shapes via `header.part.file_path` |
| `api/feature_routes.py` | Sin `_resolve_header` (no aceptaba `part_id`); `header_id` sin normalizar en DB queries | Añadido `_resolve_header`; `resolved_id = str(header.id)` propagado |
| `api/files_routes.py` | Respuesta sin campo `file_name`; `ComparisonPanel` usaba `file.file_name` → undefined | Añadido `file_name` a ambas ramas (DB y disk-scan) |

## Limitaciones conocidas

- **Sin GPU en el VPS**: renderizado por software (Mesa/OSMesa). `setRenderPointsAsSpheres(true)` no está disponible; el picking usa ray-casting JS en lugar del picker nativo de vtk.js.
- **Mallas grandes**: el endpoint de geometría devuelve todos los nodos en JSON; para mallas > ~500 k nodos conviene paginar o usar formato binario (vtkjs-arraybuffer).
- **Un solo paso en la mayoría de formatos**: meshio lee un único time-step de VTU/INP/BDF; multi-paso real requiere Exodus II o XDMF.
- **Campos elementales**: se aplanan al primer bloque de celdas; la interpolación nodo→elemento no está implementada.
