# HA OS-preserving Codex worker: implementation gate

Status: **execution blocked; no production deployment authorised**.

## Fixed requirements
- Keep Home Assistant OS, Supervisor, Home Assistant Core, Claude Code, Codex Remote SSH and Codex CLI Worker unchanged.
- Do not grant SYS_ADMIN, Docker socket, host namespaces, full_access, Supervisor manager/admin access, or disable AppArmor to make Codex work.
- Do not run Codex with sandbox bypass flags or copy Claude's broad privileges.
- Never expose Codex credentials, GitHub tokens, HA secrets or private project contents to the diagnostic transport.
- Keep the existing diagnostic-only receipt API separate from execution; an HTTP request must never enable execution.
- Stop after a 403 or failed authorisation; do not retry writes.

## Evidence baseline
See `codex-bridge-test/VALIDATION.md`, especially 0.0.3 audit:
- Authenticated task receipt roundtrip works (202, 200); execution remains disabled.
- Nonprivileged child: zero effective caps, no-new-privileges, but seccomp mode 0 observed.
- Bubblewrap fails root mount propagation.
- TCP connections to Supervisor 172.30.32.2:80, HA Core 172.30.32.1:8123 and 1.1.1.1:443 succeed.
- No host Docker socket or HA config mounts observed; this is insufficient proof of full isolation.
- 40 bridge tests and 15 repository regression tests passed in CI at the documented commit.

## Next implementation: evidence before execution
1. Read-only inventory of the existing SSH and CLI worker add-on manifests, mounts, capabilities, credential locations and process launch policies. Never print secret values.
2. Determine whether **documented, supported** HA Supervisor app configuration can provide independently enforceable task filesystem restrictions, per-destination network egress restrictions, syscall controls and a working Codex sandbox. Cite exact docs and test each claim.
3. If not, record **HA OS local worker infeasible under current security constraints**. Do not create a more privileged add-on or alter host networking to force success.
4. Independently assess an external Linux VM/container worker connected over outbound authenticated transport. This preserves HA OS. Provisioning must be a separate explicit decision; do not assume an external host exists.
5. Keep bridge transport read-only/diagnostic until an actual Codex run has passed the security gates below.

## Mandatory execution security gates
- Separate non-root worker account; writable workspaces limited to allowlisted repos and ephemeral per-task directories.
- Independent least-privilege GitHub/model credentials; never inherit HA, Supervisor, Claude or unrelated app secrets.
- Supported Codex sandbox policy demonstrably denies writes outside the workspace, reading planted canary secrets, process inspection and access to Docker/host sockets.
- Egress policy demonstrably blocks HA Core, Supervisor, LAN and arbitrary destinations while allowing only narrowly scoped services required by Codex and GitHub.
- Fail closed on missing isolation, network controls, credentials, policy, test tools or unknown Codex version.
- Authenticated task creation, status, cancellation, timeouts, process-group termination, output redaction and bounded logs.
- No autonomous merge, deploy or production changes until independently reviewed.
- End-to-end task initiated from the connected ChatGPT/HA transport and independently verified against a harmless test repository.

## Decision
The 0.0.3 findings fail both network and sandbox gates. **Do not enable unattended execution on the current HA OS add-on.** Continue implementation only if a materially different supported boundary passes negative tests, otherwise use a separately isolated Linux worker without replacing HA OS.

## 2026-11-05 discovery: existing installed Codex worker (do not duplicate)

Read-only Supervisor inventory confirms `8a8d906b_codex_cli_worker` v0.1.80 is the **moryoav/home-assistant-codex** implementation, already installed, and its `codex_cli` integration is loaded. It exposes Home Assistant actions for task submission, status, cancellation and conversation continuation; sensors report logged-in and zero active tasks at inspection. The add-on already has a mobile chat UI, a queued task runner and a protected custom AppArmor profile. Investigate using its **documented integration actions** as the execution transport instead of installing a third Codex worker or weakening HA OS security. This is an architectural discovery, not proof that the existing worker satisfies our separate execution isolation gates.

**Security caveat:** Supervisor reports its current `codex_sandbox` option as `danger-full-access`, and the worker has read/write access to Home Assistant `/config` and `homeassistant_api:true`. This is appropriate only for consciously trusted HA administration, **not** for unattended, arbitrary repository prompts or as an isolation boundary from Home Assistant. Do not silently change the running app options or submit a Codex task. Read the upstream integration action schema and runtime security implementation, then assess a narrowly scoped existing Codex Remote SSH workspace versus using the privileged HA worker. Never route untrusted GitHub tasks to this HA-config worker in its present configuration.

Sources: https://github.com/moryoav/home-assistant-codex ; https://community.home-assistant.io/t/codex-for-home-assistant-let-codex-cli-work-on-your-ha-config-from-scripts-automations-and-assist/1011929 ; https://www.reddit.com/r/homeassistant/comments/1v968qs/i_made_a_home_assistant_addon_that_lets_you_use/ .
