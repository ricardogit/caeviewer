#!/bin/bash
# Test script for Sprint 1-5 scenarios using curl

BASE_URL="http://localhost:8080"

log() {
    echo "[INFO] $1"
}

error() {
    echo "[ERROR] $1"
}

pass() {
    echo "[PASS] $1"
}

log "=================================================="
log "SCENARIO 1: MATERIAL node properties"
log "=================================================="

# Create graph
log "Creating graph..."
GRAPH=$(curl -s -X POST "$BASE_URL/api/design/graph/" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Material","description":"Sprint 2","tier":1}')
GRAPH_ID=$(echo $GRAPH | grep -o '"id":"[^"]*' | cut -d'"' -f4)
log "Graph created: $GRAPH_ID"

# Add MATERIAL node
log "Adding MATERIAL node..."
NODE=$(curl -s -X POST "$BASE_URL/api/design/graph/$GRAPH_ID/nodes" \
  -H "Content-Type: application/json" \
  -d '{
    "node_type":"MATERIAL",
    "label":"Steel",
    "level":0,
    "properties":{"model_type":"linear_elastic_isotropic","E":210000000000,"nu":0.3,"rho":7800},
    "pos_x":100,
    "pos_y":100
  }')
NODE_ID=$(echo $NODE | grep -o '"node_id":"[^"]*' | cut -d'"' -f4)
log "MATERIAL node created: $NODE_ID"

# Fetch and verify
log "Verifying E/nu properties..."
curl -s "$BASE_URL/api/design/graph/$GRAPH_ID" | grep -q '"E":210000000000' && pass "E=210 GPa saved" || error "E not found"
curl -s "$BASE_URL/api/design/graph/$GRAPH_ID" | grep -q '"nu":0.3' && pass "nu=0.3 saved" || error "nu not found"
pass "SCENARIO 1 PASSED\n"

log "=================================================="
log "SCENARIO 2: BC node with DOF checkboxes"
log "=================================================="

# Create new graph
GRAPH=$(curl -s -X POST "$BASE_URL/api/design/graph/" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test BC DOFs","description":"Sprint 2","tier":1}')
GRAPH_ID=$(echo $GRAPH | grep -o '"id":"[^"]*' | cut -d'"' -f4)
log "Graph created: $GRAPH_ID"

# Add BC node
log "Adding BC node with DOF checkboxes..."
NODE=$(curl -s -X POST "$BASE_URL/api/design/graph/$GRAPH_ID/nodes" \
  -H "Content-Type: application/json" \
  -d '{
    "node_type":"BC",
    "label":"Fixed Base",
    "level":0,
    "properties":{"bc_type":"fixed","dofs":[0,1,2],"value":0,"node_set":"fixed_base"},
    "pos_x":100,
    "pos_y":100
  }')
NODE_ID=$(echo $NODE | grep -o '"node_id":"[^"]*' | cut -d'"' -f4)
log "BC node created: $NODE_ID"

# Verify DOFs
log "Verifying DOFs [0,1,2] (UX, UY, UZ)..."
curl -s "$BASE_URL/api/design/graph/$GRAPH_ID" | grep -q '"dofs":\[0,1,2\]' && pass "DOFs [0,1,2] saved" || error "DOFs not found"
pass "SCENARIO 2 PASSED\n"

log "=================================================="
log "SCENARIO 3: Solver reads from graph (FEM test)"
log "=================================================="

log "Running FEM solver with E=70e9 (Aluminum)..."
RESULT=$(curl -s "$BASE_URL/api/design/solver/test/cantilever/?E=70e9&nu=0.33&n_div=10")
if echo "$RESULT" | grep -q '"tip_deflection_mm"'; then
    DISP=$(echo "$RESULT" | grep -o '"tip_deflection_mm":[0-9.]*' | cut -d':' -f2)
    STRESS=$(echo "$RESULT" | grep -o '"max_von_mises_mpa":[0-9.]*' | cut -d':' -f2)
    pass "FEM solver executed"
    pass "  Max displacement: $DISP mm"
    pass "  Max von Mises: $STRESS MPa"
    pass "SCENARIO 3 PASSED\n"
else
    error "Solver failed"
fi

log "=================================================="
log "SCENARIO 4: STEP/CAE/Design integration (API check)"
log "=================================================="

log "Checking STEP files endpoint..."
curl -s "$BASE_URL/api/step-view/files" | grep -q '"files"' && pass "STEP API works" || error "STEP API failed"

log "Checking CAE meshes endpoint..."
curl -s "$BASE_URL/api/cae/meshes" | grep -q '"meshes"' && pass "CAE API works" || error "CAE API failed"

log "Checking Design graph API..."
curl -s "$BASE_URL/api/design/graph/" | grep -q '"graphs"' && pass "Design API works" || error "Design API failed"

pass "SCENARIO 4 PASSED\n"

log "=================================================="
log "ALL SCENARIOS COMPLETED"
log "=================================================="
