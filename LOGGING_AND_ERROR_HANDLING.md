# Logging & Error Handling Guide

---

## Overview

This document describes the logging and error handling improvements made for production readiness.

---

## What Was Implemented

### 1. Enhanced Error Handling in Solver Routes

**File:** `app/design/api/solver_routes.py`

#### Improvements:

**run_simulation() endpoint:**
- ✅ Validate graph exists (404 if not found)
- ✅ Parse request JSON safely (400 if invalid)
- ✅ Validate tier parameter (422 if invalid)
- ✅ Read graph spec with error recovery
- ✅ Validate tier from spec
- ✅ Create database record with error handling
- ✅ Launch solver thread with exception wrapping
- ✅ Top-level try/catch for unexpected errors (500)
- ✅ Detailed logging at each step

**run_status() endpoint:**
- ✅ Check if run exists (404)
- ✅ Return full status with error details
- ✅ Try/catch for database queries

**run_results() endpoint:**
- ✅ Check run status (202 if still running, 200 if done/failed)
- ✅ Handle failed runs gracefully
- ✅ Check if results file exists
- ✅ Partial results if HDF5 read fails
- ✅ Field-by-field error handling
- ✅ Detailed error messages in response

---

## Logging Strategy

### Log Levels

```python
logger.debug()    # Detailed debugging info (disabled in production)
logger.info()     # Normal operations: requests, completions
logger.warning()  # Potentially problematic: missing files, fallbacks
logger.error()    # Errors: exceptions, invalid inputs, failures
logger.critical() # System-level: DB down, disk full, etc.
```

### Example Log Messages

```python
# INFO: Normal operation
logger.info(f"Launched simulation run {run_id} for graph {graph_id}")

# WARNING: Non-fatal issue
logger.warning(f"Could not read graph spec for {graph_id}: {e}")
logger.warning(f"No boundary conditions for run {graph_id}")

# ERROR: Exception that was handled
logger.error(f"Failed to create SimulationRun record: {e}")
logger.error(f"Invalid tier: {e}")

# ERROR with traceback: Unexpected exception
logger.error(f"Unexpected error in run_simulation: {e}", exc_info=True)
```

### Production Logging Setup

**In .env.production:**

```bash
LOG_LEVEL=INFO                    # Don't log DEBUG in production
LOG_FILE=/var/log/cae-viewer/app.log
```

**Python logging configuration:**

```python
# In app/__init__.py or config
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('/var/log/cae-viewer/app.log'),
        logging.StreamHandler()  # Also to stdout for Docker
    ]
)
```

---

## Error Response Format

### Success (202 Accepted)

```json
{
  "run_id": "abc123...",
  "hash": "def456",
  "status": "queued",
  "graph_id": "xyz789..."
}
```

### Client Error (400 Bad Request)

```json
{
  "error": "Invalid JSON in request body"
}
```

### Client Error (404 Not Found)

```json
{
  "error": "Graph not found",
  "graph_id": "abc123"
}
```

### Client Error (422 Unprocessable Entity)

```json
{
  "error": "Tier must be 0-3",
  "got": 5
}
```

### Still Processing (202 Accepted)

```json
{
  "error": "Run not complete",
  "run_id": "abc123",
  "status": "running",
  "message": "Run is still running. Check back later."
}
```

### Run Failed (200 OK with failed status)

```json
{
  "run_id": "abc123",
  "status": "failed",
  "error_message": "Tier limit exceeded: 6.5M DOF > 6M (Tier 2)",
  "wall_time_s": 45.2
}
```

### Server Error (500 Internal Server Error)

```json
{
  "error": "Internal server error",
  "detail": "database connection refused"
}
```

---

## HTTP Status Codes Used

| Code | Meaning | Use Case |
|------|---------|----------|
| 200 | OK | Get results, run completed/failed |
| 202 | Accepted | Simulation queued/running |
| 400 | Bad Request | Invalid JSON, malformed input |
| 404 | Not Found | Graph/run doesn't exist |
| 409 | Conflict | Run still processing (deprecated) |
| 422 | Unprocessable | Invalid parameters (e.g., tier) |
| 500 | Server Error | Unexpected exceptions |

---

## Best Practices for Callers

### Polling for Results

```javascript
// Frontend code
async function pollResults(runId) {
  let status = 'running';
  let attempts = 0;
  const maxAttempts = 120; // 2 hours with 60s interval
  
  while (status !== 'done' && status !== 'failed' && attempts < maxAttempts) {
    try {
      const response = await fetch(`/api/design/solver/${runId}/results`);
      
      if (response.status === 202) {
        // Still processing
        const data = await response.json();
        console.log(`Simulation still ${data.status}...`);
        await sleep(60000); // Wait 60 seconds
        attempts++;
      } else if (response.status === 200) {
        const data = await response.json();
        status = data.status;
        
        if (status === 'done') {
          return data;  // Success
        } else if (status === 'failed') {
          throw new Error(data.error_message);
        }
      } else {
        throw new Error(`Unexpected status: ${response.status}`);
      }
    } catch (error) {
      console.error(`Error polling results: ${error}`);
      await sleep(10000);  // Backoff
    }
  }
  
  throw new Error('Simulation timeout after 2 hours');
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
```

---

## Debugging Checklist

### Run Started but No Progress

```bash
# Check logs for errors
tail -f /var/log/cae-viewer/app.log | grep "run_id"

# Check WebSocket connection
# (Browser DevTools → Network → WS)

# Check solver thread
ps aux | grep solver
```

