"""Prototype local HTTP API. NOT installed, launched or exposed by the add-on.

Run only for development after setting BRIDGE_TOKEN to a strong random value.
Ingress proxy/authentication compatibility has NOT been verified.
"""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from task_queue import TaskQueue

MAX_BODY = 8192
QUEUE = TaskQueue()


class Handler(BaseHTTPRequestHandler):
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
        expected = os.environ.get("BRIDGE_TOKEN", "")
        if len(expected) < 32:
            return False
        header = self.headers.get("Authorization", "")
        return hmac.compare_digest(header, "Bearer " + expected)

    def _route(self):
        path = urlsplit(self.path).path
        if path == "/api/health" and self.command == "GET":
            return self._json(200, {"status": "ok", "mode": "prototype", "execution_enabled": False})
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        if path == "/api/tasks" and self.command == "POST":
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or not (1 <= int(length) <= MAX_BODY):
                return self._json(413, {"error": "invalid body length"})
            try:
                body = json.loads(self.rfile.read(int(length)))
                if not isinstance(body, dict) or set(body) != {"project", "prompt"}:
                    raise ValueError("Invalid task")
                task = QUEUE.submit(body["project"], body["prompt"])
                return self._json(202, {"id": task.id, "state": task.state})
            except (ValueError, TypeError, KeyError):
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
                    return self._json(200, QUEUE.get(parts[3]))
                if self.command == "POST" and self.headers.get("Content-Length") in (None, "0"):
                    return self._json(405, {"error": "method not allowed"})
            except ValueError:
                return self._json(400, {"error": "invalid id"})
            except KeyError:
                return self._json(404, {"error": "not found"})
        if len(parts) == 5 and parts[:3] == ["", "api", "tasks"] and parts[4] == "cancel" and self.command == "POST":
            try:
                return self._json(200 if QUEUE.cancel(parts[3]) else 409, {"cancelled": QUEUE.get(parts[3])["state"] == "cancelled"})
            except (ValueError, KeyError):
                return self._json(404, {"error": "not found"})
        return self._json(404, {"error": "not found"})

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def log_message(self, fmt, *args):
        # Avoid logging URLs or headers containing secrets.
        pass


if __name__ == "__main__":
    if len(os.environ.get("BRIDGE_TOKEN", "")) < 32:
        raise SystemExit("Set a strong BRIDGE_TOKEN before starting")
    # Loopback-only prototype; not reachable through Supervisor ingress as-is.
    ThreadingHTTPServer(("127.0.0.1", 18765), Handler).serve_forever()
