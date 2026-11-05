"""Bounded metadata receipts only. This module cannot execute a task."""
import dataclasses
import re
import threading
import time
import uuid

PROJECTS = frozenset(('go-field-notes', 'book-requests'))
MAX_TASKS = 100


@dataclasses.dataclass(frozen=True)
class Receipt:
    id: str
    project: str
    state: str = 'blocked'
    reason: str = 'execution_disabled'
    execution_enabled: bool = False
    output: str = ''
    exit_code: None = None
    created_at: float = dataclasses.field(default_factory=time.time)


class DiagnosticQueue:
    @property
    def execution_enabled(self):
        return False

    def __init__(self, sandbox):
        self._sandbox = sandbox
        self._tasks = {}
        self._lock = threading.Lock()

    def health(self):
        return {'mode': 'diagnostic-receipts-only', 'execution_enabled': False,
                'sandbox': self._sandbox, 'codex_installed': False}

    def submit(self, project, prompt):
        if not isinstance(project, str) or project not in PROJECTS:
            raise ValueError('Unknown project')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
            raise ValueError('Invalid prompt')
        # Discard the prompt. No filesystem access, subprocess, model or network.
        receipt = Receipt(id=uuid.uuid4().hex, project=project)
        with self._lock:
            while len(self._tasks) >= MAX_TASKS:
                del self._tasks[next(iter(self._tasks))]
            self._tasks[receipt.id] = receipt
        return receipt

    def get(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch('[0-9a-f]{32}', task_id):
            raise ValueError('Invalid task ID')
        with self._lock:
            return dataclasses.asdict(self._tasks[task_id])

    def cancel(self, task_id):
        self.get(task_id)
        return False  # Receipts never represent running work.