### Run Failed

```bash
# Check database record
psql $DATABASE_URL -c "SELECT * FROM simulation_runs WHERE id='run-id';"

# Check error message
curl http://localhost:8080/api/design/solver/run-id/status

# Check logs
tail -100 /var/log/cae-viewer/app.log | grep "run-id"
```

### Results Not Available

```bash
# Check if HDF5 file exists
ls -lh data/solver/run-id.h5

# Check file permissions
stat data/solver/run-id.h5

# Check if file is being written
lsof data/solver/run-id.h5
```

---

## Monitoring & Alerting (Optional)

### Metrics to Track

```python
# In production setup (Prometheus/Datadog):
- solver_runs_total (counter: queued, running, done, failed)
- solver_duration_seconds (histogram: track solve times)
- solver_errors_total (counter: tier exceeded, timeout, etc.)
- solver_queue_depth (gauge: how many runs waiting)
- api_response_time (histogram: by endpoint)
- db_connection_errors (counter: connection failures)
```

### Alerts to Set Up

```
1. Error rate > 5% for 5 minutes
   → Page on-call

2. Solver queue depth > 10
   → Warning: system overloaded

3. Disk space < 10% (solver results directory)
   → Urgent: clean up old results

4. Database connection pool exhausted
   → Critical: service down

5. Solver timeout rate > 10%
   → Warning: increase timeout or resources
```

---

## Configuration Examples

### Development (.env)

```bash
LOG_LEVEL=DEBUG
LOG_FILE=./logs/app.log
FLASK_ENV=development
```

### Staging (.env.staging)

```bash
LOG_LEVEL=INFO
LOG_FILE=/var/log/cae-viewer/app.log
FLASK_ENV=production
SENTRY_DSN=https://key@sentry.io/staging-project
```

### Production (.env.production)

```bash
LOG_LEVEL=WARNING              # Only warnings and errors
LOG_FILE=/var/log/cae-viewer/app.log
FLASK_ENV=production
SENTRY_DSN=https://key@sentry.io/production-project
SOLVER_TIMEOUT_SECONDS=3600
```

---

## Testing Error Paths

### Test Invalid Graph

```bash
curl -X POST http://localhost:8080/api/design/solver/invalid-id/run \
  -H "Content-Type: application/json" \
  -d '{"tier": 1}'

# Expected: 404 {"error": "Graph not found", "graph_id": "invalid-id"}
```

### Test Invalid JSON

```bash
curl -X POST http://localhost:8080/api/design/solver/graph-id/run \
  -H "Content-Type: application/json" \
  -d '{invalid json}'

# Expected: 400 {"error": "Invalid JSON in request body"}
```

### Test Invalid Tier

```bash
curl -X POST http://localhost:8080/api/design/solver/graph-id/run \
  -H "Content-Type: application/json" \
  -d '{"tier": 5}'

# Expected: 422 {"error": "Tier must be 0-3", "got": 5}
```

### Test Polling Results

```bash
# Start a run
RUN_ID=$(curl -X POST http://localhost:8080/api/design/solver/graph-id/run -s | jq -r .run_id)

# Check status (should be queued/running initially)
curl http://localhost:8080/api/design/solver/$RUN_ID/status

# Poll results (will return 202 if still running)
curl http://localhost:8080/api/design/solver/$RUN_ID/results

# After completion (will return 200 with results)
curl http://localhost:8080/api/design/solver/$RUN_ID/results
```

---

## Summary of Changes

### Before (Limited Error Handling)

```python
def run_simulation(graph_id):
    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404
    
    data = request.get_json() or {}
    # ... rest of code with minimal error handling
```

**Problems:**
- ❌ Silent failures (no logging)
- ❌ Invalid JSON crashes
- ❌ No parameter validation
- ❌ Database errors not caught
- ❌ Thread exceptions hidden

### After (Production-Ready Error Handling)

```python
def run_simulation(graph_id):
    try:
        # Validate input
        validate_graph(graph_id)
        validate_json()
        validate_tier()
        
        # Extract spec with error recovery
        spec = extract_spec_safely(graph_id)
        
        # Create record with transaction safety
        record = create_record_safely(spec)
        
        # Launch thread with exception wrapping
        thread = launch_solver_safely(record)
        
        logger.info(f"Launched {record.id}")
        return success_response(record), 202
        
    except ValidationError as e:
        logger.warning(f"Validation failed: {e}")
        return error_response(e), 422
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return error_response(e), 500
```

**Benefits:**
- ✅ All errors logged
- ✅ Graceful handling of invalid input
- ✅ Parameter validation
- ✅ Database transaction safety
- ✅ Thread exceptions caught
- ✅ Helpful error messages
- ✅ Correct HTTP status codes

---

## Rollout Plan

### Phase 1 (Today)
- ✅ Deploy improved solver_routes.py
- ✅ Monitor logs for any issues
- ✅ Test error paths manually

### Phase 2 (Tomorrow)
- [ ] Add similar improvements to CAE/STEP routes (if time)
- [ ] Set up log rotation (logrotate)
- [ ] Verify logging to file works

### Phase 3 (Week 2)
- [ ] Setup Sentry (error tracking)
- [ ] Setup Prometheus (metrics)
- [ ] Create alerting rules

---

## Files Modified

- `app/design/api/solver_routes.py` — Enhanced error handling + logging

## Files Created

- `LOGGING_AND_ERROR_HANDLING.md` — This guide
