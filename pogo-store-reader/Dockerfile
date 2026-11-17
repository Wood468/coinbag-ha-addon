# The base is expected to be Playwright's image, but the build does not rely on it: it installs the
# pinned Playwright package and Chromium (with OS deps) into the python3 that reader.py runs under,
# then fails the build if import or launch does not work.
ARG BUILD_FROM=mcr.microsoft.com/playwright/python:v1.49.0-jammy
FROM ${BUILD_FROM}
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates python3 python3-pip \
 && python3 -m pip install --no-cache-dir playwright==1.49.0 \
 && python3 -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
# Build-time smoke check: a bad image fails here, not at runtime.
RUN python3 -c "import sys; from playwright.sync_api import sync_playwright; \
p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop(); print('playwright ok', sys.executable)"
WORKDIR /app
COPY store_snapshot.py reader.py /app/
# Not an HA base image (no s6): the reader is the container's main process.
CMD ["python3", "-u", "/app/reader.py"]
