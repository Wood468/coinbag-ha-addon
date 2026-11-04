ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}
RUN apk add --no-cache openssh-server shadow nodejs npm python3     && npm install --global @openai/codex     && addgroup -S codex-remote     && adduser -S -D -H -h /data/codex-remote -s /bin/sh -G codex-remote codex-remote     && mkdir -p /data/ssh /data/codex-home /data/workspaces /run/sshd     && chown -R codex-remote:codex-remote /data/codex-home /data/workspaces     && chmod 700 /data/ssh /data/codex-home
COPY rootfs/ /
RUN chmod 0755 /usr/local/bin/codex-remote-command /etc/services.d/codex-remote/run
CMD ["/init"]
