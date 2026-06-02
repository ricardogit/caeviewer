# Production Deployment Guide

**Status:** Ready to deploy  
**Phase:** Phase 1 Launch  
**Date:** June 1, 2026

---

## Prerequisites

Before starting deployment, ensure you have:

- [ ] Server with Ubuntu 20.04+ or equivalent
- [ ] PostgreSQL 12+ installed and running
- [ ] Python 3.9+
- [ ] Node.js 16+
- [ ] Git installed
- [ ] SSH access to production server
- [ ] Domain name configured
- [ ] SSL certificate (Let's Encrypt recommended)

---

## Quick Deployment (30 minutes)

### Step 1: Prepare Server (5 min)

```bash
# SSH to your production server
ssh user@your-production-server.com

# Create application directory
sudo mkdir -p /var/cae-viewer /var/log/cae-viewer
sudo chown $USER:$USER /var/cae-viewer /var/log/cae-viewer

# Create uploads directory
mkdir -p /var/cae-viewer/uploads
mkdir -p /var/cae-viewer/data/solver

# Set permissions
chmod 755 /var/cae-viewer /var/log/cae-viewer
```

### Step 2: Clone Repository (5 min)

```bash
cd /var/cae-viewer
git clone https://github.com/your-org/cae-viewer.git .
```

### Step 3: Install Dependencies (10 min)

```bash
# Backend
pip install -r requirements.txt

# Frontend
cd frontend
npm install
npm run build
cd ..
```

### Step 4: Configure Environment (5 min)

```bash
# Copy template
cp .env.production.example .env.production

# Edit configuration (use nano, vi, or your editor)
nano .env.production

# Must set:
# - DATABASE_URL=postgresql://...
# - SECRET_KEY=<generated-with-secrets-module>
# - CORS_ORIGINS=https://yourdomain.com
# - API_PORT=8080
```

### Step 5: Initialize Database (3 min)

```bash
# Run migrations
flask db upgrade

# Verify tables created
psql $DATABASE_URL -c "\dt"
```

### Step 6: Verify Installation (2 min)

```bash
# Test API endpoint
curl -s http://localhost:8080/api/design/graph/status | head -20

# Expected output:
# {
#   "module": "design.graph",
#   "status": "ok",
#   ...
# }
```

### Step 7: Start Service (Systemd)

**Create service file:**

```bash
sudo tee /etc/systemd/system/cae-viewer.service > /dev/null <<EOF
[Unit]
Description=CAE Viewer Application
After=network.target postgresql.service

[Service]
Type=notify
User=cae-viewer
WorkingDirectory=/var/cae-viewer
EnvironmentFile=/var/cae-viewer/.env.production
ExecStart=/usr/local/bin/gunicorn \
  --workers 4 \
  --bind 0.0.0.0:8080 \
  --timeout 600 \
  --access-logfile /var/log/cae-viewer/access.log \
  --error-logfile /var/log/cae-viewer/error.log \
  "app:create_app()"
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable cae-viewer
sudo systemctl start cae-viewer

# Check status
sudo systemctl status cae-viewer
```

### Step 8: Configure Nginx Reverse Proxy

```bash
sudo tee /etc/nginx/sites-available/cae-viewer > /dev/null <<EOF
upstream cae_viewer {
    server 127.0.0.1:8080;
}

server {
    listen 80;
    listen [::]:80;
    server_name yourdomain.com;

    # Redirect HTTP to HTTPS
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name yourdomain.com;

    # SSL configuration (replace with your cert paths)
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    # Client upload limit
    client_max_body_size 500M;

    # Proxy to Flask
    location / {
        proxy_pass http://cae_viewer;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Static files (optional, if needed)
    location /static/ {
        alias /var/cae-viewer/frontend/dist/;
        expires 30d;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/cae-viewer /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Step 9: Obtain SSL Certificate (2 min)

```bash
# Install Certbot (if not already installed)
sudo apt-get install certbot python3-certbot-nginx

# Get certificate (automatic with Nginx)
sudo certbot --nginx -d yourdomain.com
```

### Step 10: Verify Deployment (3 min)

```bash
# Check service status
sudo systemctl status cae-viewer

# Check logs
tail -f /var/log/cae-viewer/error.log

# Test HTTPS endpoint
curl -s https://yourdomain.com/api/design/graph/status | head -20

# Expected: Same JSON response as HTTP test
```

---

## Post-Deployment Checklist

### Monitoring (Day 1)

```bash
# Watch logs for errors
watch 'tail -20 /var/log/cae-viewer/error.log'

# Check service health
watch 'systemctl status cae-viewer'

# Monitor disk usage
watch 'du -sh /var/cae-viewer/uploads /var/cae-viewer/data/solver'
```

### Database Backup

```bash
# Daily backup (add to crontab)
0 2 * * * /usr/bin/pg_dump $DATABASE_URL | gzip > /backup/cae-viewer-$(date +\%Y\%m\%d).sql.gz

# Test restore
pg_restore -d test_caedb /backup/cae-viewer-20260601.sql.gz
```

### Log Rotation

```bash
# Create logrotate config
sudo tee /etc/logrotate.d/cae-viewer > /dev/null <<EOF
/var/log/cae-viewer/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 cae-viewer cae-viewer
    sharedscripts
    postrotate
        systemctl reload cae-viewer > /dev/null 2>&1 || true
    endscript
}
EOF
```

### Health Check Script

```bash
# Create health check
cat > /usr/local/bin/cae-viewer-health-check.sh <<'EOF'
#!/bin/bash
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/design/graph/status)
if [ "$STATUS" != "200" ]; then
    echo "CAE Viewer health check failed: $STATUS"
    systemctl restart cae-viewer
    exit 1
