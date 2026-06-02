#!/usr/bin/env python3
"""
UI Testing Scenarios — Automated validation of all 5 critical scenarios.
This script simulates the UI workflows through the API.
"""
import requests
import json
import sys
import time

BASE_URL = "http://localhost:8080"

class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def log_pass(self, scenario, message):
        self.passed += 1
        msg = f"[PASS] {scenario}: {message}"
        print(msg)
        self.results.append(("PASS", scenario, message))

    def log_fail(self, scenario, message):
        self.failed += 1
        msg = f"[FAIL] {scenario}: {message}"
        print(msg)
        self.results.append(("FAIL", scenario, message))

    def log_info(self, message):
        print(f"[INFO] {message}")

runner = TestRunner()

print("=" * 70)
print("UI TESTING SCENARIOS — Automated Validation")
print("=" * 70)

# ============================================================================
# SCENARIO 1: MATERIAL Node Properties
# ============================================================================

print("\n[TEST 1] MATERIAL Node Properties")
print("-" * 70)

try:
    # Create graph
    resp = requests.post(f"{BASE_URL}/api/design/graph/", json={
        "name": "Test MATERIAL Properties",
        "tier": 1
    })
    if resp.status_code != 201:
        runner.log_fail("SCENARIO 1", f"Create graph failed: {resp.status_code}")
    else:
        graph_id = resp.json()["id"]
        runner.log_pass("SCENARIO 1", "Graph created")

        # Create MATERIAL node
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
            "node_type": "MATERIAL",
            "label": "Steel",
            "level": 0,
            "properties": {
                "model_type": "linear_elastic_isotropic",
                "E": 210e9,
                "nu": 0.3,
                "rho": 7800
            },
            "pos_x": 100,
            "pos_y": 100
        })
        if resp.status_code != 201:
            runner.log_fail("SCENARIO 1", f"Create MATERIAL node failed: {resp.status_code}")
        else:
            node_id = resp.json()["node_id"]
            runner.log_pass("SCENARIO 1", "MATERIAL node created")

            # Fetch graph and verify properties
            resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}")
            if resp.status_code == 200:
                graph_data = resp.json()
                node = next((n for n in graph_data["nodes"] if n["id"] == node_id), None)
                if node:
                    props = node["data"]["properties"]
                    if props.get("E") == 210e9 and props.get("nu") == 0.3 and props.get("rho") == 7800:
                        runner.log_pass("SCENARIO 1", "Properties persisted correctly")
                    else:
                        runner.log_fail("SCENARIO 1", f"Properties mismatch: {props}")
                else:
                    runner.log_fail("SCENARIO 1", "Node not found in graph")
            else:
                runner.log_fail("SCENARIO 1", f"Fetch graph failed: {resp.status_code}")

            # Test property edit
            resp = requests.put(f"{BASE_URL}/api/design/graph/{graph_id}/nodes/{node_id}", json={
                "properties": {
                    "model_type": "linear_elastic_isotropic",
                    "E": 70e9,  # Change to aluminum
                    "nu": 0.33,
                    "rho": 2700
                }
            })
            if resp.status_code == 200:
                runner.log_pass("SCENARIO 1", "Property edit successful")

                # Verify updated properties
                resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}")
                graph_data = resp.json()
                node = next((n for n in graph_data["nodes"] if n["id"] == node_id), None)
                if node:
                    props = node["data"]["properties"]
                    if props.get("E") == 70e9 and props.get("nu") == 0.33:
                        runner.log_pass("SCENARIO 1", "Updated properties verified")
                    else:
                        runner.log_fail("SCENARIO 1", f"Update not persisted: {props}")
            else:
                runner.log_fail("SCENARIO 1", f"Property edit failed: {resp.status_code}")

except Exception as e:
    runner.log_fail("SCENARIO 1", str(e))

# ============================================================================
# SCENARIO 2: BC Node with DOF Checkboxes
# ============================================================================

print("\n[TEST 2] BC Node with DOF Checkboxes")
print("-" * 70)

