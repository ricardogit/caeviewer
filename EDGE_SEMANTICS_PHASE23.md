# Edge Semantics — Phase 2-3 Implementation

## Overview

Phase 2-3 implements **edge-aware DAG validation and solver integration**:
- **Phase 2**: Enforce DAG structure (no cycles), validate edge semantics
- **Phase 3**: Solver reads edges for BC/LOAD scoping (multi-geometry support)

---

## Phase 2: DAG Validation

### What Changed

**Backend (`app/design/services/graph_service.py`):**
- Added `check_dag_validity(graph_id)` method using NetworkX
- Returns `{ is_dag: bool, cycles: [[node_list]] }`
- Integrated into `validate_completeness()` — cycles → error severity

**Backend (`app/design/api/graph_routes.py`):**
- New endpoint: `GET /<graph_id>/dag-check`
- Returns DAG status and cycle information

**Validation Logic:**
```python
# If DAG check fails:
errors.append({
    'severity': 'error',
    'message': '⚠️ Ciclo detectado: A → B → C → A. DAG requerido.'
})
```

### UI Behavior

**ValidationOverlay.jsx** already shows all validation errors including cycles:
- Red header if DAG is invalid
- Cycle message appears in error list
- Block simulation if cycles exist

### Example

```
Graph: A → B → C → A (cycle)

Validation Result:
❌ Error: Ciclo detectado en el grafo: ['A', 'B', 'C']
```

---

## Phase 3: Edge-Aware Solver

### New Edge Types (Semantic)

| Edge Type | From → To | Meaning | Solver Behavior |
|-----------|-----------|---------|---|
| `CONSTRAINS_MATERIAL` | MATERIAL → GEOMETRY | "This geometry uses this material" | Read material from source node |
| `CONSTRAINS_BC` | BC → GEOMETRY | "This BC applies to this geometry" | Apply BC only to target geometry |
| `APPLIED_TO` | LOAD → GEOMETRY | "This load applies to this geometry" | Apply LOAD only to target geometry |
| `DEPENDS_ON` | Node → Node | Generic dependency | Informational only |
| `FUNCTIONAL` | Node → Node | Functional relationship | Informational only |
| `MANUFACTURED_BY` | GEOMETRY → PROCESS | Process chain | Informational only |
| `PHYSICAL` | GEOMETRY → GEOMETRY | Physical connection | Informational only |
| `PRODUCES` | Node → RESULT | Output relationship | Informational only |

### Implementation Details

**Backend (`app/design/services/graph_to_solver_spec.py`):**

```python
def graph_to_solver_spec(graph_id) -> dict:
    # Check if ANY CONSTRAINS_BC or APPLIED_TO edges exist
    use_edge_scoping = any(e.edge_type in ('CONSTRAINS_BC', 'APPLIED_TO') 
                           for e in edges)

    if use_edge_scoping and geometry_nodes:
        # Phase 3: Edge-aware scoping
        for geom in geometry_nodes:
            # Get BCs for THIS geometry via CONSTRAINS_BC edge
            bc_edges = query(target_id=geom.id, edge_type='CONSTRAINS_BC')
            
            # Get LOADs for THIS geometry via APPLIED_TO edge
            load_edges = query(target_id=geom.id, edge_type='APPLIED_TO')
    else:
        # Phase 1 fallback: All BCs/LOADs to all GEOMETRIEs
        for bc in all_bc_nodes:
            apply_bc_globally()
```

**Key Methods in `DesignGraphService`:**

```python
# Get material assignment via CONSTRAINS_MATERIAL edge
material = service.get_material_for_geometry(graph_id, geometry_id)

# Get BC scope via CONSTRAINS_BC edge
bcs = service.get_bcs_for_geometry(graph_id, geometry_id)

# Get LOAD scope via APPLIED_TO edge
loads = service.get_loads_for_geometry(graph_id, geometry_id)
```

### Multi-Geometry Example

```
Design Graph:

MATERIAL "Steel" ──CONSTRAINS_MATERIAL──> GEOMETRY "Part A"
  └─ E=210 GPa

MATERIAL "Aluminum" ──CONSTRAINS_MATERIAL──> GEOMETRY "Part B"
  └─ E=70 GPa

BC "Fixed" ──CONSTRAINS_BC──> GEOMETRY "Part A"
  └─ DOF: [UX, UY, UZ]

LOAD "Force" ──APPLIED_TO──> GEOMETRY "Part B"
  └─ F = [0, -1000, 0]

Expected Solver Behavior:
- Part A uses Steel (E=210 GPa), fixed BC
- Part B uses Aluminum (E=70 GPa), 1000N downward load
- Each geometry has different material and constraints
```

### Backward Compatibility (Phase 1)

If NO `CONSTRAINS_BC` or `APPLIED_TO` edges exist:
```python
# Falls back to Phase 1 global application
spec['bcs'] = [bc_node.props for bc_node in ALL bc_nodes]
spec['loads'] = [load_node.props for load_node in ALL load_nodes]
```

This ensures existing graphs (Phase 1 style with no scoping edges) still work.

---

## Recommended Edge Structure (DAG + Semantic)

