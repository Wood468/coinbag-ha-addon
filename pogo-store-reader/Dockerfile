# Pinned: the image ships Chromium and the matching Playwright 1.49.0 Python package.
ARG BUILD_FROM=mcr.microsoft.com/playwright/python:v1.49.0-jammy
FROM ${BUILD_FROM}
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY store_snapshot.py reader.py /app/
# Not an HA base image (no s6): the reader is the container's main process.
CMD ["python3", "-u", "/app/reader.py"]
