# Design Graph Architecture — Node Connections & Solver Integration

## 🔗 Overview: What Are Graph Connections?

The Design Graph is a **Directed Acyclic Graph (DAG)** where:
- **Nodes** = engineering concepts (MATERIAL, GEOMETRY, BC, LOAD, etc.)
- **Edges** = semantic relationships between concepts
- **Direction** = information flow and dependency

Currently: **Connections are informational/semantic only** — they don't directly affect solver input.

---

## 📊 Current Connection Types (6 Edge Types)

Edges represent how concepts relate in the engineering domain:

| Edge Type | Meaning | Example | Solver Impact |
|-----------|---------|---------|---|
| **CONSTRAINS** | One concept constrains another | BC constrains GEOMETRY | None (informational) |
| **DEPENDS_ON** | Dependency relationship | LOAD depends on GEOMETRY | None (informational) |
| **FUNCTIONAL** | Functional relationship | OPTIMIZATION targets RESULT | None (informational) |
| **MANUFACTURED_BY** | Manufacturing process chain | GEOMETRY manufactured by PROCESS | None (informational) |
| **PHYSICAL** | Physical connection | GEOMETRY₁ physically connects to GEOMETRY₂ | None (informational) |
| **PRODUCES** | Output/result relationship | LOAD produces RESULT | None (informational) |

---

## 🚨 Important: Edges Are NOT Used by Solver (Currently)

### What the Solver Actually Reads:

```python
# In graph_to_solver_spec.py:

spec = {
    'material': {...},      # ← Read from MATERIAL node properties
    'bcs': [...],          # ← Read from BC node properties
    'loads': [...],        # ← Read from LOAD node properties
    'geometry': {...},     # ← Read from GEOMETRY node properties
}

# Edges are NOT consulted at all!
```

### What Solver Ignores:
- ❌ No automatic aggregation of BC/LOAD nodes based on edges
- ❌ No automatic material assignment based on CONSTRAINS edge
- ❌ No automatic ordering based on DEPENDS_ON
- ❌ No validation that edges follow a certain pattern

---

## 💡 What Connections COULD Mean (Future Design)

### Option A: Explicit Material Assignment (Proposed)

```
GEOMETRY ──MATERIAL──> MATERIAL
  |                        |
  |                    E = 210 GPa
  └──────────────────────┘
   "This geometry uses steel"
```

**Benefit:** Avoid having all geometries use the same material

**Current Issue:** No such edge type; solver ignores edges

---

### Option B: Hierarchical Assembly Structure

```
ASSEMBLY (parent GEOMETRY)
   ├─ PART_A (child GEOMETRY) ──MANUFACTURED_BY──> PROCESS_1
   ├─ PART_B (child GEOMETRY) ──MANUFACTURED_BY──> PROCESS_2
   └─ PART_C (child GEOMETRY) ──MANUFACTURED_BY──> PROCESS_3
```

**Benefit:** Model complex assemblies with part-level attributes

**Current Issue:** No parent-child relationship; all parts are independent

---

### Option C: BC/Load Scoping via Edges

```
BC (fixed base)
  ├─ CONSTRAINS ──> GEOMETRY_1.face[0]
  └─ CONSTRAINS ──> GEOMETRY_2.face[0]

LOAD (downward force)
  ├─ APPLIED_TO ──> GEOMETRY_1.vertex[12]
  └─ APPLIED_TO ──> GEOMETRY_2.vertex[8]
```

**Benefit:** Multiple geometries, selective BC/LOAD application

**Current Issue:** No such edges; BC/LOAD apply globally by node_set name

---

## 🎯 Recommended DAG Structure (Best Practice)

If you want a meaningful DAG, follow this pattern:

```
        CONCEPT (root)
           ├─ GEOMETRY
           │   └─ DEPENDS_ON → MATERIAL
           │
           ├─ MATERIAL (leaf)
           │
           ├─ BC ──CONSTRAINS──> GEOMETRY
           │
           ├─ LOAD ──APPLIED_TO──> GEOMETRY
           │
           └─ OPTIMIZATION ──TARGETS──> RESULT
```

**DAG Properties:**
- Single root (CONCEPT)
- Material, BC, LOAD are children
- RESULT is leaf (no outgoing edges)
- No cycles ✓
- Clear dependency direction ✓

---

## ⚙️ How Solver Currently Works (Current Implementation)

### Step 1: User drags nodes into graph
```
Canvas:
├─ MATERIAL "Steel"
├─ BC "Fixed Base"  
├─ LOAD "1000N"
└─ GEOMETRY "Cantilever"
```

**Edges drawn:** User creates (but solver ignores them)

### Step 2: Click "Simular"
```python
# In solver_routes.py:
spec = graph_to_solver_spec(graph_id)

# This function:
for node in graph.nodes:
    if node.type == 'MATERIAL':
        spec['material'] = node.properties
    elif node.type == 'BC':
        spec['bcs'].append(node.properties)
    elif node.type == 'LOAD':
        spec['loads'].append(node.properties)
    elif node.type == 'GEOMETRY':
        spec['mesh_source'] = 'geometry'
        # edges NOT consulted
```

