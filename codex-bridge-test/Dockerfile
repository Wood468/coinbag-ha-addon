ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.22
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 bubblewrap \
    && addgroup -S bridge-test \
    && adduser -S -D -H -u 10001 -G bridge-test bridge-test
WORKDIR /app
COPY runtime/ /app/
# Writable control file: an unsandboxed unprivileged process could alter this.
RUN touch /app/write-probe && chmod 0666 /app/write-probe
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Startup reads only this disposable app's options, then drops UID/GID and
# enables no-new-privileges before serving. No Codex, Git, SSH or Node installed.
ENTRYPOINT ["/usr/bin/python3", "-I", "-B", "/app/start.py"]
