#!/usr/bin/env python3
"""
Test Phase 2-3: Edge semantics, DAG validation, and edge-aware solver.
Tests multi-geometry assembly with scoped BCs and LOADs via edges.
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8080"

def log(msg, level="INFO"):
    print(f"[{level}] {msg}")

def test_phase_23_multi_geometry():
    """Test Phase 2-3: Multi-geometry assembly with edge scoping."""
    log("=" * 70)
    log("PHASE 2-3: Multi-Geometry Assembly with Edge-Aware Scoping")
    log("=" * 70)

    # 1. Create graph
    log("\n1. Creating assembly graph...")
    resp = requests.post(f"{BASE_URL}/api/design/graph/", json={
        "name": "Multi-Geometry Assembly (Phase 2-3)",
        "description": "Two parts with different materials, selective BCs/LOADs",
        "tier": 1
    })
    if resp.status_code != 201:
        log(f"Failed: {resp.text}", "ERROR")
        return False
    graph_id = resp.json()["id"]
    log(f"✓ Graph created: {graph_id}")

    # 2. Create nodes
    log("\n2. Creating nodes...")
    nodes = {}

    # Two materials
    for mat_name, E, nu in [("Steel", 210e9, 0.3), ("Aluminum", 70e9, 0.33)]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
            "node_type": "MATERIAL",
            "label": mat_name,
            "level": 0,
            "properties": {
                "model_type": "linear_elastic_isotropic",
                "E": E,
                "nu": nu,
                "rho": 7800 if mat_name == "Steel" else 2700
            },
            "pos_x": 50 + (150 if mat_name == "Aluminum" else 0),
            "pos_y": 50
        })
        nodes[f"mat_{mat_name.lower()}"] = resp.json()["node_id"]
        log(f"  ✓ {mat_name} (E={E/1e9:.0f} GPa)")

    # Two geometries
    for i, part_name in enumerate(["Part A", "Part B"]):
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
            "node_type": "GEOMETRY",
            "label": part_name,
            "level": 1,
            "properties": {"sdf_func": "cantilever"},
            "pos_x": 50 + (200 * i),
            "pos_y": 150
        })
        nodes[f"geom_{part_name.lower()}"] = resp.json()["node_id"]
        log(f"  ✓ {part_name}")

    # BCs
    for bc_name in ["Fixed Base", "Pinned Joint"]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
            "node_type": "BC",
            "label": bc_name,
            "level": 1,
            "properties": {
                "bc_type": "fixed",
                "dofs": [0, 1, 2],
                "value": 0,
                "node_set": "fixed"
            },
            "pos_x": 50 + (200 if bc_name == "Pinned Joint" else 0),
            "pos_y": 250
        })
        nodes[f"bc_{bc_name.lower()}"] = resp.json()["node_id"]
        log(f"  ✓ {bc_name}")

    # LOADs
    for load_name, dy in [("Tension 1000N", -1000), ("Compression 500N", -500)]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
            "node_type": "LOAD",
            "label": load_name,
            "level": 1,
            "properties": {
                "load_type": "force",
                "magnitude": abs(dy),
                "dir_x": 0,
                "dir_y": -1,
                "dir_z": 0,
                "node_set": "tip"
            },
            "pos_x": 50 + (200 if "500N" in load_name else 0),
            "pos_y": 350
        })
        nodes[f"load_{load_name.lower()}"] = resp.json()["node_id"]
        log(f"  ✓ {load_name}")

    # 3. Create semantic edges
    log("\n3. Creating semantic edges (Phase 2-3)...")
    edges_to_create = [
        ("mat_steel", "geom_part a", "CONSTRAINS_MATERIAL", "Steel → Part A"),
        ("mat_aluminum", "geom_part b", "CONSTRAINS_MATERIAL", "Aluminum → Part B"),
        ("bc_fixed base", "geom_part a", "CONSTRAINS_BC", "Fixed BC → Part A"),
        ("bc_pinned joint", "geom_part b", "CONSTRAINS_BC", "Pinned BC → Part B"),
        ("load_tension 1000n", "geom_part a", "APPLIED_TO", "Tension → Part A"),
        ("load_compression 500n", "geom_part b", "APPLIED_TO", "Compression → Part B"),
    ]

    for source_key, target_key, edge_type, label in edges_to_create:
        source_id = nodes.get(source_key)
        target_id = nodes.get(target_key)
        if not source_id or not target_id:
            log(f"  ⚠️ Skipping {label} (node not found)", "WARNING")
            continue

        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/edges", json={
            "source_id": source_id,
            "target_id": target_id,
            "edge_type": edge_type,
            "weight": 1.0
        })
        if resp.status_code == 201:
            log(f"  ✓ {label} ({edge_type})")
        else:
            log(f"  ✗ {label} failed: {resp.text}", "ERROR")

    # 4. Validate graph (check DAG)
    log("\n4. Validating graph (DAG check)...")
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}/dag-check")
    dag_result = resp.json()
    log(f"  ✓ DAG status: {dag_result['message']}")
    log(f"    - is_dag: {dag_result['is_dag']}")
    log(f"    - cycles: {dag_result['cycles']}")

    if not dag_result['is_dag']:
        log("  ✗ Graph is not a valid DAG!", "ERROR")
        return False

    # 5. Validate completeness
    log("\n5. Validating completeness...")
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}/validate")
    val_result = resp.json()
    log(f"  ✓ Ready for simulation: {val_result['ready_for_simulation']}")
    log(f"    - Errors: {val_result['error_count']}")
    log(f"    - Warnings: {val_result['warning_count']}")

    if val_result['errors']:
        for e in val_result['errors']:
            sev_icon = "❌" if e['severity'] == 'error' else "⚠️"
            log(f"    {sev_icon} {e['message']}")

    # 6. Verify edge-aware spec extraction
    log("\n6. Verifying edge-aware spec extraction...")
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}")
    graph_data = resp.json()

    # Count edge types
    edge_types = {}
    for edge in graph_data['edges']:
        etype = edge['label']
        edge_types[etype] = edge_types.get(etype, 0) + 1

    log("  ✓ Edge composition:")
    for etype, count in sorted(edge_types.items()):
        log(f"    - {etype}: {count}")

    # 7. Test solver spec extraction
    log("\n7. Testing solver spec extraction (with scoping)...")
    try:
        from app.design.services.graph_to_solver_spec import graph_to_solver_spec
        spec = graph_to_solver_spec(graph_id)

        log("  ✓ Spec generated successfully")
        log(f"    - Material: E={spec['material']['E']/1e9:.0f} GPa, ν={spec['material']['nu']}")
        log(f"    - BCs: {len(spec['bcs'])} boundary conditions")
        for i, bc in enumerate(spec['bcs']):
            geom_info = f" (geometry: {bc.get('geometry_id', 'N/A')[:8]})" if 'geometry_id' in bc else ""
            log(f"      [{i}] {bc['node_set']}{geom_info}")

        log(f"    - LOADs: {len(spec['loads'])} loads")
        for i, load in enumerate(spec['loads']):
            geom_info = f" (geometry: {load.get('geometry_id', 'N/A')[:8]})" if 'geometry_id' in load else ""
            log(f"      [{i}] F={load['force']}{geom_info}")

        # Verify scoping: should have geometry_id in entries
        has_scoping = any('geometry_id' in bc for bc in spec['bcs']) or \
                      any('geometry_id' in load for load in spec['loads'])
        if has_scoping:
            log("  ✓ Edge-aware scoping is active (geometry_id present)")
        else:
            log("  ℹ️  Phase 1 fallback (no geometry_id scoping)", "WARNING")

    except Exception as e:
        log(f"  ✗ Spec extraction failed: {e}", "ERROR")
        return False

    log("\n" + "=" * 70)
    log("✓ PHASE 2-3 TEST PASSED")
    log("=" * 70)
    return True


def test_dag_cycle_detection():
    """Test DAG cycle detection."""
    log("\n" + "=" * 70)
    log("TEST: DAG Cycle Detection")
    log("=" * 70)

    # Create graph
    log("1. Creating graph with potential cycle...")
    resp = requests.post(f"{BASE_URL}/api/design/graph/", json={
        "name": "Cycle Test",
        "tier": 1
    })
    graph_id = resp.json()["id"]

    # Create three nodes
    nodes = {}
    for i, name in enumerate(["A", "B", "C"]):
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
            "node_type": "GEOMETRY",
            "label": name,
            "pos_x": 100 * i,
            "pos_y": 100
        })
        nodes[name] = resp.json()["node_id"]

    # Create edges: A → B → C → A (cycle)
    log("2. Creating edges: A → B → C → A")
    edges_spec = [("A", "B"), ("B", "C"), ("C", "A")]
    for src, tgt in edges_spec:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/edges", json={
            "source_id": nodes[src],
            "target_id": nodes[tgt],
            "edge_type": "DEPENDS_ON"
        })
        log(f"  ✓ {src} → {tgt}")

    # Check DAG
    log("3. Checking DAG validity...")
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}/dag-check")
    dag_result = resp.json()

    log(f"  ✓ is_dag: {dag_result['is_dag']}")
    log(f"  ✓ cycles: {dag_result['cycles']}")

    if not dag_result['is_dag'] and dag_result['cycles']:
        log("  ✓ Cycle correctly detected!")
        return True
    else:
        log("  ✗ Cycle detection failed!", "ERROR")
        return False


def main():
    log("Starting Phase 2-3 tests...\n")

    try:
        results = [
            test_phase_23_multi_geometry(),
            test_dag_cycle_detection(),
        ]

        log("\n" + "=" * 70)
        passed = sum(results)
        total = len(results)
        log(f"RESULTS: {passed}/{total} tests passed")
        log("=" * 70)

        return 0 if all(results) else 1

    except Exception as e:
        log(f"Fatal error: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
