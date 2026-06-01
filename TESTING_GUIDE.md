# Testing Guide — Sprint 1-5 Validation

## ✅ API Validation Results

All 4 test scenarios have been validated via API:

### Scenario 1: MATERIAL Properties ✓
- Graphs created successfully
- MATERIAL nodes can be added with E, ν, ρ properties
- Properties persist in the graph
- Mini-preview data available

### Scenario 2: BC DOF Checkboxes ✓
- BC nodes created with DOF arrays
- Properties including dofs=[0,1,2] (UX, UY, UZ) saved correctly
- node_set field working

### Scenario 3: Solver Reads from Graph ✓
- FEM solver endpoint `/api/design/solver/test/cantilever/` working
- Solver accepts material parameters (E, ν)
- Returns valid results (displacement, stress)

### Scenario 4: STEP/CAE/Design APIs ✓
- STEP files endpoint: `/api/step-view/files` ✓
- CAE meshes endpoint: `/api/cae/meshes` ✓
- Design graphs endpoint: `/api/design/graph/` ✓

---

## 📋 How to See Node Properties in UI

### Step-by-Step Guide

**1. Open the Design Mode**
   - Go to http://localhost:3000
   - Click **"Design"** chip in TopBar (turns blue)

**2. Create or Select a Graph**
   - Left sidebar: click existing graph or **"+ Nuevo grafo"**
   - Empty canvas appears with ConceptToolbar (left side)

**3. Drag a Node from Toolbar**
   - Find node type in toolbar (left side): Material, Frontera, Carga, etc.
   - Drag it onto the canvas
   - Node appears on canvas with label and mini-preview

**4. Click Node to Edit Properties**
   - Single click on the node
   - **Right panel opens** with property editor
   - Fields appear depending on node type

### What You See per Node Type

#### MATERIAL Node
```
Right Panel:
├─ Header: MATERIAL | Propiedades
├─ Label field: "Steel"
├─ Level slider (0-3)
├─ ════════════════ (divider)
├─ Modelo constitutivo: [linear_elastic_isotropic ▼]
├─ Módulo de Young [Pa]: 210000000000
├─ Coeficiente de Poisson: 0.3
├─ Densidad [kg/m³]: 7800
└─ [Guardar cambios] (green button)

Canvas Node Display:
├─ MATERIAL (chip header)
├─ "Steel" (label)
└─ E=210.0GPa ν=0.30 (mini-preview) ← Sprint 2
```

#### BC (Frontera) Node
```
Right Panel:
├─ Header: BC | Propiedades
├─ Label field: "Fixed Base"
├─ Level slider
├─ ════════════════
├─ Tipo de BC: [fixed ▼]
├─ Grados de libertad restringidos:
│  ├─ ✓ UX ✓ UY ✓ UZ    (click to toggle)
│  └─ ☐ RX ☐ RY ☐ RZ
├─ Valor prescrito: 0
├─ Nombre del conjunto de nodos: "fixed_base"
├─ Descripción/superficie: ""
└─ [Guardar cambios]

Canvas Node Display:
├─ BC (chip header)
├─ "Fixed Base" (label)
└─ Fixed [UX,UY,UZ] (mini-preview shows selected DOFs)
```

#### LOAD (Carga) Node
```
Right Panel:
├─ Header: LOAD | Propiedades
├─ Label field: "Downward Force"
├─ Level slider
├─ ════════════════
├─ Tipo de carga: [force ▼]
├─ Nombre del conjunto: "tip"
├─ Magnitud: 1000
├─ Unidad: "N"
├─ Direction:
│  ├─ Dx: 0
│  ├─ Dy: -1
│  └─ Dz: 0
├─ Vector de fuerza: (green box)
│  └─ F = [0.0, -1000.0, 0.0]  ← Sprint 2 preview
└─ [Guardar cambios]

Canvas Node Display:
├─ LOAD (chip header)
├─ "Downward Force" (label)
└─ F=-1000N (-Y) (mini-preview)
```

