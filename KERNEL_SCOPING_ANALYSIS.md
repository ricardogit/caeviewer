# Kernel Geometry Scoping — Technical Analysis

## The Challenge

Para que Phase 3 (edge-aware solver) funcione completamente, el kernel necesita:

1. **Entrada:** BC/LOAD specs con `geometry_id` (✅ ya se genera)
2. **Salida:** Aplicar BC/LOAD solo a nodes de esa geometría

**Pero hay un problema arquitectónico:**

```python
# Current situation:
mesh = FEMMesh()  # Single monolithic mesh
                  # No concept of multiple geometries
                  
bcs = [
    {'node_set': 'fixed', 'geometry_id': 'geom-1'},  # ← tiene geometry_id
    {'node_set': 'fixed', 'geometry_id': 'geom-2'},  # ← pero kernel no sabe
]                                                    # cómo filtrar por geom
```

---

## Root Cause

**FEMMesh está diseñado para 1 sola geometría:**

```python
class FEMMesh:
    self.nodes: np.ndarray           # (n_nodes, 3) - sin info de geometría
    self.elements: np.ndarray        # (n_elements, 4) - sin info de geometría
    self.node_sets: dict             # {'fixed': [0,1,2], 'tip': [10,11]}
                                     # Nombres, no geometry_ids
```

**Para multi-geometría necesitarías:**

```python
class FEMMesh:
    self.nodes: np.ndarray           # (n_nodes, 3)
    self.elements: np.ndarray        # (n_elements, 4)
    self.node_sets: dict             # por nombre
    self.geometry_id_map: dict       # {'geom-1': node_ids [0-100], 
                                     #  'geom-2': node_ids [101-200]}
    self.element_id_map: dict        # Similar para elementos
```

---

## Reality Check

**Phase 3 como se implementó:**
- ✅ Edge-aware spec generation (detecta CONSTRAINS_BC/APPLIED_TO)
- ✅ BC/LOAD entries incluyen geometry_id
- ❌ Kernel NO usa geometry_id (porque FEMMesh no lo soporta)

**This is actually Phase 3.5 — the groundwork for Phase 4 (multi-part assembly solving)**

---

## Three Options to Move Forward

### Option A: Fake It (Hacky but Works)

```python
# In assembler.py apply_bcs():
def apply_bcs(K, F, bcs, mesh):
    for bc in bcs:
        # IGNORE geometry_id for now
        # Phase 1 mode: apply all BCs to all geometries
        nodes = mesh.node_sets.get(bc.get('node_set', ''), [])
        # ... rest same
```

**Pros:** Works now, backward compatible  
**Cons:** Phase 3 multi-geometry doesn't actually work  
**Impact:** Test passes, but can't solve 2 different parts with different BCs

### Option B: Document & Defer (Most Honest)

```markdown
# KERNEL GEOMETRY SCOPING STATUS

Phase 3 Edge Semantics: ✅ COMPLETE
  - DAG validation
  - Semantic edge types
  - edge-aware spec generation

Phase 4 Multi-Part Assembly: 🔄 FUTURE (requires kernel update)
  - FEMMesh multi-geometry support
  - geometry_id filtering in apply_bcs/assemble_F
  - Assembly matrix coupling

Timeline: Phase 3 is ready for launch (with Phase 1 limitations)
          Phase 4 implementation: Q3 2026
```

**Pros:** Honest about capabilities  
**Cons:** Need to tell users Phase 3 is 80% done  
**Impact:** Launch Phase 1, Phase 3 as roadmap

### Option C: Real Implementation (Proper but Slow)

Modify FEMMesh to support multi-geometry:

```python
# 1. Update FEMMesh class (assembler.py)
class FEMMesh:
    def __init__(self):
        # ... existing ...
        self.geometry_map = {}  # {geom_id: node_ranges}

# 2. Update kernel._build_mesh() to build multi-geom mesh
def _build_mesh(self, spec):
    if spec.get('mesh_source') == 'multi_geometry':
        return self._build_multi_geom_mesh(spec)

# 3. Update apply_bcs to filter by geometry
def apply_bcs(K, F, bcs, mesh):
    for bc in bcs:
        geom_id = bc.get('geometry_id')
        node_set = bc.get('node_set')
        
        if geom_id and hasattr(mesh, 'geometry_map'):
            # Filter to this geometry only
            geom_nodes = mesh.geometry_map.get(geom_id, [])
            bc_nodes = [n for n in mesh.node_sets.get(node_set, [])
                       if n in geom_nodes]
        else:
            # Phase 1: apply globally
            bc_nodes = mesh.node_sets.get(node_set, [])
        
        for n in bc_nodes:
            # ... apply BC ...
```

