"""Fixed negative tests inside bubblewrap, never reads user prompts."""
import json
import pathlib
import socket
import sys


def check(port):
    checks = {}
    try:
        # /app is readable by design but must be read-only even for an owned file.
        pathlib.Path('/app/write-probe').write_text('unexpected')
        checks['root_write_denied'] = False
    except OSError:
        checks['root_write_denied'] = True
    try:
        pathlib.Path('/data/isolation-marker').read_bytes()
        checks['private_data_hidden'] = False
    except OSError:
        checks['private_data_hidden'] = True
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            checks['parent_network_hidden'] = False
    except OSError:
        checks['parent_network_hidden'] = True
    print(json.dumps(checks))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    sys.exit(check(int(sys.argv[1])))
