#!/usr/bin/env python3
"""Simple Phase 2-3 DAG validation test."""
import requests
import json

BASE_URL = "http://localhost:8080"

print("=== PHASE 2-3 DAG VALIDATION TEST ===\n")

try:
    # 1. Create graph
    print("1. Creating graph...")
    resp = requests.post(f"{BASE_URL}/api/design/graph/", json={
        "name": "DAG Test",
        "tier": 1
    })
    if resp.status_code != 201:
        print(f"ERROR: {resp.text}")
        exit(1)
    graph_id = resp.json()["id"]
    print(f"   OK: Created {graph_id}")

    # 2. Create 3 nodes
    print("\n2. Creating nodes (A, B, C)...")
    nodes = {}
    for name in ["A", "B", "C"]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/nodes", json={
            "node_type": "GEOMETRY",
            "label": name,
            "pos_x": 100,
            "pos_y": 100
        })
        nodes[name] = resp.json()["node_id"]
        print(f"   OK: Created {name}")

    # 3. Create edges: A -> B -> C (no cycle)
    print("\n3. Creating edges (A->B->C, no cycle)...")
    for src, tgt in [("A", "B"), ("B", "C")]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id}/edges", json={
            "source_id": nodes[src],
            "target_id": nodes[tgt],
            "edge_type": "DEPENDS_ON"
        })
        print(f"   OK: {src}->{tgt}")

    # 4. Check DAG
    print("\n4. Checking DAG...")
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id}/dag-check")
    result = resp.json()
    print(f"   is_dag: {result['is_dag']}")
    print(f"   message: {result['message']}")
    print(f"   cycles: {result['cycles']}")

    if result['is_dag']:
        print("\n[PASS] No cycle detected in A->B->C")
    else:
        print("\n[FAIL] False positive: cycle detected where none exists")
        exit(1)

    # 5. Test with cycle: create A -> B -> C -> A
    print("\n5. Creating cycle graph (A->B->C->A)...")
    resp = requests.post(f"{BASE_URL}/api/design/graph/", json={
        "name": "Cycle Test",
        "tier": 1
    })
    graph_id_cycle = resp.json()["id"]

    nodes_cycle = {}
    for name in ["X", "Y", "Z"]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id_cycle}/nodes", json={
            "node_type": "GEOMETRY",
            "label": name,
            "pos_x": 100,
            "pos_y": 100
        })
        nodes_cycle[name] = resp.json()["node_id"]
        print(f"   OK: Created {name}")

    # Create cycle
    print("\n6. Creating cycle edges (X->Y->Z->X)...")
    for src, tgt in [("X", "Y"), ("Y", "Z"), ("Z", "X")]:
        resp = requests.post(f"{BASE_URL}/api/design/graph/{graph_id_cycle}/edges", json={
            "source_id": nodes_cycle[src],
            "target_id": nodes_cycle[tgt],
            "edge_type": "DEPENDS_ON"
        })
        print(f"   OK: {src}->{tgt}")

    # Check DAG (should fail)
    print("\n7. Checking DAG with cycle...")
    resp = requests.get(f"{BASE_URL}/api/design/graph/{graph_id_cycle}/dag-check")
    result = resp.json()
    print(f"   is_dag: {result['is_dag']}")
    print(f"   message: {result['message']}")
    print(f"   cycles: {result['cycles']}")

    if not result['is_dag'] and result['cycles']:
        print("\n[PASS] Cycle correctly detected")
    else:
        print("\n[FAIL] Cycle not detected")
        exit(1)

    print("\n=== ALL TESTS PASSED ===")

except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
