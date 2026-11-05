# Disposable HA test results — 2026-11-05

## Follow-up: outer-container negative tests (0.0.3)

Reviewed PR #16's current branch and commits through `92f437d`, with both GitHub
checks passing. The local checkout was clean and matched the remote; no newer
uncommitted Claude edits were present. Earlier commits are attributed to Dylan
and later ones to Codex; Git metadata alone cannot establish which tool authored
Dylan's changes. Reviewed the existing bridge guard, invocation, environment,
authentication, process-group cancellation, retention and packaging tests.

Inspected installed Claude Code 1.2.76 metadata and its public config and
`stdin-runner.sh` source (upstream head observed:
`25791e026cabaf0ca054c6d75173e1eb432116f8`). Claude serializes headless tasks,
uses CLI allowed-tool permissions, times out a process group, and returns HA
events plus persisted transcript tails. Its add-on requests root/full access,
Docker, manager Supervisor and HA APIs, and HA/config/share/media mounts. This is
an intentionally privileged administration architecture, not a safe substitute
for a constrained untrusted execution worker. No credentials were read from its
filesystem, copied, provisioned into this app, or used for model calls. Installed
options were not printed. Claude was not invoked or modified.

Built and updated **only the disposable test app** to 0.0.3 with Supervisor.
No privileges, namespaces, mounts, security profiles or production apps changed.
The new fixed audit executes once in an unprivileged Python child with a minimal
environment; no bearer in argv/environment. Sensitive-path probes only open and
close handles, never read contents; the image-write probe does not truncate or
write. TCP probes send no application bytes. Each connect has a one-second bound
and the whole child has a five-second timeout. HTTP callers cannot select probes,
destinations, commands or execution policy.

Actual child results, retrieved over the existing authenticated HA MCP transport:

| Negative test | Result |
| --- | --- |
| Open this app's `/data/options.json` | Permission denied |
| Open `/proc/1/mem` | Permission denied |
| Open immutable image code for writing, without truncation | Permission denied |
| HA secrets/storage and Claude credential paths | Absent; no shared mounts |
| `/var/run/docker.sock`, `/run/docker.sock` | Absent |
| Effective capabilities | Zero (`0000000000000000`) |
| No-new-privileges | `1` |
| Seccomp mode | **`0` (no filter observed)** |
| TCP to Supervisor `172.30.32.2:80` | **Reachable — restriction fails** |
| TCP to HA Core `172.30.32.1:8123` | **Reachable — restriction fails** |
| TCP to fixed public IP `1.1.1.1:443` | **Reachable — restriction fails** |
| Inner bubblewrap sandbox | **Blocked**, `Failed to make / slave: Permission denied` |

Correction to earlier assumptions: retaining default Supervisor settings does
**not** establish that a default Docker seccomp filter is active on this host.
The observed child mode above supersedes the earlier README's claim. No seccomp
setting was changed. A mount rejection alone does not identify the enforcing
kernel/AppArmor policy. Absent files establish lack of exposure at those paths,
not a general filesystem deny policy. PID 1 memory denial is a real process
access test, not proof against every process escape. Reachable TCP establishes
network exposure, not successful authenticated Supervisor access; no such API
calls were attempted by the audit.

Authenticated live submission returned HTTP 202 with receipt
`dacc9bcd4d8e4e908c63d750cad2d181`; retrieval returned HTTP 200, matching ID,
`state:blocked`, `reason:execution_disabled`, empty output and null exit code.
Missing bearer returned 401; attempting an HTTP execution-enable field returned
400. The previous redacted option value was unusable for authentication; rotated
only this disposable app's independent token using cryptographic randomness,
without displaying or committing it. True Supervisor ingress remains unverified.

The separate Supervisor-managed container provides useful file/process
separation, but **does not supply the required complete execution boundary**.
Ordinary `ports:{}` disables host publishing, not container egress. The documented
app config does not provide a destination egress allowlist or per-app custom
seccomp selector. A firewall inside a task-accessible privileged container, host
network changes, security-profile relaxation, and Codex bypass flags were not
used. No safe solution on this retained HA policy has been demonstrated. A
separately provisioned Linux VM/worker with working supported Codex isolation and
independently scoped credentials remains necessary unless a supported HA runtime
mechanism can pass these gates. No external worker is available in this session.
No real Codex/model task has run, and no production deployment is authorized by
these results.

Verification for implementation commit `48df1d9`: **40 bridge tests** pass locally
with ResourceWarning fatal; GitHub `bridge-tests` independently passes all 40.
GitHub `static-checks` passes all **15 repository regression tests**, Python
compilation, service syntax/config validation and the Coin Bag Docker build.
The local broader suite could not import `dbus_fast`; attempts to provision a
temporary venv hit the existing AppArmor filesystem policy, which was preserved.
CI installed the declared dependencies and verified the full suite instead.
The disposable image itself built and started successfully under Supervisor.
Python compilation and `git diff --check` pass locally.

Final state: disposable 0.0.3 **stopped**, manual boot, auto-update false,
`mcp_gateway_access:false`. Execution remains hard-disabled. Claude Code,
Codex Remote SSH and Codex CLI Worker retained their running versions. Core and
Supervisor were not restarted, reconfigured or upgraded.

Sources: [Claude add-on configuration](https://github.com/robsonfelix/robsonfelix-hass-addons/blob/25791e026cabaf0ca054c6d75173e1eb432116f8/claudecode/config.yaml),
[Claude headless runner](https://github.com/robsonfelix/robsonfelix-hass-addons/blob/25791e026cabaf0ca054c6d75173e1eb432116f8/claudecode/stdin-runner.sh),
[supported HA configuration](https://contributors.home-assistant.io/apps/reference/configuration/),
[OpenAI isolation guidance](https://learn.chatgpt.com/docs/agent-approvals-security),
[OpenAI permissions](https://learn.chatgpt.com/docs/permissions).

The sections below preserve the earlier 0.0.2 experiment and its historical
state. The follow-up above is the latest result.

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
