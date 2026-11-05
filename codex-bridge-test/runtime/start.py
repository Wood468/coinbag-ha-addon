"""Startup for the disposable app. No execution toggle exists."""
import ctypes
import json
import os
import pathlib
import pwd
import re
import sys
import signal
import threading

# Isolated Python mode excludes cwd; add only this immutable image directory.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from diagnostic_queue import DiagnosticQueue
from sandbox_probe import probe
from server import BridgeServer


class GatewayServer(BridgeServer):
    """Optional authenticated sibling API, distinct from Supervisor ingress."""
    def verify_request(self, request, client_address):
        # Host-network HA MCP reaches bridge containers via the hassio gateway.
        # Other host-network processes share this IP: bearer authentication is
        # mandatory and the IP alone does not establish the caller's identity.
        return client_address[0] == '172.30.32.1'


def main():
    if os.geteuid() != 0:
        raise SystemExit('Expected Supervisor container startup user')
    options_path = pathlib.Path('/data/options.json')
    # Supervisor writes these options only for this app's private data volume.
    options = json.loads(options_path.read_text())
    token = options.get('bridge_token', '')
    if not isinstance(token, str) or not re.fullmatch('[A-Za-z0-9_-]{43,128}', token):
        raise SystemExit('Configure an independent random bridge_token before starting')
    gateway_access = options.get('mcp_gateway_access', False)
    if not isinstance(gateway_access, bool):
        raise SystemExit('mcp_gateway_access must be boolean')
    options_path.chmod(0o600)
    del options
    marker = pathlib.Path("/data/isolation-marker")
    marker.write_text("public-sandbox-control")
    marker.chmod(0o644)
    user = pwd.getpwnam('bridge-test')
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    os.environ.clear()  # Remove injected Supervisor token before any child probe.
    os.environ.update(PATH='/usr/bin:/bin', LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise SystemExit('Unable to enforce no-new-privileges')
    sandbox = probe()
    print(json.dumps({'event': 'test_bridge_started', 'execution_enabled': False,
                      'uid': os.geteuid(), 'sandbox': sandbox}), flush=True)
    queue = DiagnosticQueue(sandbox)
    ingress = BridgeServer(('0.0.0.0', 8099), token=token,
                           queue=queue, ingress_only=True)
    gateway = None
    if gateway_access:
        gateway = GatewayServer(('0.0.0.0', 8100), token=token,
                                queue=queue, ingress_only=True)
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
    def stop(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        ingress.serve_forever()
    finally:
        ingress.server_close()
        if gateway is not None:
            gateway.shutdown()
            gateway.server_close()


if __name__ == '__main__':
    main()