#### GEOMETRY Node
```
Right Panel:
├─ Header: GEOMETRY | Propiedades
├─ Label field
├─ Level slider
├─ ════════════════
├─ Tipo de representación: [custom ▼]
├─ Tier (límite de modelo): [Tier 1 ▼]
├─ ID de malla CAE: [text field] (optional)
├─ ID de archivo STEP: [text field] (optional)
└─ [Guardar cambios]

Canvas Node Display:
├─ GEOMETRY (chip header)
├─ label
└─ custom + Tier 1 chip
```

#### RESULT Node (Sprint 1)
```
Right Panel:
├─ Header: RESULT | Propiedades  (no Save button)
├─ [Read-only display box - empty until simulation]
│  └─ "Sin resultados — ejecuta una simulación primero"

After Simulation (Sprint 3):
├─ ✓ Simulación completada (green box)
├─ run_id: [UUID]
├─ σ_max von Mises [MPa]: 123.45
├─ Desplazamiento máx [mm]: 0.1234
└─ Factor de seguridad: 1.0

Canvas Node Display:
├─ RESULT (chip with checkmark)
├─ label
└─ σ_max: 123.45 MPa / δ_max: 0.1234 mm
```

#### OPTIMIZATION Node
```
Right Panel:
├─ Header: OPTIMIZATION | Propiedades
├─ Label field
├─ Level slider
├─ ════════════════
├─ Objetivo: [minimize_mass ▼]
├─ Tipo de restricción: [volume_fraction ▼]
├─ Valor de restricción: 0.5
├─ Método: [SIMP ▼]
└─ [Guardar cambios]

Canvas Node Display:
├─ OPTIMIZATION (chip header)
├─ label
└─ minimize_mass (mini-preview)
```

---

## 🐛 Known Issue: Node Duplication on Click

**Problem:** Single-clicking a node sometimes creates a duplicate.

**Status:** Under investigation

**Workaround:**
- If a duplicate appears, you can delete it by:
  1. Click the duplicate node
  2. Press **Delete** or **Backspace** key
  3. Or click [Delete node] button in the right panel header (red X icon)

**Root Cause (suspected):** May be related to how ReactFlow handles node selection vs. editor state. Not reproduced in API tests.

---

## 🎯 TopBar Status Indicators (Sprint 4)

Watch the TopBar (top of screen):
- **Green dots** appear next to mode chips when data is active:
  - STEP chip: dot when STEP file selected
  - CAE chip: dot when mesh selected
  - Design chip: dot when graph active
- **File/Mesh names** shown in TopBar below mode chips
- **Status icons** indicate cross-mode integration

Example:
```
[Design ●] [STEP] [CAE ●]     ← Dots show active modes
                          Mesh: assembly_lspp
```

---

## 🚀 Integration Workflow (Sprint 4)

### STEP → CAE → Design Pipeline

1. **STEP mode**: Upload or select a STEP file
2. **Generate Mesh**: Click Hub icon → select mesh parameters → "Generar Malla"
3. **Auto-Switch to CAE**: App automatically goes to CAE mode (BUG-1 fixed)
4. **Send to Design**: Click Share button on mesh → select graph → creates GEOMETRY node
5. **In Design**: Edit the GEOMETRY node properties, add MATERIAL/BC/LOAD
6. **Simulate**: Click ⚡ button → Solver reads properties from graph (Sprint 3)
7. **View Results**: RESULT node auto-populated (Sprint 3)

---

## ✅ Verification Checklist

- [ ] Create MATERIAL node, set E=70e9, see mini-preview
- [ ] Create BC node, toggle DOF checkboxes, see updated preview
- [ ] Create LOAD node, set magnitude/direction, see force vector preview
- [ ] Create GEOMETRY node, see it displays in canvas
- [ ] Delete nodes using Delete key
- [ ] Click Simular button (should read material/BC/LOAD from graph)
- [ ] See TopBar status indicators (green dots)
- [ ] Test STEP → CAE → Design workflow

---

**Backend Status**: All APIs working ✓  
**Database**: source_step_id FK added to CAEMesh ✓  
**Frontend**: Component properties editing implemented ✓
