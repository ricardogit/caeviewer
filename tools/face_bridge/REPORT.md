# Fase 1a — Spike del puente OCC → Gmsh

Prueba aislada de la cadena de IDs estables: **cara OCC → superficie Gmsh → Physical Group → `*NSET`/`*ELSET` en el `.inp`**, antes de construir UI.

## Cómo correrlo

```bash
docker build -f docker/geometry.Dockerfile -t caeviewer-geometry:latest .
MSYS_NO_PATHCONV=1 docker run --rm --memory 4g -v C:/cae-viewer:/work -w /work \
  -e PYTHONPATH=/work caeviewer-geometry:latest \
  python -m tools.face_bridge.spike [--only NOMBRE] [--heal] [--no-mesh] [--mesh-timeout 300]
```

Resultados en `data/face_bridge_spike/` (ignorado por git): `summary.json`, un JSON por archivo con firmas y tabla `face_index ↔ gmsh_tag`, más los `.brep` e `.inp`.

## Módulos

| Archivo | Responsabilidad |
|---|---|
| `occ_import.py` | `STEPCAFControl_Reader` (XDE) en mm, índice de cara con `TopExp.MapShapes` (1-based), firmas OCC, escritura BREP |
| `signature.py` | Normalización de tipo de superficie, hash estable de firma, `match_signatures` (OCC↔OCC entre versiones) |
| `gmsh_bridge.py` | Importa el BREP en Gmsh sin reparación, firma por superficie (`getMass`, `getCenterOfMass`), emparejamiento 1:1 que falla de forma explícita, Physical Groups + `.inp` |
| `spike.py` | CLI: determinismo, puente, mallado aislado con timeout, comparación entre versiones |

## Resultados (7 STEP de `examples/`)

| Archivo | Caras | Sólidos | Determinismo (proceso / corridas) | Emparejadas | Δ centroide máx | Malla tet + `.inp` `F_<idx>` |
|---|---|---|---|---|---|---|
| arbol FINAL | 46 | 1 | OK / OK | 46/46 | 6e-14 mm | ✅ 12 k tets |
| tapa entredos | 130 | 1 | OK / OK | 130/130 | 2e-11 mm | ❌ error PLC |
| Cuerpo | 218 | 1 | OK / OK | 218/218 | 3e-9 mm | ❌ error PLC / timeout 300 s |
| Cuerpo Con Soporte | 332 | 1 | OK / OK | 332/332 | 3e-9 mm | ❌ error PLC; HXT también falla |
| IMPELENTE SW | 435 | 1 | OK / OK | 435/435 | 4e-10 mm | ✅ 24 k tets |
| Pedestal - copia | 353 | 1 | OK / OK | 353/353 | 3e-10 mm | ✅ 323 k tets |
| Pedestalx | 247 | 1 | OK / OK | 247/247 | 3e-10 mm | ✅ 205 k tets |

**Veredicto:** el puente funciona. Se emparejaron 1761/1761 caras, sin ambigüedades y sin discrepancias de tipo de superficie. Los IDs son deterministas dentro de un mismo proceso y entre corridas distintas.

- **Tiempos:** importar con XDE < 2 s, firmas ≤ 6 s, importar en Gmsh < 0.3 s, emparejar < 15 ms.
- **Physical Groups:** en las 4 piezas que mallan, los grupos de 3 caras tienen nodos y el `.inp` trae `*NSET`/`*ELSET` con nombre `F_<idx>`. Los tags de Gmsh no cambian al reimportar el BREP en una sesión nueva.
- **Orden de Gmsh:** coincidió con el de `TopExp` en todos los casos. Aun así se mantiene el emparejamiento por firma, que es lo que lo garantiza.
- **Sin probar:** todos los STEP son de un solo sólido, así que los ensambles (agrupación por sólido, caras de contacto coincidentes) no se probaron con datos reales. El código ya los contempla.
- **Nombres XDE:** solo el sólido trae nombre; ninguna cara.

## Tolerancias

Se miden contra `L`, la diagonal del bbox del modelo.

| Criterio | Valor | Uso | Holgura observada |
|---|---|---|---|
| Centroide | 1e-4·L | filtro duro | desviación máxima 3e-9 mm |
| Área | 1e-3 relativo | filtro duro | desviación máxima 2e-10 |
| Tipo de superficie | penalización | costo blando | sin discrepancias |
| Bbox | — | costo blando | Gmsh se desvía hasta 88 mm en B-splines |

**Recomendación:** quitar el bbox del emparejamiento OCC↔Gmsh, porque `getBoundingBox` de Gmsh es demasiado holgado. Usarlo solo para comparar versiones OCC↔OCC, donde es preciso.

## Entre versiones: "Pedestal - copia" (353 caras) vs "Pedestalx" (247)

- 196 caras tienen hash idéntico, pero **solo 10 conservan el mismo índice**.
- Por firma se emparejan 201 caras con tolerancia estricta y 204 con holgada, sin ambigüedades.

**Consecuencia para la Fase 1b/2:** el índice de `TopExp` es estable dentro de una versión de la geometría, pero no entre versiones. Las condiciones de frontera se migran entre versiones con `match_signatures`. Las caras sin pareja son geometría que cambió de verdad y se marcan con ⚠ para que el usuario decida.

## Fallos y aprendizajes

1. **Mallado de 3 piezas (independiente del puente).** Gmsh falla igual abriendo el STEP directo, que es lo que hace hoy `step_mesher.py`.
   - Errores: TetGen `A segment and a facet intersect`, `HXT 3D mesh failed` y, con MeshAdapt, `Invalid boundary mesh (overlapping facets)`.
   - Probado sin éxito: algoritmos 3D 1, 10 y 4; tamaño ×1, ×0.5 y ×0.25; algoritmos 2D 6, 1 y 5; tamaño por curvatura activado y desactivado; con y sin reparación de Gmsh.
   - **Pendiente para la Fase 2:** tamaños locales, `ShapeFix_Shape` en OCC antes de escribir el BREP (volviendo a calcular las firmas) y defeaturing.
2. **Gmsh puede colgarse.** El mallado debe correr en un proceso aislado con timeout duro (el spike usa `fork` + `kill`). Encaja con los jobs de la cola `mesh`.
3. **Reintentar en la misma sesión no sirve.** Tras un fallo de TetGen, limpiar y regenerar devolvió 0 tetraedros sin lanzar error. Cada intento va en una sesión de Gmsh nueva, y una malla vacía cuenta como fallo.
4. **pythonOCC 7.7.2** aborta (`Standard_NullObject`) con `TDocStd_Document(TCollection_ExtendedString(...))`. Pasándole un `str` funciona.
5. **Memoria del anfitrión.** Con poca memoria libre, el CLI de Docker en Windows murió (exit 139). Conviene correr un contenedor por archivo con `--memory 4g`; el spike usa unos 250 MB.
