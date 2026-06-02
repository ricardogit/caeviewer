# Environment Configuration Guide

---

## Overview

CAE Viewer uses environment variables for configuration. Different `.env` files are used for different environments:

| File | Purpose | Use Case |
|------|---------|----------|
| `.env` | Default local development | `python run.py` (main) |
| `.env.local` | Local overrides | Sensitive values, personal settings |
| `.env.example` | Version-controlled template | Reference for development |
| `.env.production` | Production deployment | Server deployment |
| `.env.production.example` | Template for production | Reference for ops team |

---

## Development Setup (Local Machine)

### 1. Copy template to .env

```bash
# Already done if .env exists, but for reference:
cp .env.example .env
```

### 2. Verify .env has required settings

```bash
cat .env
```

Expected minimum content:

```bash
FLASK_ENV=development
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/caedb
SECRET_KEY=dev-secret-key-not-for-production
API_PORT=8080
```

### 3. Override sensitive values in .env.local (NOT committed)

Create `.env.local` for local overrides:

```bash
# .env.local (DO NOT COMMIT)
DATABASE_URL=postgresql://your-username:your-password@localhost:5432/caedb
SECRET_KEY=your-local-secret-key
```

**Why separate .env.local?**
- `.env` is committed to git (templates, defaults)
- `.env.local` is in `.gitignore` (secrets, personal settings)
- `python run.py` loads both (`.env` then `.env.local`)
- `.env.local` values override `.env`

### 4. Verify Configuration

```bash
# Test that environment loads correctly
python -c "
from app import create_app
app = create_app()
print('Database:', app.config['SQLALCHEMY_DATABASE_URI'])
print('Environment:', app.config.get('FLASK_ENV'))
print('Max upload:', app.config.get('MAX_UPLOAD_SIZE_MB', 'not set'))
"
```

Expected output:

```
Database: postgresql://postgres:postgres@localhost:5432/caedb
Environment: development
Max upload: 500
```

### 5. Initialize Database (First Time)

```bash
# Create tables
flask db upgrade

# Verify tables exist
psql -U postgres -d caedb -c "\dt"
```

---

## Production Setup

### 1. Generate Production Environment File

On your production server:

```bash
# Copy template
cp .env.production.example .env.production

# Generate SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"
# Output: abc123def456...
```

### 2. Edit .env.production

```bash
nano /etc/cae-viewer/.env.production  # or your preferred editor
```

Set these values:

```bash
FLASK_ENV=production
DATABASE_URL=postgresql://cae_user:strong_password@db.example.com:5432/caedb
SECRET_KEY=abc123def456...  (generated above)
CORS_ORIGINS=https://yourdomain.com
MAX_UPLOAD_SIZE_MB=500
UPLOAD_DIR=/var/cae-viewer/uploads
SOLVER_TIMEOUT_SECONDS=3600
GMSH_PATH=/usr/bin/gmsh
LOG_LEVEL=INFO
LOG_FILE=/var/log/cae-viewer/app.log
SENTRY_DSN=https://your-sentry-key@sentry.io/project
```

### 3. Secure File Permissions

```bash
# Only app user can read .env.production (contains secrets!)
chmod 600 /etc/cae-viewer/.env.production
chown app-user:app-group /etc/cae-viewer/.env.production

# Verify
ls -l /etc/cae-viewer/.env.production
# Should show: -rw------- (600 permissions)
```

### 4. Create Upload and Log Directories

```bash
# Create directories
sudo mkdir -p /var/cae-viewer/uploads
sudo mkdir -p /var/log/cae-viewer

# Set ownership
sudo chown app-user:app-group /var/cae-viewer/uploads
sudo chown app-user:app-group /var/log/cae-viewer

# Set permissions
sudo chmod 755 /var/cae-viewer/uploads
sudo chmod 755 /var/log/cae-viewer
```

### 5. Initialize Production Database

```bash
# Connect to remote PostgreSQL (SSH tunnel recommended)
ssh -L 5432:db.example.com:5432 server.example.com

# In another terminal:
export DATABASE_URL="postgresql://cae_user:strong_password@localhost:5432/caedb"
flask db upgrade
```

### 6. Start Flask in Production

