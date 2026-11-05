# Disposable HA test results — 2026-11-05

## Scope and final state

Built and installed only `f40151c9_codex_bridge_test` from development repository
`https://github.com/Wood468/coinbag-ha-addon#feature/chatgpt-codex-task-bridge`.
The Supervisor built versions 0.0.1 and 0.0.2 successfully from the Dockerfile;
this executor has no Docker CLI/socket, so the actual disposable Supervisor
installation supplied the container build/runtime validation.

Final test app: **0.0.2, stopped**, manual boot, auto-update false,
`mcp_gateway_access:false`. Private token retained only in its Supervisor-managed
password option; no token or model credential is included in this report.
No production app was updated, restarted, merged or deployed.

Before and after the experiment:

| Existing app | Slug | Version | State |
| --- | --- | --- | --- |
| Codex Remote SSH | `a2c32b20_codex_remote` | 0.1.17 | started |
| Codex CLI Worker | `8a8d906b_codex_cli_worker` | 0.1.80 | started |

Their configuration, startup, images and credentials were not modified. Git diff
against the starting commit is empty for the SSH config, Dockerfile, entrypoint
and AppArmor profile. The shared prototype transport changed only to support
an injected diagnostic queue and its health details, with its default execution
gate preserved. Neither transport nor test code is installed in the running SSH
app by this work.

## Isolation observed from Supervisor

The disposable app reports:

