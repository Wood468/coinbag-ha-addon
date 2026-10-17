ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-pip bluez dbus \
 && pip install --no-cache-dir --break-system-packages "bleak==2.1.1"
WORKDIR /app
COPY main.py pairing_agent.py protocol.py fetch_constants.py /app/
RUN python3 fetch_constants.py /app/constants.json
# The HA base image runs s6-overlay: the app must be an s6 service, not a CMD.
COPY run.sh /etc/services.d/coinbag/run
RUN chmod a+x /etc/services.d/coinbag/run
