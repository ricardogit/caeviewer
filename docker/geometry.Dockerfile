# CAE Viewer — geometry/mesh base image (Fase 0)
#
# Shared by the geometry worker, the mesh worker and offline tools (face-bridge spike).
# pythonocc-core comes from conda-forge (not pip). Gmsh comes from the pip wheel,
# which bundles its own OCCT — this is intentional: the OCC->Gmsh bridge exchanges
# BREP files and matches faces by geometric signature, so the two OCCT builds
# never need to match.
#
# Build:  docker build -f docker/geometry.Dockerfile -t caeviewer-geometry:latest .

FROM mambaorg/micromamba:1.5-jammy

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglu1-mesa libgl1 libxrender1 libxcursor1 libxft2 libxinerama1 \
        libxext6 libxi6 libxfixes3 libxrandr2 libfontconfig1 libfreetype6 \
        netcat-openbsd postgresql-client \
    && rm -rf /var/lib/apt/lists/*
USER $MAMBA_USER

RUN micromamba install -y -n base -c conda-forge \
        python=3.11 pythonocc-core=7.7.2 numpy \
    && micromamba clean -afy

ARG MAMBA_DOCKERFILE_ACTIVATE=1
COPY --chown=$MAMBA_USER:$MAMBA_USER requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOME=/tmp

# Shared data volumes are owned by uid 1001 (same as `appuser` in the web image),
# so web and workers can read each other's files. Compose runs workers as 1001.
USER root
RUN mkdir -p /app/data/uploads /app/data/processed /app/data/solver /app/data/design \
             /app/data/rom /app/data/jobs /app/logs \
    && chown -R 1001:1001 /app/data /app/logs
USER $MAMBA_USER

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER app/    /app/app/
COPY --chown=$MAMBA_USER:$MAMBA_USER config/ /app/config/
COPY --chown=$MAMBA_USER:$MAMBA_USER tools/  /app/tools/

# Default: generic worker. Override queues with WORKER_QUEUES or --queues.
CMD ["python", "-m", "app.jobs.worker"]
