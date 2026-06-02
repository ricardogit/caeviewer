# UI Manual Testing Checklist — Pre-Production

**Before Production Launch, test these 5 scenarios manually in the browser.**

---

## Setup

**Start Backend & Frontend:**
```bash
# Terminal 1: Backend
python run.py
# Should say: "Running on http://localhost:8080"

# Terminal 2: Frontend  
cd frontend && npm run dev
# Should say: "Local: http://localhost:3000"
```

**Open Browser:**
```
http://localhost:3000
```

---

## ✅ SCENARIO 1: Node Properties — MATERIAL

**Goal:** Create MATERIAL node, edit properties, verify mini-preview

### Steps:

1. [ ] Click **Design** chip (top bar)
   - Expected: TopBar turns blue, canvas area is empty

2. [ ] Click **+ Nuevo grafo** (left sidebar)
   - Expected: Dialog asks for graph name
   - Enter: "Test Material Properties"
   - Click: Create
   - Expected: Canvas loads with toolbar on left, empty canvas

3. [ ] Find **Material** icon in toolbar (left side)
   - Expected: Icon with "M" or material symbol
   - Tooltip should appear on hover: "Material"

4. [ ] **Drag Material node** to canvas
   - Drag from toolbar → center of canvas
   - Expected: Node appears with label "Material" + mini-preview

5. [ ] **Click node to edit**
   - Click the Material node
   - Expected: Right panel opens with property editor
   - Fields visible:
     - [ ] Label: "Steel" (editable text)
     - [ ] Level slider: 0-3
     - [ ] Constitutive model dropdown: "linear_elastic_isotropic"
     - [ ] Young's Modulus (E): 210000000000
     - [ ] Poisson ratio (ν): 0.3
     - [ ] Density (ρ): 7800

6. [ ] **Edit E value**
   - Change E from 210e9 → 70e9
   - Expected: Field shows "70000000000"
   - Mini-preview should update in real-time (if implemented)

7. [ ] **Change ν**
   - Change ν from 0.3 → 0.33
   - Expected: Field updates

8. [ ] **Click "Guardar cambios"** (Save button)
   - Expected: Green button at bottom of panel
   - After click: Button briefly highlights, no error message

9. [ ] **Verify persistence**
   - Click canvas (deselect node)
   - Click node again
   - Expected: E=70000000000, ν=0.33 still there

10. [ ] **Check mini-preview**
    - Expected below node label: `E=70.0GPa ν=0.33` or similar
    - (If mini-preview not implemented, note as limitation)

### Expected Result: ✅ PASS
- Node created with editable properties
- Properties saved and persist
- Mini-preview shows key values
- No console errors

### If FAIL:
- [ ] Check browser console (F12) for errors
- [ ] Check network tab for API calls
- [ ] Verify `/api/design/graph/{id}/nodes/` returns correct properties

---

## ✅ SCENARIO 2: BC Node — DOF Checkboxes

**Goal:** Create BC node, toggle DOF checkboxes, verify preview

### Steps:

1. [ ] With same graph open, find **Frontera (BC)** in toolbar

2. [ ] **Drag BC node** to canvas
   - Expected: Node appears with label "Frontera"

3. [ ] **Click to edit**
   - Expected: Right panel shows BC editor
   - Fields visible:
     - [ ] Label: "Frontera"
     - [ ] BC Type dropdown: "fixed"
     - [ ] **6 DOF checkboxes:** UX, UY, UZ, RX, RY, RZ
     - [ ] Value field: 0
     - [ ] Node set field: "fixed"

4. [ ] **Verify default DOF selection**
   - Expected: UX, UY, UZ are **checked** (✓)
   - Expected: RX, RY, RZ are **unchecked** (☐)

5. [ ] **Toggle DOF checkboxes**
   - [ ] Uncheck UZ
     - Expected: UZ checkbox becomes ☐
     - Mini-preview should change
   - [ ] Check RX
     - Expected: RX checkbox becomes ✓
     - Mini-preview should change

6. [ ] **Save**
   - Click "Guardar cambios"
   - Expected: No error

7. [ ] **Verify persistence**
   - Deselect and re-select node
   - Expected: dofs still shows UX, UY (not UZ), RX

8. [ ] **Check mini-preview**
   - Expected: something like `Fixed [UX,UY,RX]`
   - Should reflect selected DOFs

### Expected Result: ✅ PASS
- 6 DOF checkboxes functional
- Selection persists
- Mini-preview updates with selected DOFs