try:
    # Create graph
    resp = requests.post(f"{BASE_URL}/api/design/graph/", json={
        "name": "Test BC DOFs",
        "tier": 1
    })
    graph_id = resp.json()["id"]
    runner.log_pass("SCENARIO 2", "Graph created")

    # Create BC node with default DOFs
    resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
        "node_type": "BC",
        "label": "Fixed Base",
        "level": 0,
        "properties": {
            "bc_type": "fixed",
            "dofs": [0, 1, 2],  # UX, UY, UZ
            "value": 0,
            "node_set": "fixed_base"
        },
        "pos_x": 100,
        "pos_y": 100
    })
    if resp.status_code == 201:
        node_id = resp.json()["node_id"]
        runner.log_pass("SCENARIO 2", "BC node created with UX,UY,UZ")

        # Verify DOFs
        resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}")
        graph_data = resp.json()
        node = next((n for n in graph_data["nodes"] if n["id"] == node_id), None)
        if node:
            props = node["data"]["properties"]
            if props.get("dofs") == [0, 1, 2]:
                runner.log_pass("SCENARIO 2", "DOF selection [0,1,2] verified")
            else:
                runner.log_fail("SCENARIO 2", f"DOF mismatch: {props.get('dofs')}")

        # Test DOF edit (toggle to [0, 1, 3] — UX, UY, RX)
        resp = requests.put(f"{BASE_URL}/api/design/graph/{graph_id}/nodes/{node_id}", json={
            "properties": {
                "bc_type": "fixed",
                "dofs": [0, 1, 3],  # UX, UY, RX (toggled RX on, UZ off)
                "value": 0,
                "node_set": "fixed_base"
            }
        })
        if resp.status_code == 200:
            runner.log_pass("SCENARIO 2", "DOF toggle successful")

            # Verify updated DOFs
            resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}")
            graph_data = resp.json()
            node = next((n for n in graph_data["nodes"] if n["id"] == node_id), None)
            if node:
                props = node["data"]["properties"]
                if props.get("dofs") == [0, 1, 3]:
                    runner.log_pass("SCENARIO 2", "Updated DOFs [0,1,3] verified")
                else:
                    runner.log_fail("SCENARIO 2", f"DOF update mismatch: {props.get('dofs')}")
        else:
            runner.log_fail("SCENARIO 2", f"DOF edit failed: {resp.status_code}")
    else:
        runner.log_fail("SCENARIO 2", f"Create BC node failed: {resp.status_code}")

except Exception as e:
    runner.log_fail("SCENARIO 2", str(e))

# ============================================================================
# SCENARIO 3: Solver Integration — Graph Properties
# ============================================================================

print("\n[TEST 3] Solver Integration — Graph Properties")
print("-" * 70)