### Step 3: Solver uses spec
```python
kernel.solve_sync(spec)
# ↓
# material = spec['material']
# bcs = spec['bcs']  # ALL BC nodes regardless of edges
# loads = spec['loads']  # ALL LOAD nodes regardless of edges
# ↓
# Assemble & solve
```

---

## 📌 What Edges Could Indicate (But Don't Currently)

### If We Implemented Edge Semantics:

```yaml
MATERIAL "Steel" 
  ↑ CONSTRAINS_MATERIAL
  |
  └─ GEOMETRY "Cantilever"
      ↑ CONSTRAINS
      |
      └─ BC "Fixed Base"
      
Load Map:
LOAD "1000N" ──APPLIES_TO──> BC node's GEOMETRY
```

**This could enable:**
- `graph.get_material_for_geometry(geom_id)` ← follow CONSTRAINS_MATERIAL edge
- `graph.get_bcs_for_geometry(geom_id)` ← follow CONSTRAINS edges
- `graph.get_loads_for_geometry(geom_id)` ← follow APPLIES_TO edges

**But currently:** All BC/LOAD nodes are applied to all GEOMETRY nodes (no scoping)

---

## 🔄 Proposed Improvement: Edge-Aware Solver (Future)

Instead of:
```python
spec['bcs'] = [bc.properties for bc in ALL BC nodes]
```

Implement:
```python
spec['bcs'] = []
for geometry in graph.geometries():
    bc_nodes = geometry.incoming_edges(edge_type='CONSTRAINS')
    for bc_node in bc_nodes:
        spec['bcs'].append({
            'geometry_id': geometry.id,
            'bc_type': bc_node.properties.bc_type,
            ...
        })
```

**Benefits:**
- Multiple geometries with different BCs ✓
- Clear scoping ✓
- Edge semantics matter ✓
- True DAG structure ✓

---

## 📋 Current State Summary

| Aspect | Current | DAG? | Used by Solver? |
|--------|---------|------|---|
| Nodes | 7 types | Yes | Yes |
| Edges | 6 types defined | No | **NO** |
| Ordering | Free (any topology) | No | N/A |
| Scoping | Global (all nodes) | N/A | Yes |
| Material → Geometry | No mapping | N/A | Uses first MATERIAL for all |
| BC → Geometry | No mapping | N/A | All BCs to all geometries |
| LOAD → Geometry | No mapping | N/A | All LOADs to all geometries |

---

## 💾 What Should Be Stored in DB

Current (working):
- ✓ Node properties (material E/ν, BC type, LOAD magnitude)
- ✓ Node positions (pos_x, pos_y)
- ✓ Node types & labels

Current (implemented but unused):
- ✓ Edges with types (CONSTRAINS, DEPENDS_ON, etc.)
- ❌ Edge semantics NOT enforced

New requirement for edge-aware solver:
- Validate edges follow DAG rules (no cycles)
- Extract edge relationships and use them in spec

---

## 🎨 UI/UX Implications

### Current Freedom (No Constraints)
```
Users can create:
- Cycles: A → B → A ✓ (allowed but meaningless)
- Disconnected subgraphs ✓ (allowed)
- Orphan nodes with no edges ✓ (allowed)
```

### If We Enforce DAG Rules
```
Validation would enforce:
- No cycles ✓
- Clear root → leaf flow ✓
- Possibly: every node must connect ✓
```

**UI Change Needed:**
- Add DAG cycle detection
- Show warnings if edges create cycles
- Suggest "correct" edge directions

---

## 🚀 Recommendation: 3-Phase Evolution

### Phase 1 (Current) ✓
- Nodes contain all properties
- Edges are informational only
- Solver reads node properties, ignores edges
- Free topology (no DAG enforcement)

### Phase 2 (Next)
- Enforce DAG structure (cycle detection)
- Validate edges have semantic meaning
- Add edge semantics to validation
- UI: show cycle warnings

### Phase 3 (Future)
- Edge-aware solver
- Material assignment by CONSTRAINS_MATERIAL edge
- BC/LOAD scoping by geometry edges
- True multi-geometry support

---

## 🔍 How to Check Current Graph Structure

In the browser console:
```javascript
// Get all nodes
const nodes = graphData.nodes;
console.log(nodes);

// Get all edges
const edges = graphData.edges;
console.log(edges);

// Check for cycles (simple check)
const hasCycles = (nodes, edges) => {
  // Would need a DFS algorithm
};
```

---

## 📚 References

- **Current**: nodes store all data, edges decorative
- **Architecture**: 7-node-type ontology (MATERIAL, BC, LOAD, GEOMETRY, CONCEPT, RESULT, OPTIMIZATION)
- **Solver coupling**: via `graph_to_solver_spec()` which reads node properties only
- **DAG status**: Can have cycles (not enforced), but semantically should be DAG
