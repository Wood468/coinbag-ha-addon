# Codex Remote SSH (isolated Home Assistant app)

This is a separate SSH endpoint for Codex remote projects. It does not modify or reuse the existing Codex CLI Worker.

## Security design
- No `/config`, Docker socket, Supervisor API, or Home Assistant API mount.
- Dedicated non-root `codex-remote` account and isolated `CODEX_HOME`.
- SSH public-key authentication only; no password or root login.
- No agent, TCP, X11, tunnel, or PTY forwarding.
- Forced command allow-list; no general shell.
- No host port mapping. Intended access is through a tailnet-only Tailscale TCP service.
- Workspace data stays under this app's `/data/workspaces`.

## Not yet production-ready
The current ChatGPT SSH client command sequence and the Supervisor/AppArmor/network behavior must be verified before deployment. The forced-command allow-list is intentionally narrow; do not broaden it blindly if the client requests an unknown command.

## Deployment outline
1. Add this repository to Home Assistant Apps (local app repository already used for Coin Bag).
2. Review/build this app; do not install over or alter the existing Codex Worker.
3. Generate a dedicated Ed25519 SSH keypair on the device that will connect. Put only the public key in the app's `authorized_keys` option.
4. Start the app and inspect its logs plus `/data/codex-device-auth.log`. Complete the separate Codex device-auth flow. Never copy the worker's auth file.
5. Configure Tailscale's Services feature with a tailnet-only TCP service targeting this app's internal hostname on port 2222. Do not use Funnel or publish a host port. Verify the internal target resolves from the Tailscale app.
6. Test SSH and the exact ChatGPT remote-project flow using a disposable workspace before real work.

## Limitations
- OpenAI currently documents SSH-host remote projects in the ChatGPT desktop app. The iOS SSH form should be tested rather than assumed to support the complete workflow.
- This is an isolated coding workspace, not a path into Home Assistant configuration.
- Private Git repositories need a separate Git credential setup within this app.