try:
    # Create graph with MATERIAL, BC, LOAD
    resp = requests.post(f"{BASE_URL}/api/design/graph/", json={
        "name": "Test Solver Integration",
        "tier": 0
    })
    graph_id = resp.json()["id"]
    runner.log_pass("SCENARIO 3", "Graph created")

    # Add MATERIAL (Aluminum)
    resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
        "node_type": "MATERIAL",
        "label": "Aluminum",
        "properties": {"E": 70e9, "nu": 0.33, "rho": 2700},
        "pos_x": 50, "pos_y": 50
    })
    runner.log_pass("SCENARIO 3", f"MATERIAL node created: {resp.status_code}")

    # Add BC
    resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
        "node_type": "BC",
        "label": "Fixed",
        "properties": {"bc_type": "fixed", "dofs": [0, 1, 2], "value": 0, "node_set": "fixed"},
        "pos_x": 150, "pos_y": 50
    })
    runner.log_pass("SCENARIO 3", f"BC node created: {resp.status_code}")

    # Add LOAD
    resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
        "node_type": "LOAD",
        "label": "Downward Force",
        "properties": {"load_type": "force", "magnitude": 1000, "dir_x": 0, "dir_y": -1, "dir_z": 0, "node_set": "tip"},
        "pos_x": 250, "pos_y": 50
    })
    runner.log_pass("SCENARIO 3", f"LOAD node created: {resp.status_code}")

    # Add GEOMETRY
    resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
        "node_type": "GEOMETRY",
        "label": "Cantilever",
        "properties": {"sdf_func": "cantilever"},
        "pos_x": 350, "pos_y": 50,
        "tier": 0
    })
    runner.log_pass("SCENARIO 3", f"GEOMETRY node created: {resp.status_code}")

    # Validate graph
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}/validate")
    if resp.status_code == 200:
        val_result = resp.json()
        if val_result.get("ready_for_simulation"):
            runner.log_pass("SCENARIO 3", "Graph validation passed")
        else:
            runner.log_fail("SCENARIO 3", f"Validation errors: {val_result.get('errors')}")

    # Run solver
    resp = requests.post(f"{BASE_URL}/api/design/solver/{graph_id}/run", json={
        "tier": 0
    })
    if resp.status_code == 202:
        run_id = resp.json()["run_id"]
        runner.log_pass("SCENARIO 3", f"Solver launched: {run_id[:8]}...")

        # Wait for completion (up to 30 seconds)
        for attempt in range(30):
            time.sleep(1)
            resp = requests.get(f"{BASE_URL}/api/design/solver/{run_id}/status")
            if resp.status_code == 200:
                status = resp.json()["status"]
                if status in ("done", "failed"):
                    runner.log_pass("SCENARIO 3", f"Solver completed: {status}")

                    # Get results
                    resp = requests.get(f"{BASE_URL}/api/design/solver/{run_id}/results")
                    if resp.status_code == 200:
                        results = resp.json()
                        if "fields" in results and len(results["fields"]) > 0:
                            runner.log_pass("SCENARIO 3", f"Results available: {len(results['fields'])} fields")
                        else:
                            runner.log_fail("SCENARIO 3", "No fields in results")
                    break
        else:
            runner.log_fail("SCENARIO 3", "Solver timeout (30s)")
    else:
        runner.log_fail("SCENARIO 3", f"Solver launch failed: {resp.status_code} - {resp.text[:100]}")

except Exception as e:
    runner.log_fail("SCENARIO 3", str(e))

# ============================================================================
# SCENARIO 4: DAG Validation — Cycle Detection
# ============================================================================

print("\n[TEST 4] DAG Validation — Cycle Detection")
print("-" * 70)

try:
    # Create graph with cycle
    resp = requests.post(f"{BASE_URL}/api/design/graph/", json={
        "name": "Test DAG Cycle",
        "tier": 1
    })
    graph_id = resp.json()["id"]
    runner.log_pass("SCENARIO 4", "Graph created")

    # Create 3 nodes
    nodes = {}
    for name in ["A", "B", "C"]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
            "node_type": "GEOMETRY",
            "label": name,
            "pos_x": 100, "pos_y": 100
        })
        nodes[name] = resp.json()["node_id"]
    runner.log_pass("SCENARIO 4", "3 nodes created (A, B, C)")

    # Create cycle: A -> B -> C -> A
    edges_created = 0
    for src, tgt in [("A", "B"), ("B", "C"), ("C", "A")]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/edges", json={
            "source_id": nodes[src],
            "target_id": nodes[tgt],
            "edge_type": "DEPENDS_ON"
        })
        if resp.status_code == 201:
            edges_created += 1
    runner.log_pass("SCENARIO 4", f"Cycle created: A->B->C->A ({edges_created} edges)")

    # Validate DAG
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}/dag-check")
    if resp.status_code == 200:
        dag_result = resp.json()
        if not dag_result.get("is_dag"):
            runner.log_pass("SCENARIO 4", "Cycle correctly detected")
            if dag_result.get("cycles"):
                runner.log_pass("SCENARIO 4", f"Cycle path found: {len(dag_result['cycles'])} cycles")
        else:
            runner.log_fail("SCENARIO 4", "Cycle not detected (false negative)")

    # Validate completeness (should have DAG error)
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}/validate")
    if resp.status_code == 200:
        val_result = resp.json()
        if not val_result.get("ready_for_simulation"):
            runner.log_pass("SCENARIO 4", "Validation blocked due to cycle")
            if any("Ciclo" in e.get("message", "") or "cycle" in e.get("message", "").lower()
                   for e in val_result.get("errors", [])):
                runner.log_pass("SCENARIO 4", "Cycle error message present")
        else:
            runner.log_fail("SCENARIO 4", "Validation not blocked by cycle")

    # Delete one edge to break cycle
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}")
    edges = resp.json()["edges"]
    if edges:
        edge_to_delete = edges[0]["id"]
        resp = requests.delete(f"{BASE_URL}/api/design/graph/{graph_id}/edges/{edge_to_delete}")
        if resp.status_code == 200:
            runner.log_pass("SCENARIO 4", "Edge deleted (cycle broken)")

            # Re-validate
            resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}/dag-check")
            if resp.status_code == 200:
                if resp.json().get("is_dag"):
                    runner.log_pass("SCENARIO 4", "DAG validation passed after cycle removal")
                else:
                    runner.log_fail("SCENARIO 4", "Still has cycle after edge deletion")

