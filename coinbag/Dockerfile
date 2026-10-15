ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-pip bluez dbus \
 && pip install --no-cache-dir --break-system-packages bleak
WORKDIR /app
COPY main.py protocol.py fetch_constants.py run.sh /app/
RUN python3 fetch_constants.py /app/constants.json && chmod +x run.sh
CMD ["/app/run.sh"]
