"""Constrained Codex task queue prototype, not wired into the running add-on.

Execution remains disabled until container sandbox and API access are verified.
"""
from __future__ import annotations

import dataclasses
import os
import pathlib
import re
import subprocess
import signal
import threading
import time
import uuid
import selectors
import logging

WORKSPACES = pathlib.Path("/data/workspaces")
PROJECTS = {
    "go-field-notes": "go-field-notes",
    "book-requests": "book-requests",
}
MAX_PROMPT = 4000
MAX_OUTPUT = 12000
TIMEOUT_SECONDS = 300
MAX_TASKS = 100
MAX_STREAM_BYTES = 1024 * 1024


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
    def __init__(self, workspaces: pathlib.Path = WORKSPACES, *, execution_enabled: bool = False, codex_home: pathlib.Path | None = None):
        self.workspaces = workspaces
        self.execution_enabled = execution_enabled
        # A dedicated home must be provisioned independently; never reuse SSH/worker auth.
        self.codex_home = codex_home
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}
        self._active: str | None = None
        self._process: subprocess.Popen | None = None

    def submit(self, project: str, prompt: str) -> Task:
        if not self.execution_enabled:
            raise RuntimeError("Execution disabled pending sandbox verification")
        if not isinstance(project, str) or project not in PROJECTS:
            raise ValueError("Unknown project")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            raise ValueError("Invalid prompt")
        # Resolve and verify an existing workspace; never create or clone on demand.
        # This prototype must not be exposed to untrusted clients: read-only sandbox
        # support on Home Assistant OS remains unverified.
        base = self.workspaces.resolve(strict=True)
        workspace = (base / PROJECTS[project]).resolve(strict=True)
        if workspace.parent != base or not workspace.is_dir():
            raise ValueError("Workspace unavailable")
        if self.codex_home is None:
            raise RuntimeError("Execution disabled pending isolated home provisioning")
        home = self.codex_home.resolve(strict=True)
        if not home.is_dir() or home == base or base in home.parents or home in base.parents or home == pathlib.Path(os.environ.get("CODEX_HOME", "/nonexistent")).resolve():
            raise RuntimeError("Execution disabled: unsafe Codex home")
        with self._lock:
            if self._active is not None:
                raise RuntimeError("Another task is running")
            while len(self._tasks) >= MAX_TASKS:
                del self._tasks[next(iter(self._tasks))]
            task = Task(id=uuid.uuid4().hex, project=project)
            self._tasks[task.id] = task
            self._active = task.id
            snapshot = dataclasses.replace(task)
        try:
            threading.Thread(target=self._run, args=(task, workspace, prompt), daemon=True).start()
        except RuntimeError:
            with self._lock:
                del self._tasks[task.id]
                self._active = None
            raise
        logging.getLogger(__name__).info("task_submitted id=%s project=%s", task.id, project)
        return snapshot

    def _run(self, task: Task, workspace: pathlib.Path, prompt: str) -> None:
        with self._lock:
            if task.state != "cancelled":
                task.state = "running"
        try:
            env = {"HOME": str(self.codex_home), "CODEX_HOME": str(self.codex_home),
                   "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
            command = ["codex", "--ask-for-approval", "never", "exec",
                       "--ignore-user-config", "--ignore-rules", "--ephemeral",
                       "--sandbox", "read-only", "--skip-git-repo-check",
                       "-C", str(workspace), "-"]
            with subprocess.Popen(
                command, cwd=str(workspace), env=env, shell=False,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True,
            ) as proc:
                try:
                    with self._lock:
                        self._process = proc
                        if task.state == "cancelled":
                            self._kill(proc)
                    proc.stdin.write(prompt.encode("utf-8"))
                    proc.stdin.close()
                    output = bytearray()
                    total = 0
                    deadline = time.monotonic() + TIMEOUT_SECONDS
                    state = None
                    with selectors.DefaultSelector() as selector:
                        selector.register(proc.stdout, selectors.EVENT_READ)
                        while selector.get_map():
                            if time.monotonic() >= deadline:
                                state = "timed_out"
                                self._kill(proc)
                                break
                            for key, _ in selector.select(timeout=0.05):
                                chunk = os.read(key.fileobj.fileno(), 4096)
                                if not chunk:
                                    selector.unregister(key.fileobj)
                                    continue
                                total += len(chunk)
                                output.extend(chunk)
                                if total > MAX_STREAM_BYTES:
                                    state = "output_limited"
                                    self._kill(proc)
                                    break
                            if state:
                                break
                    try:
                        proc.wait(timeout=max(.01, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        state = "timed_out"
                        self._kill(proc)
                        proc.wait(timeout=5)
                    # Remove descendants even when the parent has already exited.
                    self._kill(proc)
                    stdout = output.decode("utf-8", errors="replace")
                    state = state or ("succeeded" if proc.returncode == 0 else "failed")
                    with self._lock:
                        task.output = redact(stdout)[-MAX_OUTPUT:]
                        task.exit_code = proc.returncode
                        if task.state != "cancelled":
                            task.state = state
                finally:
                    self._kill(proc)

        except Exception as exc:
            with self._lock:
                if task.state != "cancelled":
                    task.state = "failed"
                task.output = f"Task execution failed: {type(exc).__name__}"
        finally:
            with self._lock:
                task.finished_at = time.time()
                if self._active == task.id:
                    self._process = None
                    self._active = None
            logging.getLogger(__name__).info("task_finished id=%s state=%s exit_code=%s",
                                            task.id, task.state, task.exit_code)

    @staticmethod
    def _kill(proc):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def get(self, task_id: str) -> dict:
        if not isinstance(task_id, str) or not re.fullmatch(r"[0-9a-f]{32}", task_id):
            raise ValueError("Invalid task ID")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError("Task not found")
            return dataclasses.asdict(task)

    def cancel(self, task_id: str) -> bool:
        self.get(task_id)  # Consistent validation, including before process startup.
        with self._lock:
            if task_id != self._active:
                return False
            self._tasks[task_id].state = "cancelled"
            if self._process is not None:
                self._kill(self._process)
            return True


def redact(value: str) -> str:
    # Defense in depth: secrets must not enter the job output in the first place.
    value = re.sub(r"gh[opsu]_[A-Za-z0-9_]{20,}", "[REDACTED]", value)
    value = re.sub(r"github_pat_[A-Za-z0-9_]{20,}", "[REDACTED]", value)
    value = re.sub(r"(?i)Bearer\s+[^\s\"\']+", "Bearer [REDACTED]", value)
    value = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "[REDACTED]", value)
    return value
