"""One bounded, fixed startup probe; results never enable execution."""
import json
import os
import pathlib
import socket
import subprocess

CHECKS = {'root_write_denied', 'private_data_hidden', 'parent_network_hidden'}


def probe():
    # Positive controls prevent a read-only image or unreadable marker from
    # producing a false sandbox pass. Marker contains no secret.
    try:
        with open('/app/write-probe', 'r+b'):
            pass
        pathlib.Path('/data/isolation-marker').read_bytes()
    except OSError:
        return {'status': 'failed', 'reason': 'positive_control_failed',
                'codex_sandbox_verified': False}
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent',
                   '--new-session', '--cap-drop', 'ALL', '--ro-bind', '/', '/',
                   '--tmpfs', '/data', '--tmpfs', '/run', '--tmpfs', '/tmp',
                   '--proc', '/proc', '--dev', '/dev', '--',
                   '/usr/bin/python3', '-I', '-B', '/app/sandbox_check.py',
                   str(listener.getsockname()[1])]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=5, check=False,
                                    env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {'status': 'unavailable', 'error': type(exc).__name__,
                    'codex_sandbox_verified': False}
        # No raw stderr: never expose paths, options or credentials in diagnostics.
        if result.returncode != 0:
            namespace_error = b'namespace' in result.stderr.lower() or b'operation not permitted' in result.stderr.lower()
            return {'status': 'blocked', 'exit_code': result.returncode,
                    'reason': 'namespace_or_policy_denied' if namespace_error else 'probe_failed',
                    'codex_sandbox_verified': False}
        try:
            checks = json.loads(result.stdout)
            passed = isinstance(checks, dict) and set(checks) == CHECKS and all(v is True for v in checks.values())
        except (ValueError, TypeError):
            passed = False
        return {'status': 'primitive_checks_passed' if passed else 'failed',
                'codex_sandbox_verified': False,
                'checks': checks if passed else {}}