### If FAIL:
- [ ] Checkboxes not clickable: check onClick handlers in NodePanel.jsx
- [ ] DOFs not saving: check PATCH request in network tab
- [ ] Mini-preview missing: check DesignNodeComponent.jsx

---

## ✅ SCENARIO 3: Solver Integration — Graph Properties

**Goal:** Create MATERIAL+BC+LOAD nodes, run solver, verify it uses graph properties

### Steps:

1. [ ] In same or new graph, create **3 nodes:**
   - [ ] MATERIAL: E=70e9, ν=0.33 (Aluminum)
   - [ ] BC: Fixed, UX+UY+UZ
   - [ ] LOAD: Magnitude=1000, Direction=(0,-1,0)

2. [ ] **Connect nodes with edges** (optional but recommended)
   - Drag from BC → GEOMETRY (not required, but nice to have)
   - Edge type: CONSTRAINS
   - Expected: Edge appears

3. [ ] **Click "✓ Validar grafo"** (top right)
   - Expected: Validation panel appears
   - Expected: Shows either "Grafo válido" or "Errores encontrados"
   - If errors: fix them (missing GEOMETRY?)

4. [ ] **Add GEOMETRY node** if missing
   - Drag GEOMETRY node to canvas
   - Expected: Node labeled "GEOMETRY"

5. [ ] **Re-validate**
   - Click "✓ Validar grafo" again
   - Expected: "Grafo válido" message
   - Status should be "ready_for_simulation: true"

6. [ ] **Click "⚡ Simular"** (Solver button)
   - Expected: WebSocket connection opens
   - Expected: Progress bar or spinner appears
   - Expected: Progress messages:
     - "starting..."
     - "mesh built: XXX nodes, YYY elements"
     - "assembly complete, applying BCs"
     - iterations/residuals
     - "Done"

7. [ ] **Wait for completion** (30-60 seconds)
   - Expected: No errors in console
   - Expected: Final message with results

8. [ ] **Check RESULT node** (if exists)
   - Expected: RESULT node populated with:
     - [ ] run_id (UUID)
     - [ ] max_von_mises_mpa (stress value)
     - [ ] max_displacement_mm (displacement value)

9. [ ] **Verify solver used graph properties**
   - Expected: Solver results calculated with E=70e9, ν=0.33
   - (Hard to verify without comparing to manual calc, but no errors = good sign)

### Expected Result: ✅ PASS
- Solver launches without errors
- Progress updates show mesh+assembly+solve
- Results appear in console/UI
- No WebSocket disconnect errors
- RESULT node shows values

### If FAIL:
- [ ] **Solver timeout:** Check solver_routes.py for errors
- [ ] **WebSocket error:** Check socketio connection in browser console
- [ ] **No results:** Check `_update_result_nodes()` in kernel.py
- [ ] **Wrong E/ν used:** Check graph_to_solver_spec() extraction

---

## ✅ SCENARIO 4: DAG Validation — Cycle Detection

**Goal:** Create cycle A→B→C→A, verify validation blocks it

### Steps:

1. [ ] In new graph, create **3 GEOMETRY nodes:** A, B, C

2. [ ] Create **edges (with cycle):**
   - [ ] A → B: edge_type = "DEPENDS_ON"
   - [ ] B → C: edge_type = "DEPENDS_ON"
   - [ ] C → A: edge_type = "DEPENDS_ON" ← closes the cycle

3. [ ] **Click "✓ Validar grafo"**
   - Expected: Validation panel appears
   - Expected: **RED error message** showing cycle detected
   - Example: "Ciclo detectado: ['A', 'B', 'C']" or similar

4. [ ] **Verify "Simular" blocked**
   - Try clicking "⚡ Simular" button
   - Expected: Button disabled or click does nothing
   - Expected: Error message: "Fix validation errors first"

5. [ ] **Delete one edge to break cycle**
   - Click edge C → A
   - Expected: Edge highlights
   - Press **Delete** key
   - Expected: Edge disappears

6. [ ] **Re-validate**
   - Click "✓ Validar grafo" again
   - Expected: **GREEN checkmark** or "Grafo válido" message
   - Expected: No more cycle error

7. [ ] **Verify "Simular" now allowed**
   - Try clicking "⚡ Simular"
   - Expected: Either launches or says "missing MATERIAL/BC/LOAD"
   - Key: No longer "cycle" error

### Expected Result: ✅ PASS
- Cycle detected in validation
- Error message shows cycle path
- Solver blocked while cycle exists
- Cycle removal re-enables solver

### If FAIL:
- [ ] **Cycle not detected:** Check check_dag_validity() in graph_service.py
- [ ] **Error not shown:** Check validation_routes.py response
- [ ] **Solver still allowed:** Check validation guard in solver_routes.py

