# Production Readiness Checklist

**Current Status:** Phase 1-3 implemented + tested (API level)  
**Gaps:** UI testing, kernel integration, deployment, monitoring

---

## 🔴 CRITICAL (Must Fix Before Production)

### 1. Kernel Geometry Scoping (Phase 3 Completion)

**What's Missing:**
- `FEMKernel._apply_bcs()` doesn't use `bc['geometry_id']` field
- `FEMKernel._apply_loads()` doesn't use `load['geometry_id']` field
- Multi-geometry solver spec generated but not used

**Impact:** Medium — Phase 1 graphs work, Phase 3 scoping doesn't work

**Fix Needed:**
```python
# In app/design/services/fem/kernel.py
def _apply_bcs(self, K, F, bcs, node_sets_map):
    for bc_spec in bcs:
        geometry_id = bc_spec.get('geometry_id')
        if geometry_id:
            # Only apply to nodes in this geometry's node_set
            node_set = bc_spec['node_set']
            # Filter node_sets_map by geometry
            pass
        else:
            # Apply globally (Phase 1 mode)
            pass
```

**Effort:** 2-3 hours  
**Priority:** HIGH

---

### 2. UI Manual Testing (All 4 Scenarios)

**What's Missing:**
- Drag-drop nodes to canvas (verify no duplication)
- Property editing per node type
- DAG validation overlay
- Solver button + progress display
- Adaptive refinement visualization
- STEP→CAE→Design mode switching

**Impact:** High — Cannot ship without UI validation

**Tests Required:**

✅ **Scenario 1: Node Properties**
- [ ] Drag MATERIAL node → canvas
- [ ] Click node → right panel opens
- [ ] Edit E=70e9, ν=0.33, see preview update
- [ ] Save → property persists
- [ ] Mini-preview shows "E=70.0GPa ν=0.33"

✅ **Scenario 2: BC DOF Checkboxes**
- [ ] Drag BC node → canvas
- [ ] Click node → see 6 DOF checkboxes
- [ ] Toggle UX, UY, UZ (check)
- [ ] Toggle RX, RY (uncheck)
- [ ] Save → dofs=[0,1,2]
- [ ] Preview shows "Fixed [UX,UY,UZ]"

✅ **Scenario 3: Solver Reads Graph**
- [ ] Create MATERIAL, BC, LOAD nodes with properties
- [ ] Click "✓ Validar grafo" → no errors
- [ ] Click "⚡ Simular" → WebSocket progress
- [ ] Wait for completion
- [ ] RESULT node populated with σ_max, δ_max

✅ **Scenario 4: Cross-Mode Integration**
- [ ] STEP mode: upload STEP file
- [ ] Generate mesh → auto-switch to CAE
- [ ] CAE mode: see mesh + Share button
- [ ] Share → creates GEOMETRY node in Design
- [ ] Design mode: GEOMETRY node linked to mesh

✅ **Scenario 5: DAG Validation (NEW)**
- [ ] Create cycle: A→B→C→A
- [ ] Click "Validar grafo"
- [ ] Error overlay shows cycle detected
- [ ] Cannot click "Simular" (blocked)
- [ ] Delete one edge
- [ ] Re-validate → no errors

**Effort:** 2-3 hours  
**Priority:** CRITICAL

---

### 3. Database Migrations in Production

**What's Missing:**
- Automated migration path for source_step_id FK
- Rollback strategy
- Data consistency checks

**Required:**
```bash
# On production database:
flask db migrate
flask db upgrade

# Verify migration:
SELECT column_name FROM information_schema.columns
WHERE table_name='cae_meshes' AND column_name='source_step_id';
```

**Effort:** 1 hour  
**Priority:** HIGH

---

### 4. Environment Configuration

**What's Missing:**
- Production `.env` template
- Database connection (PostgreSQL)
- CORS settings
- Flask secret key
- Upload directories

**Required `.env.production`:**
```bash
FLASK_ENV=production
DATABASE_URL=postgresql://user:pass@prod-db:5432/caedb
SECRET_KEY=<generate-with-secrets-module>
CORS_ORIGINS=https://yourdomain.com
MAX_UPLOAD_SIZE_MB=500
API_PORT=8080
SOLVER_TIMEOUT_SECONDS=3600
GMSH_PATH=/usr/bin/gmsh
```

**Effort:** 30 minutes  
**Priority:** HIGH

---

## 🟡 IMPORTANT (Should Fix Before Production)

### 5. Error Handling & Logging

**What's Missing:**
- Proper exception handling in solver routes
- Database connection error recovery
- File upload validation (size, format)
- Mesh parsing error messages
- WebSocket disconnect handling

