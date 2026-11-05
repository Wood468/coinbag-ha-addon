# Codex Bridge Disposable Test

A separate Home Assistant test app for PR #16. It verifies authenticated ingress
and task receipt transport without running Codex or model-generated commands.
It does not change Codex Remote SSH or Codex CLI Worker.

- Separate slug `codex_bridge_test` and Supervisor-managed private `/data`.
- Ingress port 8099 only; no host ports, host network, host PID/IPC/DBus, shared
  mounts, Docker socket/API, HA API, elevated capabilities or protection changes.
- Default Docker AppArmor and seccomp restrictions remain enabled.
- Drops to UID 10001, clears inherited environment (including Supervisor tokens),
  and sets no-new-privileges before the startup probe or HTTP server.
- Requires both the actual Supervisor socket peer (`172.30.32.2`) and an
  independent random bearer token on every API route.
- No Codex, Git, SSH, Node, command queue or execution-enable setting in the image.

## Development installation only

Register the development repository, **not the default branch**:

`https://github.com/Wood468/coinbag-ha-addon#feature/chatgpt-codex-task-bridge`

Install only **Codex Bridge Disposable Test** from that repository. Leave the
existing SSH and Worker entries alone. The app boots manually. Before starting,
set `bridge_token` using a cryptographically random URL-safe token of at least
32 random bytes (43+ characters). The option uses a password field. Never paste
its value into chat, logs, commits or issue reports. Disable auto-update for this
disposable app and keep boot manual.

No production app is replaced. Removal is stop/uninstall of this test slug only;
removing its data discards its private token. Remove the development repository
only after its test app is uninstalled.

## API and expected results

All requests require `Authorization: Bearer <independent-secret>`. Requests are
made through `Home assistant`'s `ha_manage_app`, using the discovered **test** slug,
`path`, `method`, `request_headers` and, for submission, a JSON `body`.

| Request | Expected result |
| --- | --- |
| GET `/api/health` | 200, `execution_enabled:false`, `codex_installed:false`, sandbox evidence |
| POST `/api/tasks` | 202, ID and `state:blocked`; this is a diagnostic receipt, never executed |
| GET `/api/tasks/{id}` | 200, same ID, `reason:execution_disabled`, empty output, no exit code |
| POST `/api/tasks/{id}/cancel` | 409; no running task exists |
| Any route without/corrupt bearer | 401, when routed through Supervisor |
| Direct connection from another socket peer | Closed before HTTP processing |

Submission body: `{"project":"book-requests","prompt":"disposable transport probe"}`.
Allowed project names are `book-requests` and `go-field-notes`; these are labels,
not mounted workspaces. Prompts are validated then discarded. Only the most
recent 100 metadata receipts exist in memory; restart clears them. There is no
execution or configuration API. A successful receipt roundtrip proves ingress
transport/authentication only, **not Codex execution**.

## Sandbox experiment

The image uses Alpine's distribution `bubblewrap`. At startup, after dropping
privileges, it runs one fixed probe with user/PID/network namespaces, read-only
root, masked private `/data` and `/run`, private `/tmp` and no capabilities.
The negative tests verify a normally writable control file becomes read-only,
a normally readable non-secret marker in `/data` disappears, and a known parent
network listener cannot be reached. Positive controls prevent false passes from
unreadable files. The probe cannot be supplied or changed by HTTP callers.

Failure leaves the diagnostic server available and execution disabled. Even
`primitive_checks_passed` explicitly reports `codex_sandbox_verified:false`:
a real Codex sandbox, credential isolation, Unix socket isolation and external
tool policies still require validation. This image has no model credentials.

The supported HA OS outer boundary is Supervisor-managed Docker with protection
mode, AppArmor/seccomp and isolated volumes/namespaces. Nested bubblewrap may be
blocked by these policies. Do not add SYS_ADMIN, use host namespaces, disable
AppArmor/seccomp/protection mode, use legacy Landlock as a fallback, or pass
Codex bypass flags to force it to run. If the target cannot support the inner
sandbox under the retained policies, execution needs a separately isolated Linux
worker host/VM with working supported sandbox primitives; that is an architectural
change, not permission to weaken HA OS protections.

Sources: [HA app security](https://contributors.home-assistant.io/apps/guides/security/),
[ingress](https://contributors.home-assistant.io/apps/guides/ingress/),
[branch repositories](https://contributors.home-assistant.io/apps/guides/repository/),
[Codex permissions and Linux enforcement](https://learn.chatgpt.com/docs/permissions).

## Tests

From the repository root:

```sh
python3 -W error::ResourceWarning -m unittest discover -s codex-remote/bridge -p 'test_*.py' -v
```

`runtime/server.py` is an exact packaging copy of the PR's shared transport.
The tests fail if those copies diverge. No executable task queue is packaged.
