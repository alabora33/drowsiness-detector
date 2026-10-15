# syntax=docker/dockerfile:1

# Exact Python/Debian version, pinned by digest for reproducible builds.
FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Hide MediaPipe/TFLite info and warning lines; errors are still printed.
    GLOG_minloglevel=2

# MediaPipe's native library loads libGLESv2 and libEGL (Debian's libegl1
# depends on Mesa). Inference itself runs on the CPU.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgles2 libegl1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY requirements.txt .
# MediaPipe depends on the GUI build of OpenCV (Qt, libGL, X11). The server
# never opens a window, so replace it with the headless build of the same
# OpenCV version: smaller image, fewer system libraries.
RUN pip install -r requirements.txt \
    && OPENCV_VERSION="$(pip show opencv-contrib-python | sed -n 's/^Version: //p')" \
    && pip uninstall -y opencv-contrib-python \
    && pip install "opencv-contrib-python-headless==${OPENCV_VERSION}"

COPY models/ models/
COPY app/ app/

# Build-time configuration: CONFIG_PATH is a path inside the build context
# (see .dockerignore for what is included). It is validated here, so an
# invalid configuration fails the build instead of the running container.
ARG CONFIG_PATH=configs/default.yaml
COPY ${CONFIG_PATH} /app/config/config.yaml
RUN python -m app.config --check /app/config/config.yaml

# Runtime override: mount another file and point APP_CONFIG at it.
ENV APP_CONFIG=/app/config/config.yaml

ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="drowsiness-detector" \
      org.opencontainers.image.description="Real-time camera drowsiness detection (FastAPI + MediaPipe)" \
      org.opencontainers.image.source="https://github.com/alabora33/drowsiness-detector" \
      org.opencontainers.image.version="${APP_VERSION}" \
      io.github.alabora33.drowsiness-detector.config="${CONFIG_PATH}"

RUN mkdir -p /app/data && chown app:app /app/data
ENV APP_SETTINGS_PATH=/app/data/settings.yaml
USER app
# Default port; must match server.port in the active configuration.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s --retries=3 \
    CMD ["python", "-m", "app.main", "--healthcheck"]
CMD ["python", "-m", "app.main"]
