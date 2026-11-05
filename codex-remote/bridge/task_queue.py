"""Constrained, read-only Codex task queue. No HTTP listener until ingress is verified.

This module intentionally contains no shell execution and never accepts a path or
command from callers. It is not wired into the running SSH add-on.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import subprocess
import threading
import time
import uuid

WORKSPACES = pathlib.Path("/data/workspaces")
PROJECTS = {
    "go-field-notes": "go-field-notes",
    "book-requests": "book-requests",
}
MAX_PROMPT = 4000
MAX_OUTPUT = 12000
TIMEOUT_SECONDS = 300


@dataclasses.dataclass
class Task:
    id: str
    project: str
    state: str = "queued"
    exit_code: int | None = None
    output: str = ""
    created_at: float = dataclasses.field(default_factory=time.time)
    finished_at: float | None = None


class TaskQueue:
    def __init__(self, workspaces: pathlib.Path = WORKSPACES):
        self.workspaces = workspaces
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}
        self._active: str | None = None
        self._process: subprocess.Popen | None = None

    def submit(self, project: str, prompt: str) -> Task:
        if project not in PROJECTS:
            raise ValueError("Unknown project")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            raise ValueError("Invalid prompt")
        # Resolve and verify an existing workspace; never create or clone on demand.
        base = self.workspaces.resolve(strict=True)
        workspace = (base / PROJECTS[project]).resolve(strict=True)
        if workspace.parent != base or not workspace.is_dir():
            raise ValueError("Workspace unavailable")
        with self._lock:
            if self._active is not None:
                raise RuntimeError("Another task is running")
            task = Task(id=uuid.uuid4().hex, project=project)
            self._tasks[task.id] = task
            self._active = task.id
        threading.Thread(target=self._run, args=(task, workspace, prompt), daemon=True).start()
        return dataclasses.replace(task)

    def _run(self, task: Task, workspace: pathlib.Path, prompt: str) -> None:
        with self._lock:
            task.state = "running"
        try:
            env = {key: value for key, value in os.environ.items()
                   if key in ("HOME", "PATH", "CODEX_HOME", "LANG", "TERM")}
            command = ["codex", "exec", "--sandbox", "read-only",
                       "--skip-git-repo-check", "-C", str(workspace), prompt]
            with subprocess.Popen(
                command, cwd=str(workspace), env=env, shell=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                start_new_session=True,
            ) as proc:
                with self._lock:
                    self._process = proc
                try:
                    stdout, _ = proc.communicate(timeout=TIMEOUT_SECONDS)
                    state = "succeeded" if proc.returncode == 0 else "failed"
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, _ = proc.communicate()
                    state = "timed_out"
                with self._lock:
                    task.output = redact(stdout[-MAX_OUTPUT:])
                    task.exit_code = proc.returncode
                    if task.state != "cancelled":
                        task.state = state
        except Exception as exc:
            with self._lock:
                task.state = "failed"
                task.output = f"Task execution failed: {type(exc).__name__}"
        finally:
            with self._lock:
                task.finished_at = time.time()
                self._process = None
                self._active = None

    def get(self, task_id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", task_id):
            raise ValueError("Invalid task ID")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError("Task not found")
            return dataclasses.asdict(task)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            if task_id != self._active or self._process is None:
                return False
            self._tasks[task_id].state = "cancelled"
            self._process.kill()
            return True


def redact(value: str) -> str:
    # Defense in depth: secrets must not enter the job output in the first place.
    value = re.sub(r"gh[opsu]_[A-Za-z0-9_]{20,}", "[REDACTED]", value)
    value = re.sub(r"github_pat_[A-Za-z0-9_]{20,}", "[REDACTED]", value)
    return value
