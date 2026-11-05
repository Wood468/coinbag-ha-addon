# Bridge validation — 2026-11-05

## Result

Not ready to deploy. No end-to-end ChatGPT → Home Assistant → Codex task has
succeeded. The existing SSH app and separate CLI Worker were not changed.

## Reproducible local checks

```sh
python3 -W error::ResourceWarning -m unittest discover -s codex-remote/bridge -p 'test_*.py' -v
```

29 distinct tests pass. The HTTP lifecycle test opens real loopback sockets,
submits a task, retrieves its finished output, and cancels a second task. Its
child executable is a Python fixture substituted for Codex. This validates API
and process plumbing only; it is not an OpenAI model or HA ingress test.

Coverage includes the default execution gate, allow-listed workspaces, symlink
escape, prompt schema/length, stdin delivery (including option-like prompts),
environment filtering, successful/failed execution, bounded output/retention,
redaction before response truncation, timeout after early stdout closure,
cancellation before/after process startup, spawn failure cleanup, restart with
execution disabled and no previous task records, bearer authentication on all
routes, hostile authorization values, body framing, JSON content type,
loopback binding, Supervisor socket-peer checks, and private token files.

The task store is intentionally volatile. Restart loses task IDs/results and
must not replay work. A supervised container must terminate its entire process
cgroup on restart. Crash recovery/persistent audit storage is not implemented.

## Observed live HA results

The connected `Home assistant` plugin's `ha_get_app` succeeded:

- SSH slug: `a2c32b20_codex_remote`, version `0.1.17`, started.
- `ingress: false`, `host_network: true`, `network: {}`.
- No Supervisor, Home Assistant or Docker API permissions.
- Separate Worker: `8a8d906b_codex_cli_worker`, version `0.1.80`, started.

Using `ha_manage_app` without lifecycle/configuration fields:

| Request | Result |
| --- | --- |
| GET `/api/health` | VALIDATION_FAILED: app does not support Ingress |
| POST `/api/tasks` with harmless read-only probe | Same rejection, no task accepted |
| GET `/api/tasks/00000000000000000000000000000000` | Same rejection, no result available |

The separate `ChatGPT HA` plugin returned an internal error on the read-only
skill-guide request. Its currently advertised tool list has no app API proxy.
The working `Home assistant` proxy advertises `request_headers`, JSON `body`,
and `method`; bearer forwarding and successful submission/retrieval remain
unverified until an ingress-enabled test app exists.

## Sandbox probe

In the current SSH workspace container (not a new HA test app):

```sh
codex -c 'sandbox_mode="read-only"' sandbox /bin/true
```

Codex CLI `0.166.0` exited 1:

> bwrap: No permissions to create a new namespace

No kernel settings, AppArmor profile, capabilities, or sandbox flags were
weakened. A fixture subprocess passing is not evidence that Codex sandboxing
works on the Lenovo. The target app must pass a real sandbox negative test
before any model task can be enabled.

## Security review and remaining gates

- Both entrypoints instantiate an execution-disabled queue. There is no HTTP
  setting or request parameter to enable execution.
- Development binds loopback only. `ingress.py` is staged for a **separate**
  bridge-network container, with no host ports, and rejects peers other than
  `172.30.32.2` using the socket address (not forwarding headers). Do not launch
  it in the existing host-network SSH app.
- All endpoints, including health, require an independent random bearer token.
  The ingress token file must be a nonsymlink regular file owned by the process
  user with no group/other permissions. Token values must never be pasted into
  chat, committed, or included in task output. File mode is not entropy proof;
  provision with a cryptographic generator (`secrets.token_urlsafe(32)`).
- Connections/threads, body size, request read time, total child output, returned
  output, task runtime, and retained task count are bounded. Audit events contain
  task ID, allowed project, final state, and exit code, never prompts/headers.
- Child environment omits inherited Supervisor/GitHub/bridge credentials. Prompt
  goes through stdin; sandbox is read-only and approval policy is never (denies
  escalation). User config and execpolicy rules are ignored; unsupported CLI
  versions fail rather than retry with looser settings.
- **Read-only does not mean secret-isolated.** A dedicated Codex home alone is
  insufficient. OS-level isolation must prevent the child from reading bridge
  credentials, SSH/Worker credentials, HA config, other projects and sockets.
  Disable external MCP servers/hooks and verify repository configuration cannot
  enable unsandboxed tools. These target-container controls are NOT yet proven.
- Redaction handles common GitHub/OpenAI/bearer patterns only. It cannot guarantee
  arbitrary secrets are removed. Credential exclusion at the filesystem and
  tool boundary is mandatory before execution. No shared auth files were read
  or copied to provision the bridge.
- No write-capable tasks, branch-only Git permissions, merge/deploy permissions,
  persistence or production packaging are validated. Keep those disabled.

## Required next environment

Provide a disposable HA OS/Supervised test instance (or authorize a separate
isolated test app after reviewing this draft) that does not reuse the SSH app's
volume, host network, or CLI Worker's auth/config. It needs working kernel
sandbox support without turning off protection, and independent scoped Codex
credentials provisioned through a secret channel.

First validate authenticated health through the connected proxy and rejection
from LAN/other app peers. Then test sandbox write/network/credential-read denial
inside the target container. Only after these pass, enable a disposable read-only
workspace task, submit through `ha_manage_app`, poll its returned ID, and verify
a unique marker from a fixture file. Repeat timeout/cancel/restart checks. Record
actual results before considering any production deployment.

## Additional repository checks

Python compilation and `git diff --check` pass. The unrelated Coin Bag suite's
8 static tests pass; `test_pairing_agent` cannot import `dbus_fast` in this
executor. Creating a temporary validation venv also failed during pip bootstrap
with a permission error for `/lib/ld-musl-x86_64.so.1`. No system packages or
running app files were changed to work around it. The existing validation CI
installs its declared Bluetooth dependencies and remains the authority for that
unrelated suite; the bridge suite requires only the Python standard library.

## Follow-up: disposable HA app validation

The subsequent disposable-app experiment is documented in
[../../codex-bridge-test/VALIDATION.md](../../codex-bridge-test/VALIDATION.md).
Its separate container built successfully on HA OS. Connected-interface health,
blocked task receipt submission/retrieval, authentication rejection and restart
semantics were exercised live using a separate authenticated internal listener.
True Supervisor ingress remains unverified because the installed MCP tool uses
a direct sibling-container route. The actual HA bubblewrap probe failed with
`bwrap: Failed to make / slave: Permission denied`; execution is still unavailable.
The disposable app is stopped and its optional listener disabled. Both original
Codex apps are unchanged and running. This supersedes the earlier statement that
no test app exists, without establishing any real Codex execution success.