fi
echo "CAE Viewer OK"
exit 0
EOF

chmod +x /usr/local/bin/cae-viewer-health-check.sh

# Add to crontab (every 5 minutes)
*/5 * * * * /usr/local/bin/cae-viewer-health-check.sh
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u cae-viewer -n 50

# Check Python/dependencies
python -c "from app import create_app; print('App imports OK')"

# Check port is available
netstat -tuln | grep 8080
```

### Database Connection Failed

```bash
# Test connection
psql $DATABASE_URL -c "SELECT 1;"

# Check credentials
echo $DATABASE_URL

# Verify PostgreSQL is running
sudo systemctl status postgresql
```

### High CPU/Memory Usage

```bash
# Check process
ps aux | grep gunicorn

# Increase workers if needed (edit .env.production)
# Current: 4 workers
# For 8+ CPU: 8-12 workers
# Restart service: sudo systemctl restart cae-viewer
```

### WebSocket Connection Issues

```bash
# Test WebSocket connection
wscat -c ws://yourdomain.com/socket.io/

# Check Nginx proxy headers
curl -v http://localhost:8080/api/design/graph/status 2>&1 | grep -i upgrade
```

---

## Rollback Procedure

If something goes wrong:

```bash
# 1. Stop service
sudo systemctl stop cae-viewer

# 2. Revert code
cd /var/cae-viewer
git revert HEAD  # or git reset --hard previous-commit

# 3. Downgrade database (if schema changed)
flask db downgrade

# 4. Restart service
sudo systemctl start cae-viewer

# 5. Verify
curl -s https://yourdomain.com/api/design/graph/status
```

---

## First-Time Usage

1. **Access application:** https://yourdomain.com
2. **Test Design mode:**
   - Click "Design" chip
   - Create new graph
   - Drag 3-4 nodes to canvas
   - Click "Validar grafo" (validate)
   - Should see "Grafo válido"
3. **Test Solver:**
   - Create MATERIAL (E=210e9, ν=0.3)
   - Create BC (fixed)
   - Create LOAD (1000N down)
   - Create GEOMETRY (cantilever)
   - Click "Simular" (Solver button)
   - Wait for results (~10 seconds)
   - Should see RESULT node with stress/displacement

---

## Production Environment Variables

Required in `.env.production`:

```bash
# Core
FLASK_ENV=production
SECRET_KEY=<generated-with-secrets-module>
API_PORT=8080

# Database
DATABASE_URL=postgresql://user:password@host:5432/caedb

# Security
CORS_ORIGINS=https://yourdomain.com

# Files
MAX_UPLOAD_SIZE_MB=500
UPLOAD_DIR=/var/cae-viewer/uploads

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/cae-viewer/app.log

# Solver
SOLVER_TIMEOUT_SECONDS=3600
GMSH_PATH=/usr/bin/gmsh

# Optional
SENTRY_DSN=<sentry-url>  # Error tracking
PROMETHEUS_ENABLED=false  # Metrics
```

---

## Scaling (Later)

If you need to scale:

1. **Add more gunicorn workers:** Increase `--workers` in systemd service
2. **Use load balancer:** Deploy multiple app instances behind Nginx
3. **Use Redis for caching:** Set `REDIS_URL` in `.env.production`
4. **Separate solver queue:** Move solver to separate worker process

---

## Support & Monitoring

### Daily Health Checks

```bash
# 1. Application running
curl -s https://yourdomain.com/api/design/graph/status

# 2. Database accessible
psql $DATABASE_URL -c "SELECT COUNT(*) FROM design_graphs;"

# 3. Uploads directory has space
du -sh /var/cae-viewer/uploads

# 4. No error spikes in logs
grep -c ERROR /var/log/cae-viewer/error.log
```

### Weekly Maintenance

- [ ] Database backup tested
- [ ] Log files rotated
- [ ] SSL certificate renewal (auto with certbot)
- [ ] System updates (`apt update && apt upgrade`)

---

## Emergency Contacts

- **Application logs:** `/var/log/cae-viewer/error.log`
- **Database:** See `.env.production` for credentials
- **Reverse proxy:** `/etc/nginx/sites-available/cae-viewer`
- **Service:** `sudo systemctl status cae-viewer`

---

## Timeline

**Estimated time:** 30 minutes for full deployment  
**Go-live:** After Step 10 verification  
**Post-launch monitoring:** First 24 hours critical

---

## Success Criteria

✅ Deployment successful when:
- [ ] API endpoint returns 200: `curl https://yourdomain.com/api/design/graph/status`
- [ ] Frontend loads: https://yourdomain.com
- [ ] Can create graph and nodes
- [ ] Solver launches and completes
- [ ] No errors in `/var/log/cae-viewer/error.log`
- [ ] Database accessible and contains data

---

**Ready to deploy? Follow the Quick Deployment section above.** 🚀