---

## ✅ SCENARIO 5: Cross-Mode Integration — STEP→CAE→Design

**Goal:** Test mode switching and cross-mode linking

### Steps (STEP Mode):

1. [ ] Click **STEP** chip (top bar)
   - Expected: STEP mode activates
   - Expected: Left sidebar shows file list (probably empty)
   - Expected: 3D viewer on right

2. [ ] **Upload STEP file**
   - Click upload button (should be in left panel)
   - Select a `.stp` or `.step` file
   - Expected: File appears in list
   - Expected: 3D model loads in viewer

3. [ ] **Generate Mesh** (if button exists)
   - Look for "Generar Malla" or gear icon
   - Click it
   - Expected: Dialog with mesh parameters
   - Click "Generar"
   - Expected: **Auto-switch to CAE mode**

### Steps (CAE Mode):

4. [ ] **Verify auto-switch to CAE worked**
   - Expected: CAE chip is now blue
   - Expected: Mesh viewer shows same geometry
   - Expected: Left sidebar shows mesh list

5. [ ] **Look for Share button**
   - Find mesh in sidebar
   - Expected: Share icon (button) on the right
   - Click it

6. [ ] **Select target Design graph**
   - Expected: Dialog opens
   - Expected: Dropdown to select existing graph or "Create new"
   - Select any graph (or create new "STEP→CAE→Design Test")
   - Click "Enviar a Diseño" or "Send to Design"
   - Expected: Success message

### Steps (Design Mode):

7. [ ] **Switch to Design**
   - Click **Design** chip
   - Expected: Canvas loads with existing nodes

8. [ ] **Find GEOMETRY node created from mesh**
   - Expected: New node appeared (labeled with mesh filename)
   - Expected: Properties show mesh_id (linked to CAE mesh)

9. [ ] **Verify the link works**
   - Click GEOMETRY node
   - Expected: Right panel shows mesh_id field
   - Expected: Could potentially click to view mesh

### Expected Result: ✅ PASS
- STEP upload works
- Mesh generation launches
- Auto-switch to CAE works
- Share button available
- GEOMETRY node created in Design with mesh_id
- Cross-mode linking functional

### If FAIL:
- [ ] **STEP upload fails:** Check /api/step-view/upload
- [ ] **Auto-switch doesn't happen:** Check App.jsx line 438 (should be setAppMode('cae'))
- [ ] **Share button missing:** Check CAEFileList.jsx
- [ ] **No GEOMETRY node:** Check /api/design/graph/{id}/import/mesh endpoint

---

## Summary Checklist

### All 5 Scenarios:
- [ ] **Scenario 1:** MATERIAL properties editing ✓
- [ ] **Scenario 2:** BC DOF checkboxes ✓
- [ ] **Scenario 3:** Solver reads graph properties ✓
- [ ] **Scenario 4:** DAG cycle detection ✓
- [ ] **Scenario 5:** Cross-mode integration ✓

### No Errors:
- [ ] Browser console (F12): No red errors
- [ ] Network tab: No 500 errors, only 200/201/202
- [ ] WebSocket: "Connecting → Connected" (not "Disconnected")
- [ ] Solver: No "timeout" or "FATAL" messages

### UI Usability:
- [ ] Buttons respond immediately (no lag)
- [ ] Text fields editable
- [ ] Checkboxes toggle smoothly
- [ ] Panels open/close smoothly
- [ ] No visual glitches (overlapping text, etc.)

---

## Known Limitations (Expected)

⚠️ These are OK — don't count as failures:

- [ ] Multi-geometry solver scoping (Phase 4 feature)
- [ ] Undo/Redo not implemented
- [ ] No real-time mesh refinement visualization
- [ ] No keyboard shortcuts (except Delete)
- [ ] Drag-drop node duplication (rare edge case)
- [ ] Code editor features minimal

---

## Issues Found Log

If you find problems, document them here:

| Scenario | Issue | Severity | Status |
|----------|-------|----------|--------|
| ? | ? | ? | ? |

---

## Sign-Off

Once all 5 scenarios pass with no critical issues:

```
Date: ___________
Tester: ___________
Status: ☐ READY FOR PRODUCTION
        ☐ NEEDS FIXES (list below)
```

---

## How to Run (Quick Reference)

```bash
# Terminal 1
python run.py

# Terminal 2
cd frontend && npm run dev

# Browser
http://localhost:3000
```

**Typical test time:** 30-45 minutes for all 5 scenarios
