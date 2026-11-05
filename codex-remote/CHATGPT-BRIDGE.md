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
