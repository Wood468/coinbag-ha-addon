"""Fixed outer-container observations. Never executes caller-supplied code.

Open sensitive paths only to test permissions; never read their contents. TCP
checks send no application bytes, credentials, or requests to HA services.
These observations cannot certify a Codex sandbox or enable execution.
"""
import json
import os
import pathlib
import socket


PATHS = {
    'own_options_unreadable': '/data/options.json',
    'ha_secrets_unreadable': '/homeassistant/secrets.yaml',
    'ha_storage_unreadable': '/config/.storage/auth',
    'claude_credentials_unreadable': '/homeassistant/.claudecode/.credentials.json',
    'docker_socket_absent': '/var/run/docker.sock',
    'alternate_docker_socket_absent': '/run/docker.sock',
    'pid1_memory_unreadable': '/proc/1/mem',
}
TARGETS = {
    'supervisor_tcp_denied': ('172.30.32.2', 80),
    'homeassistant_tcp_denied': ('172.30.32.1', 8123),
    # Fixed numeric address avoids DNS errors masquerading as network isolation.
    'internet_tcp_denied': ('1.1.1.1', 443),
    # IPv4 denial does not imply IPv6 denial. A reachable IPv6 destination
    # must fail the audit too; unavailable IPv6 is inconclusive, not a pass.
    'internet_ipv6_tcp_denied': ('2606:4700:4700::1111', 443),
}


def inaccessible(path, flags=os.O_RDONLY):
    try:
        fd = os.open(path, flags | os.O_NONBLOCK)
    except FileNotFoundError:
        return 'absent'
    except PermissionError:
        return 'denied'
    except OSError:
        return 'unverified'
    else:
        os.close(fd)
        return 'accessible'


def check():
    paths = {name: inaccessible(path) for name, path in PATHS.items()}
    paths['image_code_unwritable'] = inaccessible('/app/boundary_check.py', os.O_WRONLY)
    network = {}
    for name, target in TARGETS.items():
        try:
            with socket.create_connection(target, timeout=1):
                network[name] = 'reachable'
        except OSError:
            # A refused connection or timeout alone does not prove policy denial.
            network[name] = 'not_reached_unverified'
    status = pathlib.Path('/proc/self/status').read_text().splitlines()
    controls = {key: next((line.split(':', 1)[1].strip() for line in status
                           if line.startswith(key + ':')), 'unknown')
                for key in ('CapEff', 'NoNewPrivs', 'Seccomp')}
    return {'paths': paths, 'network': network, 'process_controls': controls,
            'uid': os.geteuid(), 'execution_boundary_verified': False,
            'reason': 'network_reachable' if 'reachable' in network.values()
            else 'insufficient_evidence'}


if __name__ == '__main__':
    print(json.dumps(check()))
