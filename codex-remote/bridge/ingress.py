"""Staged ingress adapter for an isolated test app, never the SSH host network.

This entrypoint deliberately has no execution-enable option. It establishes the
API authentication/routing contract first; it does not start Codex.
"""
import argparse
import logging
import os
import pathlib
import stat

from server import BridgeServer


def read_token(path):
    # Open once without following a symlink and validate the opened descriptor.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise ValueError('Token must be an owner-only regular file owned by this user')
        return source.read(130).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file', type=pathlib.Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('Run the isolated bridge as an unprivileged user')
    logging.basicConfig(level=logging.INFO)
    # Only in a dedicated container with host_network:false and ports:{}.
    # Source validation uses the socket peer, never spoofable forwarding headers.
    BridgeServer(('0.0.0.0', 8099), token=read_token(args.token_file),
                 ingress_only=True).serve_forever()


if __name__ == '__main__':
    main()