```
        CONCEPT (root, optional)
           ├─ MATERIAL "Steel" ──CONSTRAINS_MATERIAL──┐
           │                                           ↓
           ├─ GEOMETRY "Part A" ←──────────────────────┘
           │   ├─ BC "Fixed" ──CONSTRAINS_BC──→ (same)
           │   └─ LOAD "Force" ──APPLIED_TO──→ (same)
           │
           └─ RESULT (leaf)
              ↑
              └─ OPTIMIZATION ──TARGETS──┘
```

**DAG Properties:**
- Single semantic root (CONCEPT)
- MATERIAL → GEOMETRY via CONSTRAINS_MATERIAL
- BC/LOAD → GEOMETRY via CONSTRAINS_BC / APPLIED_TO
- RESULT/OPTIMIZATION are leaves
- No cycles
- Clear dependency direction

---

## Migration Path

### From Phase 1 → Phase 2-3

**For existing graphs (no scoping edges):**
1. Run validation → check DAG status
2. If cycles found → show warning, suggest removal
3. User can draw CONSTRAINS_BC / APPLIED_TO edges OR keep Phase 1 global mode

**For new graphs (with scoping edges):**
1. Drag BC, connect to specific GEOMETRY via CONSTRAINS_BC
2. Drag LOAD, connect to specific GEOMETRY via APPLIED_TO
3. Solver automatically uses edge-aware scoping

---

## API Summary

### New Endpoints

**DAG Validation:**
```http
GET /api/design/graph/<graph_id>/dag-check

Response:
{
  "graph_id": "uuid",
  "is_dag": true,
  "cycles": [],
  "message": "✓ Grafo es DAG válido"
}
```

### Updated Endpoints

**Validation includes DAG check:**
```http
GET /api/design/graph/<graph_id>/validate

Response:
{
  "ready_for_simulation": false,
  "errors": [
    {
      "severity": "error",
      "message": "⚠️ Ciclo detectado: ['A', 'B', 'A']"
    }
  ]
}
```

**Solver spec automatically uses edge scoping:**
```http
POST /api/design/solver/<graph_id>/run

// Internally calls graph_to_solver_spec(graph_id)
// which detects CONSTRAINS_BC/APPLIED_TO edges
// and applies scoped BCs/LOADs
```

---

## Frontend Changes (Phase 2-3 Ready)

**ValidationOverlay.jsx:**
- Already shows cycle errors in red
- Blocks simulation if cycles exist

**EdgeTypeDialog.jsx:**
- Already lists CONSTRAINS_MATERIAL, CONSTRAINS_BC, APPLIED_TO
- User can select these types when drawing edges

**Recommended enhancements (future):**
1. Visual cues: highlight edges when drawing scoping edges
2. Cycle detection: show cycle path with red dashed lines
3. Scoping legend: show which BCs/LOADs apply to which GEOMETRIEs
4. Edge validation UI: suggest converting CONSTRAINS → CONSTRAINS_BC for BC nodes

---

## Testing Phase 2-3

### Test Scenario: Multi-Geometry Assembly

```bash
# 1. Create graph
POST /api/design/graph/ 
  { "name": "Assembly Two Parts", "tier": 1 }

# 2. Create nodes
POST /api/design/graph/<id>/nodes (MATERIAL "Steel")
POST /api/design/graph/<id>/nodes (MATERIAL "Aluminum")
POST /api/design/graph/<id>/nodes (GEOMETRY "Part A")
POST /api/design/graph/<id>/nodes (GEOMETRY "Part B")
POST /api/design/graph/<id>/nodes (BC "Fixed Base")
POST /api/design/graph/<id>/nodes (LOAD "Tension")

# 3. Create edges
POST /api/design/graph/<id>/edges 
  {
    "source_id": "steel_id",
    "target_id": "partA_id",
    "edge_type": "CONSTRAINS_MATERIAL"
  }

POST /api/design/graph/<id>/edges 
  {
    "source_id": "bc_id",
    "target_id": "partA_id",
    "edge_type": "CONSTRAINS_BC"
  }

POST /api/design/graph/<id>/edges 
  {
    "source_id": "load_id",
    "target_id": "partB_id",
    "edge_type": "APPLIED_TO"
  }

# 4. Validate (should be DAG)
GET /api/design/graph/<id>/dag-check
  → { is_dag: true, cycles: [] }

# 5. Run solver (should scope BCs/LOADs)
POST /api/design/solver/<id>/run
  → Solver reads:
     - Part A with Steel + BC Fixed
     - Part B with Aluminum + Load 1000N
```

---

## Known Limitations

### Phase 3 Scope

- Material assignment via CONSTRAINS_MATERIAL: Ready ✓
- BC scoping via CONSTRAINS_BC: Ready ✓
- LOAD scoping via APPLIED_TO: Ready ✓
- DAG enforcement: Ready ✓
- Multi-geometry assembly: Ready (edges define scoping) ✓

### Not Implemented Yet

- Solver actually using `geometry_id` field in BC/LOAD entries (kernel update needed)
- UI multi-geometry assembly visualization
- Hierarchical assembly (parent-child GEOMETRY relationships)

---

## References

- GRAPH_ARCHITECTURE.md: Overall graph design
- app/design/services/graph_service.py: DAG check implementation
- app/design/services/graph_to_solver_spec.py: Edge-aware spec extraction
- app/design/api/graph_routes.py: DAG endpoint