**Current Issues:**
```
POST /api/design/solver/<id>/run
- If mesh not found → cryptic error
- If solver crashes → incomplete results
- If WebSocket closes → client doesn't know
```

**Need:**
```python
@bp.route('/<graph_id>/run', methods=['POST'])
def run_simulation(graph_id):
    try:
        graph = DesignGraph.query.get(graph_id)
        if not graph:
            return {'error': 'Graph not found'}, 404
        
        # Validate before starting
        errors = validate_simulation_readiness(graph)
        if errors:
            return {'error': 'Validation failed', 'details': errors}, 422
        
        # Run in background
        task = start_background_task(...)
        return {'task_id': task.id}, 202  # Accepted
        
    except DatabaseError as e:
        logger.error(f"DB error: {e}")
        return {'error': 'Database error'}, 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {'error': 'Internal server error'}, 500
```

**Effort:** 3-4 hours  
**Priority:** HIGH

---

### 6. Performance Optimization

**What's Missing:**
- Database query optimization (N+1 queries)
- Frontend bundle optimization
- Mesh caching strategy
- Solver progress throttling

**Potential Bottlenecks:**
- Large graph queries (fetch all nodes/edges every request)
- Mesh file re-parsing on every GET
- WebSocket updates every iteration (can overflow browser)

**Fixes Needed:**
```python
# 1. Cache mesh parsing (already in CAE, extend to solver)
@functools.lru_cache(maxsize=8)
def load_mesh(mesh_id, mtime):
    return parse_mesh(...)

# 2. Paginate graph queries
GET /api/design/graph/<id>/nodes?page=1&limit=50

# 3. Throttle WebSocket updates (skip non-significant changes)
if iteration % 5 == 0:  # Send every 5th iteration only
    emit('progress', data)
```

**Effort:** 2-3 hours  
**Priority:** MEDIUM

---

### 7. Security

**What's Missing:**
- Input validation on all endpoints
- File upload scanning (malware, max size)
- SQL injection prevention (likely fine with SQLAlchemy, verify)
- CSRF protection (if UI uses forms)
- Rate limiting

**Required Checks:**
```python
# 1. Input validation
def validate_node_properties(node_type, properties):
    if node_type == 'MATERIAL':
        assert 0 < properties['E'] < 1e12
        assert 0 < properties['nu'] < 0.5
    # ...

# 2. File upload validation
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
ALLOWED_MESH_FORMATS = {'.vtu', '.vtk', '.inp', '.bdf', '.msh', ...}
ALLOWED_STEP_FORMATS = {'.stp', '.step', '.p21'}

# 3. Rate limiting
@limiter.limit("100 per hour")
@bp.route('/api/design/solver/<id>/run', methods=['POST'])
def run_simulation(graph_id):
    ...
```

**Effort:** 2-3 hours  
**Priority:** HIGH

---

### 8. Monitoring & Logging

**What's Missing:**
- Application logging (file + syslog)
- Performance metrics (response times, solver duration)
- Error tracking (Sentry, Rollbar)
- Database health checks
- Disk space monitoring (for uploads)

**Recommended Stack:**
- **Logging:** Python `logging` module → Stackdriver/CloudLogging
- **Metrics:** Prometheus + Grafana
- **Error tracking:** Sentry
- **Health checks:** `/health` endpoint

**Minimal Setup:**
```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@bp.route('/health', methods=['GET'])
def health_check():
    try:
        db.session.execute('SELECT 1')
        return {'status': 'ok'}, 200
    except:
        return {'status': 'error'}, 500
```

**Effort:** 2-3 hours  
**Priority:** MEDIUM

---

## 🟢 NICE TO HAVE (Post-Launch)

### 9. Documentation for Users

**Missing:**
- User manual (PDF/website)
- Video tutorials (3-5 min each)
- API documentation (Swagger/OpenAPI)
- Troubleshooting guide

**Quick Start:**
```markdown
# CAE Viewer User Manual

## Getting Started
1. Open http://yourdomain.com
2. Click **Design** tab
3. Create new graph: "+ Nuevo grafo"
4. Drag nodes from toolbar
5. Edit properties in right panel
6. Click "Validar grafo" to check
7. Click "Simular" to run FEM solver

## Keyboard Shortcuts
- Delete: Remove selected node
- Ctrl+S: Save (auto-saved)

## FAQ
Q: What does "Ciclo detectado" mean?
A: Your graph has a cycle (A→B→A). Remove one edge to fix.
```

**Effort:** 4-6 hours  
**Priority:** LOW (can do week 1 post-launch)

---

### 10. Deployment Pipeline

**Missing:**
- GitHub Actions / GitLab CI
- Automated tests on PR
- Docker containers
- Kubernetes deployment
- Blue-green deployment