- `protected:true`, `apparmor:default` (Docker's enforced default profile).
- `host_network:false`, `host_pid:false`, `host_ipc:false`.
- `network:{}` (no host port mappings), no shared mounts or requested capabilities.
- `hassio_api:false`, `homeassistant_api:false`, `docker_api:false`.
- `ingress:true`, container ingress port 8099.
- Startup log confirms UID 10001 and `execution_enabled:false`.

The image contains no Codex, Git, SSH, Node, model credentials, executable task
queue or HTTP execution-enable switch. A fixed startup sandbox probe is its only
child-process experiment. `PR_SET_NO_NEW_PRIVS` must succeed before serving.

## Connected Home Assistant interface checks

The `Home assistant` plugin is live; its host-network HA MCP app is
`81f33d0f_ha_mcp`, version 9.0.0. Its observed Docker gateway source is
`172.30.32.1`. The plugin's app-mode proxy directly contacts the target container
and adds ingress-looking headers, instead of routing through Supervisor. The
source check on port 8099 correctly rejects it, even with the independent bearer.

**True Supervisor ingress is enabled but remains unverified end to end.** We did
not trust `X-Hass-Source`, `X-Ingress-Path`, `X-Remote-User-Id` or forwarding headers
as proof of authentication. The Supervisor-only ingress listener still only
accepts socket peer `172.30.32.2`.

To test the connected tool, version 0.0.2 adds a distinct opt-in listener on
container-only port 8100. It accepts gateway `172.30.32.1` plus mandatory bearer
credentials. Host-network apps share this source address; the independent bearer
is the credential, and the IP check is additional restriction, not app identity.
No host port or unauthenticated command endpoint was created. The listener was
enabled only during this experiment and is now disabled.

Actual `ha_manage_app` calls with the test slug and `port:8100`:

| Check | Observed result |
| --- | --- |
| Authenticated GET `/api/health` | HTTP 200; diagnostic-receipts-only, execution false, Codex absent |
| POST `/api/tasks`, valid bearer and project | HTTP 202; receipt `6430e10c2813424388656ffd100b05ee`, state blocked |
| GET that returned task ID, valid bearer | HTTP 200; same ID, reason execution_disabled, empty output, null exit code |
| Health without bearer / with wrong bearer | HTTP 401 |
| Submission without bearer | HTTP 401 |
| Retrieval without bearer | HTTP 401 |
| POST including `execution_enabled:true` | HTTP 400 |
| Cancel blocked receipt | HTTP 409, cancelled false |
| Authenticated port 8099 call from connected tool | Socket closed by Supervisor source restriction |
| Restart only the disposable app, then GET prior ID | HTTP 404; receipts not replayed |
| Health after restart | HTTP 200; execution still false, same sandbox failure |

This is a successful connected-tool **receipt transport** roundtrip. It is not
a Codex task execution or a successful Supervisor ingress roundtrip. The test
prompt was discarded and no workspace was mounted or accessed.

## Sandbox result and supported method investigation

The distribution bubblewrap probe ran inside the actual HA disposable app,
as UID 10001 with no-new-privileges and inherited credentials removed. It failed:

```text
exit code: 1
bwrap: Failed to make / slave: Permission denied
codex_sandbox_verified: false
```

This failure is at the root-mount propagation setup step. Bubblewrap's source
identifies the operation as `mount(..., MS_SLAVE | MS_REC, ...)`. We do not have
kernel audit evidence attributing the rejection specifically to AppArmor,
seccomp or another kernel/container restriction. A bounded read-only host-log
query for `bwrap` returned no lines. No syscall, kernel, AppArmor, capability,
network or protection-mode setting was relaxed to force a pass.

The supported HA OS outer isolation mechanism is a separate Supervisor-managed
container with protection mode, default AppArmor/seccomp, separate data and no
privileged mounts/APIs. That mechanism successfully runs this diagnostic app.
It is **not evidence that Codex's inner sandbox works**. Current OpenAI guidance
requires bubblewrap/seccomp for restricted Linux policies and says legacy
Landlock cannot substitute for filesystem/socket isolation. The default HA
container policy tested here prevents the required inner mount operation.

No supported nested-container/runtime override was established from the normal
app configuration that would preserve these restrictions and pass this test.
Adding SYS_ADMIN, disabling protection/AppArmor/seccomp, mounting Docker, using
host namespaces, downgrading sandbox backends, or running Codex with bypass flags
are not acceptable remedies under this task's constraints.

A separate Linux worker host/VM with supported unprivileged bubblewrap is the
remaining architectural option to investigate if HA's retained policy cannot
support it. That worker must pass real Codex write/network/secret/socket negative
tests, use independently scoped credentials and omit external unsandboxed tools.
No model execution may be enabled merely because this primitive probe passes.

## Exact remaining blockers

1. **True ingress tool route:** installed HA MCP's in-app direct route originates
   at the Docker gateway, while genuine ingress originates at Supervisor. An
   off-host HA MCP connection or connector change that actually uses authenticated
   Supervisor ingress is needed to validate that route. Existing MCP was not
   upgraded or reconfigured as part of this test.
2. **Sandbox:** the target container denies bubblewrap's root-mount propagation
   operation. A worker environment with working supported isolation is required
   before any Codex execution; no safe automatic policy change was established.

No additional credentials are needed for diagnostic receipts. Independent Codex
credentials will be needed only after a suitable worker sandbox is demonstrated;
none were requested, copied or provisioned into this test app.

## Automated validation

38 distinct bridge/package/security tests pass locally using the Python standard
library, with ResourceWarning treated as an error. Compilation and whitespace
checks pass. GitHub `bridge-tests` and `static-checks` both passed for code commit
`ff9f394` (the static workflow installs Coin Bag dependencies and builds its
container but does not deploy it).

Sources: [HA app security](https://contributors.home-assistant.io/apps/guides/security/),
[HA ingress](https://contributors.home-assistant.io/apps/guides/ingress/),
[HA configuration surface](https://contributors.home-assistant.io/apps/reference/configuration/),
[HA MCP routing implementation](https://github.com/homeassistant-ai/ha-mcp/blob/master/src/ha_mcp/tools/tools_addons.py),
[Codex Linux enforcement](https://learn.chatgpt.com/docs/permissions),
[bubblewrap mount setup](https://github.com/containers/bubblewrap/blob/main/bubblewrap.c).
