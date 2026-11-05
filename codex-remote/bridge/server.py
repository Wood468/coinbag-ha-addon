"""Prototype local HTTP API. NOT installed, launched or exposed by the add-on.

Run only for development after setting BRIDGE_TOKEN to a strong random value.
Ingress proxy/authentication compatibility has NOT been verified.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_BODY = 8192
MAX_CONNECTIONS = 16


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, *, token, queue=None, ingress_only=False):
        # Tokens are immutable for this process; a missing/weak secret fails startup.
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
            raise ValueError("Provide a random URL-safe token of at least 32 bytes")
        if not ingress_only and address[0] != "127.0.0.1":
            raise ValueError("Non-ingress development servers must bind loopback")
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.token = token
        if queue is None:
            from task_queue import TaskQueue
            queue = TaskQueue()
        self.queue = queue
        self.ingress_only = ingress_only
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def verify_request(self, request, client_address):
        return not self.ingress_only or client_address[0] == "172.30.32.2"


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def _json(self, code, data):
        body = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        headers = self.headers.get_all("Authorization", [])
        if len(headers) != 1:
            return False
        # Bytes avoid compare_digest raising on hostile non-ASCII header values.
        return hmac.compare_digest(headers[0].encode("utf-8"),
                                   ("Bearer " + self.server.token).encode("ascii"))

    def _route(self):
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment or parsed.scheme or parsed.netloc:
            return self._json(400, {"error": "invalid path"})
        path = parsed.path
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1:
            return self._json(400, {"error": "ambiguous body framing"})
        if path == "/api/health" and self.command == "GET":
            health = {"status": "ok", "mode": "read-only",
                      "execution_enabled": self.server.queue.execution_enabled}
            if hasattr(self.server.queue, "health"):
                health.update(self.server.queue.health())
            return self._json(200, health)
        if path == "/api/tasks" and self.command == "POST":
            length = self.headers.get("Content-Length", "")
            if not length.isascii() or not length.isdecimal() or len(length) > 5 or not (1 <= int(length) <= MAX_BODY):
                return self._json(413, {"error": "invalid body length"})
            try:
                if self.headers.get_content_type() != "application/json":
                    return self._json(415, {"error": "application/json required"})
                raw = self.rfile.read(int(length))
                if len(raw) != int(length):
                    return self._json(400, {"error": "incomplete body"})
                body = json.loads(raw)
                if not isinstance(body, dict) or set(body) != {"project", "prompt"}:
                    raise ValueError("Invalid task")
                task = self.server.queue.submit(body["project"], body["prompt"])
                return self._json(202, {"id": task.id, "state": task.state})
            except (ValueError, TypeError, KeyError, RecursionError):
                return self._json(400, {"error": "invalid task"})
            except RuntimeError as exc:
                if str(exc).startswith("Execution disabled"):
                    return self._json(503, {"error": "execution disabled"})
                return self._json(409, {"error": "busy"})
            except (OSError, FileNotFoundError):
                return self._json(503, {"error": "workspace unavailable"})
        parts = path.split("/")
        if len(parts) == 4 and parts[:3] == ["", "api", "tasks"]:
            try:
                if self.command == "GET":
                    return self._json(200, self.server.queue.get(parts[3]))
                if self.command == "POST" and self.headers.get("Content-Length") in (None, "0"):
                    return self._json(405, {"error": "method not allowed"})
            except ValueError:
                return self._json(400, {"error": "invalid id"})
            except KeyError:
                return self._json(404, {"error": "not found"})
        if len(parts) == 5 and parts[:3] == ["", "api", "tasks"] and parts[4] == "cancel" and self.command == "POST":
            try:
                return self._json(200 if self.server.queue.cancel(parts[3]) else 409, {"cancelled": self.server.queue.get(parts[3])["state"] == "cancelled"})
            except (ValueError, KeyError):
                return self._json(404, {"error": "not found"})
        return self._json(404, {"error": "not found"})

    def do_GET(self):
        try:
            self._route()
        except (socket.timeout, ConnectionError):
            self.close_connection = True

    def do_POST(self):
        try:
            self._route()
        except (socket.timeout, ConnectionError):
            self.close_connection = True

    def log_message(self, fmt, *args):
        # Avoid logging URLs or headers containing secrets.
        pass


if __name__ == "__main__":
    # No execution switch here: serving the staged API cannot enable commands.
    BridgeServer(("127.0.0.1", 18765), token=os.environ.get("BRIDGE_TOKEN", "")).serve_forever()