```bash
# Option A: Gunicorn (recommended)
gunicorn \
  --env-prefix FLASK_ \
  --workers 4 \
  --bind 0.0.0.0:8080 \
  --access-logfile /var/log/cae-viewer/access.log \
  --error-logfile /var/log/cae-viewer/error.log \
  --log-level info \
  "app:create_app()"

# Option B: uWSGI
uwsgi \
  --env-prefix FLASK_ \
  --http 0.0.0.0:8080 \
  --wsgi-file wsgi.py \
  --callable app \
  --processes 4 \
  --logto /var/log/cae-viewer/app.log
```

### 7. Verify Production Deployment

```bash
# Check Flask is running
curl -I http://localhost:8080/api/design/graph/status

# Expected: HTTP/1.1 200 OK

# Check logs
tail -f /var/log/cae-viewer/app.log

# Test database
curl http://localhost:8080/api/design/graph/

# Expected: {"graphs": [], "total": 0}
```

---

## Environment Variables Reference

### Core Settings

| Variable | Default | Example | Notes |
|----------|---------|---------|-------|
| `FLASK_ENV` | `development` | `production` | Controls debug mode, logging |
| `SECRET_KEY` | (required) | `abc123...` | Generate with `secrets` module |
| `API_PORT` | `8080` | `8080` | Port Flask listens on |

### Database

| Variable | Default | Example | Notes |
|----------|---------|---------|-------|
| `DATABASE_URL` | (required) | `postgresql://...` | PostgreSQL connection string |
| `SQLALCHEMY_POOL_SIZE` | `10` | `20` | Connection pool size |
| `SQLALCHEMY_MAX_OVERFLOW` | `10` | `20` | Overflow queue size |

### CORS & Security

| Variable | Default | Example | Notes |
|----------|---------|---------|-------|
| `CORS_ORIGINS` | `*` | `https://domain.com` | Allowed origins (comma-separated) |
| `CORS_ALLOW_CREDENTIALS` | `true` | `true` | Allow cookies in CORS |

### File Uploads

| Variable | Default | Example | Notes |
|----------|---------|---------|-------|
| `MAX_UPLOAD_SIZE_MB` | `500` | `1000` | Maximum file size in MB |
| `UPLOAD_DIR` | `./uploads` | `/var/cae-viewer/uploads` | Upload directory |
| `UPLOAD_CLEANUP_DAYS` | `0` | `30` | Auto-delete old files (0=disabled) |

### Solver

| Variable | Default | Example | Notes |
|----------|---------|---------|-------|
| `SOLVER_TIMEOUT_SECONDS` | `3600` | `7200` | Max solve time (seconds) |
| `SOLVER_TIER_LIMITS` | (built-in) | `30000,600000,6000000,60000000` | DOF limits per tier |
| `GMSH_PATH` | `gmsh` | `/usr/bin/gmsh` | Path to GMSH executable |

### Logging

| Variable | Default | Example | Notes |
|----------|---------|---------|-------|
| `LOG_LEVEL` | `INFO` | `DEBUG` | Minimum log level |
| `LOG_FILE` | (stdout) | `/var/log/cae-viewer/app.log` | Log file path |

### Optional Services

| Variable | Default | Example | Notes |
|----------|---------|---------|-------|
| `SENTRY_DSN` | (disabled) | `https://...@sentry.io/...` | Error tracking (optional) |
| `REDIS_URL` | (disabled) | `redis://localhost:6379/0` | Redis cache (optional) |
| `PROMETHEUS_ENABLED` | `false` | `true` | Metrics endpoint (optional) |

---

## Common Deployment Scenarios

### Scenario A: AWS EC2 + RDS

```bash
# .env.production
FLASK_ENV=production
DATABASE_URL=postgresql://cae_user:password@caedb.abc123.us-east-1.rds.amazonaws.com:5432/caedb
SECRET_KEY=<generated>
CORS_ORIGINS=https://myapp.example.com
UPLOAD_DIR=/mnt/efs/cae-viewer/uploads  # EFS for persistence
GMSH_PATH=/usr/bin/gmsh
SENTRY_DSN=https://key@sentry.io/project
```

### Scenario B: GCP Cloud Run

```bash
# .env.production (via Google Secret Manager)
FLASK_ENV=production
DATABASE_URL=postgresql://postgres:password@/caedb?host=/cloudsql/project:region:instance
SECRET_KEY=<from Secret Manager>
CORS_ORIGINS=https://myapp.run.app
UPLOAD_DIR=/tmp/uploads  # Cloud Run ephemeral storage
GMSH_PATH=/usr/bin/gmsh
```

