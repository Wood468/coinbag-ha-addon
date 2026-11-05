# ChatGPT → Lenovo Codex bridge (implementation plan)

Status: design only; **not deployed**. Existing Codex Remote SSH and Codex CLI Worker must remain untouched until a verified end-to-end path exists.

## Current constraint

The connected Home Assistant tool can inspect/manage add-ons and proxy a **documented app HTTP API** through Supervisor ingress. It cannot run arbitrary shell commands. The Codex Remote SSH add-on currently has no ingress/API endpoint. An SSH/Tailscale service does not make it a callable ChatGPT tool.

## Intended interface

Provide an add-on-specific authenticated API, reachable **only** through Home Assistant Supervisor ingress, with narrowly scoped operations:
- `POST /api/tasks`: submit a Codex prompt plus a known project ID; returns a job ID.
- `GET /api/tasks/{id}`: report bounded status, exit code and redacted output.
- `POST /api/tasks/{id}/cancel`: stop an active task.
- `GET /api/health`: no secrets, no filesystem access.

Use an explicit project allow-list; reject arbitrary working directories, shell command strings, paths, URLs and environment overrides. Run Codex as existing non-root `codex-remote`, with no Docker socket, HA config mount, HA API credentials or Supervisor token. Never return GitHub tokens or Codex auth material. Enforce task limits, one active task, bounded output, and structured audit records. Disable write operations until repo-specific approval and branch-only safeguards are tested.

## Network/authentication

The current add-on uses `host_network: true` for a loopback-only SSH endpoint. **Do not** simply bind a new HTTP server to `0.0.0.0` or expose a host port. Validate ingress routing and isolation first; add an independent authorization layer if other add-ons can reach the service. Do not rely on Tailscale's SSH endpoint as an HTTP API.

## Acceptance criteria

1. Verify Home Assistant ingress proxy can call a harmless health endpoint from this ChatGPT connection.
2. Verify no LAN/public exposure and no unauthenticated API access.
3. Run one read-only Codex task in a disposable workspace; capture output through the proxy.
4. Test cancellation, timeout, restart, malformed input and secret redaction.
5. Test repo-specific branch-only access, with no merge/deploy permissions.
6. Keep existing Codex CLI Worker unchanged throughout.

## Deployment gate

No production deployment until the API and network/security assumptions are tested and a working ChatGPT tool call is demonstrated. A GitHub branch or HTTP endpoint alone does not establish ChatGPT connectivity.

## Implementation and current evidence

See [bridge/VALIDATION.md](bridge/VALIDATION.md) for executed tests, live tool
results, sandbox failure, and remaining gates. The isolated API and process tests
are implemented; production connectivity is **not established**.

`bridge/server.py` provides an execution-disabled loopback development API.
`bridge/ingress.py` is a staged, execution-disabled adapter for an independent
bridge-network test container. Neither is copied or started by the existing
SSH app's Dockerfile/startup, and its config/version are unchanged.

A future isolated test app must use `host_network: false`, `ports: {}`,
`ingress: true`, `ingress_port: 8099`, `panel_admin: true`, a dedicated non-root
user and volume, no `/config`/Docker mounts and no HA/Supervisor API permissions.
Launch the adapter with `python3 ingress.py --token-file <private-file>` only
inside that isolated container. This recipe is not a deployment instruction
for the running SSH app.

All documented requests require `Authorization: Bearer <independent-secret>`;
POST submission also requires `Content-Type: application/json`. The connected
`Home assistant` tool exposes the corresponding `request_headers`, `method`,
`path`, and `body` parameters on `ha_manage_app`. Keep secrets out of chat and
tool output. No token has been provisioned for a live bridge yet.

Sources: [HA ingress isolation](https://contributors.home-assistant.io/apps/guides/ingress/),
[Codex security](https://developers.openai.com/codex/security). Ingress authenticates
the HA session; this command-capable API additionally requires a bearer token.
A read-only Codex sandbox restricts writes; it does not establish credential
isolation or safe network behavior for external tools.

## Disposable test app

[../codex-bridge-test/README.md](../codex-bridge-test/README.md) packages a separate
execution-unavailable app. Its [validation report](../codex-bridge-test/VALIDATION.md)
records actual connected-interface receipt tests and the remaining ingress-route
and sandbox blockers. This test app does not replace or modify the SSH app or
CLI Worker, and a blocked receipt is not Codex execution.