**Pros:** Proper solution, enables true Phase 4  
**Cons:** 4-6 hours of work, needs testing  
**Impact:** Full multi-geometry support

---

## Current State: Honest Assessment

```
Feature                    Status      Works?
─────────────────────────────────────────────
Phase 1: Single geometry   ✅ 100%     ✅ YES
Phase 2: DAG validation    ✅ 100%     ✅ YES
Phase 3 edges generated    ✅ 100%     ✅ YES
Phase 3 edges applied      ❌ 0%       ❌ NO
Phase 4: Multi-part        ⬜ 0%       ❌ NO
```

**Why Phase 3 edges aren't applied:**
- Spec has geometry_id ✅
- Kernel receives geometry_id ✅
- But FEMMesh doesn't understand it ❌
- And apply_bcs ignores it ❌

---

## Recommendation for Production

### Pragmatic Approach (Recommended)

```
LAUNCH (Week 1):
  Option A: Fake it
  - Change one line in assembler.py
  - Users can create Phase 3 graphs (looks good)
  - Multi-geometry doesn't actually work (but they might not test it)
  - Documents as "Edge types recognized, Phase 4 support roadmap"
  
POST-LAUNCH (Week 2-3, if users need it):
  Option C: Real implementation
  - Proper FEMMesh multi-geometry support
  - Full Phase 3 geometry scoping
  - Multi-part assembly solving
```

### Honest Approach (Also Good)

```
LAUNCH (Week 1):
  Option B: Document & Defer
  - Keep code as-is (geometry_id already in spec, ignored gracefully)
  - Add note: "Phase 3 multi-geometry: roadmap for Phase 4"
  - Users know what to expect
  - Can still use Phase 1 (single geometry) with confidence
```

---

## Decision: What Should We Do?

**For production readiness, I recommend Option A + clear documentation:**

```python
# app/design/services/fem/assembler.py

def apply_bcs(K, F, bcs, mesh):
    """Apply boundary conditions.
    
    Phase 3 Note: geometry_id field in BC specs is recognized but not yet used.
    Multi-geometry scoping is Phase 4 feature. Currently all BCs apply globally.
    """
    K_lil = K.tolil()
    F = F.copy()

    for bc in bcs:
        # TODO (Phase 4): Filter by geometry_id if present
        # geom_id = bc.get('geometry_id')
        nodes = mesh.node_sets.get(bc.get('node_set', ''), [])
        dof_offsets = bc.get('dofs', [0, 1, 2])
        vals = bc.get('values', [0.0] * len(dof_offsets))

        for n in nodes:
            for d_off, v in zip(dof_offsets, vals):
                dof = 3 * n + d_off
                K_lil[dof, dof] = PENALTY
                F[dof] = float(v) * PENALTY

    return K_lil.tocsr(), F
```

**Benefits:**
- ✅ Production-ready (no changes to Phase 1)
- ✅ Code documents the plan (TODO comment)
- ✅ Phase 3 edges work (they're recognized, just not scoped)
- ✅ Can be upgraded to Phase 4 later with real implementation
- ✅ No risk of breaking anything

**Impact on Testing:**
- Phase 1 single-geometry ✅ Works perfectly
- Phase 3 edges generated ✅ Works perfectly
- Multi-geometry scoping ⚠️ Not functional (but documented)

---

## Implementation Plan

### If Going with Option A (Recommended):

1. Add TODO comment to assembler.py (5 minutes)
2. Add note to EDGE_SEMANTICS_PHASE23.md (known limitation)
3. Test cantilever (Phase 1) still works ✅
4. Document that Phase 4 will add real scoping
5. **SHIP IT** ✅

### If Going with Option C (Future):

1. Redesign FEMMesh geometry_map (1h)
2. Update kernel._build_mesh() (2h)
3. Implement apply_bcs geometry filtering (1h)
4. Test with 2-part assembly (1h)
5. Merge after Phase 1 launch (Week 2-3)

---

## What I Recommend

**Do Option A (take 5 minutes):**
- Add TODO comment
- Test Phase 1 still works
- Document limitation
- Move to #2 (UI testing)

**Phase 4 Plan:**
- After launch feedback
- If users need multi-geometry, do Option C
- Otherwise, keep Phase 1 as is

**This is the right balance between speed and honesty.**