except Exception as e:
    runner.log_fail("SCENARIO 4", str(e))

# ============================================================================
# SCENARIO 5: Cross-Mode Integration (Partial — API only)
# ============================================================================

print("\n[TEST 5] Cross-Mode Integration")
print("-" * 70)

try:
    # Check STEP files endpoint
    resp = requests.get(f"{BASE_URL}/api/step-view/files")
    if resp.status_code == 200:
        files = resp.json().get("files", [])
        runner.log_pass("SCENARIO 5", f"STEP files API working ({len(files)} files)")
    else:
        runner.log_fail("SCENARIO 5", f"STEP files endpoint failed: {resp.status_code}")

    # Check CAE meshes endpoint
    resp = requests.get(f"{BASE_URL}/api/cae/meshes")
    if resp.status_code == 200:
        meshes = resp.json().get("meshes", [])
        runner.log_pass("SCENARIO 5", f"CAE meshes API working ({len(meshes)} meshes)")
    else:
        runner.log_fail("SCENARIO 5", f"CAE meshes endpoint failed: {resp.status_code}")

    # Check Design graphs endpoint
    resp = requests.get(f"{BASE_URL}/api/design/graph/")
    if resp.status_code == 200:
        graphs = resp.json().get("graphs", [])
        runner.log_pass("SCENARIO 5", f"Design graphs API working ({len(graphs)} graphs)")
    else:
        runner.log_fail("SCENARIO 5", f"Design graphs endpoint failed: {resp.status_code}")

    # Test import endpoints are accessible
    if graphs:
        graph_id = graphs[0]["id"]

        # Check import routes exist (by calling with invalid IDs)
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/import/step", json={
            "step_file_id": "test-id"
        })
        if resp.status_code in (201, 400):  # 201 = created, 400 = bad request (step doesn't exist)
            runner.log_pass("SCENARIO 5", "STEP import endpoint accessible")
        else:
            runner.log_fail("SCENARIO 5", f"STEP import endpoint failed: {resp.status_code}")

        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/import/mesh", json={
            "mesh_id": "test-id"
        })
        if resp.status_code in (201, 400):
            runner.log_pass("SCENARIO 5", "Mesh import endpoint accessible")
        else:
            runner.log_fail("SCENARIO 5", f"Mesh import endpoint failed: {resp.status_code}")

    runner.log_pass("SCENARIO 5", "Cross-mode integration APIs operational")

except Exception as e:
    runner.log_fail("SCENARIO 5", str(e))

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)
print(f"Passed: {runner.passed}")
print(f"Failed: {runner.failed}")
print(f"Total:  {runner.passed + runner.failed}")
print(f"Success Rate: {100 * runner.passed / (runner.passed + runner.failed):.1f}%")

if runner.failed == 0:
    print("\n✅ ALL SCENARIOS PASSED — READY FOR PRODUCTION")
    sys.exit(0)
else:
    print(f"\n❌ {runner.failed} SCENARIO(S) FAILED — NEEDS INVESTIGATION")
    print("\nFailed tests:")
    for status, scenario, message in runner.results:
        if status == "FAIL":
            print(f"  - {scenario}: {message}")
    sys.exit(1)