### Scenario C: Kubernetes Deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cae-viewer
spec:
  template:
    spec:
      containers:
      - name: cae-viewer
        image: cae-viewer:latest
        envFrom:
        - configMapRef:
            name: cae-viewer-config
        - secretRef:
            name: cae-viewer-secrets
        volumeMounts:
        - name: uploads
          mountPath: /var/cae-viewer/uploads
```

```bash
# Create ConfigMap (non-secrets)
kubectl create configmap cae-viewer-config \
  --from-literal=FLASK_ENV=production \
  --from-literal=MAX_UPLOAD_SIZE_MB=500 \
  --from-literal=LOG_LEVEL=INFO

# Create Secret (secrets)
kubectl create secret generic cae-viewer-secrets \
  --from-literal=DATABASE_URL=postgresql://... \
  --from-literal=SECRET_KEY=... \
  --from-literal=SENTRY_DSN=...
```

---

## Troubleshooting

### Database Connection Failed

```bash
# Check DATABASE_URL format
echo $DATABASE_URL

# Test psql connection
psql "$DATABASE_URL"

# Check server is accessible
telnet db.example.com 5432
```

### Upload Directory Permission Denied

```bash
# Check ownership
ls -ld /var/cae-viewer/uploads

# Fix permissions
sudo chown app-user:app-group /var/cae-viewer/uploads
sudo chmod 755 /var/cae-viewer/uploads
```

### SECRET_KEY Not Set

```bash
# Generate new key
python3 -c "import secrets; print(secrets.token_hex(32))"

# Add to .env
echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env.production
```

### CORS Errors in Browser

```bash
# Check CORS_ORIGINS setting
echo $CORS_ORIGINS

# Should match your frontend domain (including https://)
# Wrong: http://localhost:3000 (http, not https)
# Right: https://domain.com
```

---

## Security Best Practices

1. ✅ **Never commit .env.production to git**
   - Add to `.gitignore`
   - Use `git-secrets` or `talisman` to prevent accidents

2. ✅ **Use strong SECRET_KEY** (32+ hex characters)
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

3. ✅ **Restrict .env.production permissions** (600)
   ```bash
   chmod 600 /etc/cae-viewer/.env.production
   ```

4. ✅ **Use separate DB credentials** for production
   - Create `cae_user` with limited permissions
   - Don't use `postgres` superuser account

5. ✅ **Enable HTTPS/TLS** for CORS_ORIGINS
   - Use `https://` not `http://`
   - Get cert from Let's Encrypt (free)

6. ✅ **Rotate secrets periodically**
   - Update SECRET_KEY every 3-6 months
   - Update DB password annually
   - Rotate SENTRY_DSN if compromised

7. ✅ **Monitor logs for suspicious activity**
   - 400 Bad Request (might indicate attack)
   - Connection pooling errors
   - Slow queries

---

## Environment Validation Script

```python
# validate_env.py
import os
from pathlib import Path

required = {
    'FLASK_ENV': ('development', 'production'),
    'DATABASE_URL': None,
    'SECRET_KEY': None,
    'API_PORT': None,
}

warnings = []
errors = []

for var, allowed_values in required.items():
    value = os.getenv(var)
    if not value:
        errors.append(f"Missing: {var}")
    elif allowed_values and value not in allowed_values:
        warnings.append(f"{var}={value} (expected one of {allowed_values})")

if os.getenv('FLASK_ENV') == 'production':
    if len(os.getenv('SECRET_KEY', '')) < 32:
        errors.append("SECRET_KEY too short (min 32 chars)")
    if not os.getenv('CORS_ORIGINS'):
        errors.append("CORS_ORIGINS required for production")

if errors:
    print("ERROR: Environment validation failed")
    for e in errors:
        print(f"  - {e}")
    exit(1)

if warnings:
    print("WARNING: Check these settings")
    for w in warnings:
        print(f"  - {w}")

print("✓ Environment validation passed")
```

Run before deployment:

```bash
python validate_env.py
```

---

## Summary

| Step | Local | Production |
|------|-------|------------|
| 1. Copy template | `.env.example` → `.env` | `.env.production.example` → `.env.production` |
| 2. Edit values | .env.local overrides | Edit .env.production directly |
| 3. Secure | chmod 644 .env | chmod 600 .env.production |
| 4. Create dirs | auto (./uploads) | mkdir + chown |
| 5. Initialize | `flask db upgrade` | `flask db upgrade` (via SSH) |
| 6. Start | `python run.py` | `gunicorn` or `uWSGI` |
| 7. Verify | curl localhost:8080 | curl https://domain.com |