**Simple GitHub Actions Example:**
```yaml
name: Test & Deploy
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: pytest tests/
      - run: npm run test (frontend)

  deploy:
    if: github.ref == 'refs/heads/main'
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: docker build -t cae-viewer:${{ github.sha }} .
      - run: docker push gcr.io/project/cae-viewer:${{ github.sha }}
      - run: kubectl set image deployment/cae-viewer ...
```

**Effort:** 3-4 hours  
**Priority:** MEDIUM

---

## 📋 Implementation Plan

### Week 1 (Before Launch)

- [ ] **Day 1-2:** Kernel geometry scoping (critical fix)
- [ ] **Day 3:** UI manual testing (4 scenarios + DAG)
- [ ] **Day 4:** Database migrations + environment config
- [ ] **Day 5:** Error handling + basic logging

**Estimated Effort:** 10-12 hours  
**Risk:** Medium (kernel changes, UI edge cases)

### Week 2 (Post-Launch)

- [ ] **Day 1-2:** Security hardening (input validation, rate limiting)
- [ ] **Day 3:** Performance optimization (caching, pagination)
- [ ] **Day 4-5:** Monitoring setup + documentation

**Estimated Effort:** 8-10 hours  
**Risk:** Low (incremental improvements)

---

## 🧪 Test Coverage Before Production

### Backend Tests (Automated)
- [x] API tests: 4 sprint scenarios + 2 Phase 2-3 tests
- [ ] Unit tests: graph_service, solver spec extraction
- [ ] Integration tests: full workflow (graph → solver → results)
- [ ] Error cases: invalid inputs, missing files, solver timeout

### Frontend Tests (Manual)
- [ ] Node CRUD (create, edit, delete, drag-drop)
- [ ] Property editing (all 7 node types)
- [ ] Validation (DAG, completeness)
- [ ] Solver integration (progress, results)
- [ ] Cross-mode switching (Design↔STEP↔CAE)
- [ ] Error handling (invalid files, network errors)

### System Tests (Integration)
- [ ] Upload STEP file → generate mesh → Design graph → solve
- [ ] Large graph (50+ nodes) performance
- [ ] Long-running solver (1+ hour)
- [ ] Concurrent users (5+ simultaneous simulations)

---

## 🚀 Go/No-Go Checklist

**GO if:**
- ✅ Kernel geometry scoping working (multi-geometry test passes)
- ✅ All 5 UI scenarios tested manually
- ✅ Database migrations tested on staging
- ✅ No critical errors in logs
- ✅ Performance acceptable (<2s API response)

**NO-GO if:**
- ❌ Kernel still not using geometry_id
- ❌ UI duplication bug not fixed
- ❌ Solver crashes on large meshes
- ❌ WebSocket drops connection unexpectedly
- ❌ Database migration fails

---

## 📊 Effort Summary

| Task | Priority | Effort | Status |
|------|----------|--------|--------|
| Kernel geometry scoping | 🔴 CRITICAL | 3h | ⬜ TODO |
| UI manual testing | 🔴 CRITICAL | 3h | ⬜ TODO |
| DB migrations | 🔴 CRITICAL | 1h | ⬜ TODO |
| Environment config | 🔴 CRITICAL | 0.5h | ⬜ TODO |
| Error handling | 🟡 IMPORTANT | 4h | ⬜ TODO |
| Security hardening | 🟡 IMPORTANT | 3h | ⬜ TODO |
| Performance tuning | 🟡 IMPORTANT | 3h | ⬜ TODO |
| Monitoring setup | 🟡 IMPORTANT | 2h | ⬜ TODO |
| Documentation | 🟢 NICE | 5h | ⬜ TODO |
| CI/CD pipeline | 🟢 NICE | 4h | ⬜ TODO |
|||||
| **TOTAL** | - | **~29h** | - |

**Timeline:** 1-2 weeks with focused effort

---

## 🎯 Recommendation

### MVP (Week 1)
1. Fix kernel geometry scoping ⚠️ **Critical**
2. Manual UI testing (5 scenarios)
3. Setup monitoring (logs + errors)
4. Database backup procedure
5. **Launch with Phase 1 support only** (no Phase 3 scoping yet)

### Post-Launch Improvements (Week 2-3)
- Phase 3 edge scoping (once kernel fixed)
- Performance optimization
- Documentation
- Security hardening

**Rationale:** Launch Phase 1 fully tested, Phase 3 roadmap item. Users get value immediately while you stabilize in production.

---

## 📞 Questions Before Production

1. **Target deployment:** AWS/GCP/On-premises?
2. **Expected users:** 1? 10? 100+?
3. **Data retention:** How long to keep simulation results?
4. **Backup strategy:** Daily? Hourly?
5. **SLA requirements:** 99.9% uptime?
6. **Compliance:** HIPAA? GDPR? Other?
