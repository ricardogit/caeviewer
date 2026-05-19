# CAE Viewer — Production Docker Image
# Stage 1: build the React/Vite frontend
# Stage 2: conda Python env with pythonocc-core + Flask serving the built SPA

# ─── Stage 1: Frontend build ──────────────────────────────────────────────────
FROM node:18-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps

COPY frontend/ ./
RUN npm run build


# ─── Stage 2: Python + OCC + Flask ────────────────────────────────────────────
FROM condaforge/miniforge3:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc g++ \
        postgresql-client \
        netcat-openbsd \
        curl \
        libfltk1.3 \
        libgl1 \
        libglu1-mesa \
        libosmesa6 \
        libxrender1 \
        libxft2 \
        libxext6 \
        libxi6 \
        libxcursor1 \
        libxfixes3 \
        libxrandr2 \
        libxinerama1 \
        libxss1 \
        libfontconfig1 \
        libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pin Python 3.11 + pythonocc-core in one solve
RUN conda install -y -c conda-forge python=3.11 pythonocc-core=7.7.2 \
    && conda clean -afy

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir gunicorn \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source (excluding frontend source — we use the built dist)
COPY app/         /app/app/
COPY config/      /app/config/
COPY run.py       /app/run.py
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

# Copy the built React SPA from stage 1
COPY --from=frontend-builder /frontend/dist /app/frontend/dist

RUN mkdir -p /app/data/uploads /app/data/processed /app/logs

RUN chmod +x /app/docker-entrypoint.sh

RUN useradd -m -u 1001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "4", \
     "--timeout", "300", \
     "--worker-class", "sync", \
     "run:app"]
