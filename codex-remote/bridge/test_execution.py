"""Real child-process lifecycle tests; the child is a fixture, not Codex."""
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import task_queue
from task_queue import TaskQueue


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = pathlib.Path(self.temp.name)
        (root / 'work' / 'go-field-notes').mkdir(parents=True)
        (root / 'home').mkdir()
        self.queue = TaskQueue(root / 'work', execution_enabled=True, codex_home=root / 'home')
        self.real_popen = subprocess.Popen

    def runner(self, script):
        def launch(command, **kwargs):
            self.command, self.kwargs = command, kwargs
            return self.real_popen([sys.executable, '-c', script], **kwargs)
        return mock.patch.object(task_queue.subprocess, 'Popen', side_effect=launch)

    def finish(self, task):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.queue.get(task.id)
            if result['finished_at'] is not None:
                return result
            time.sleep(.01)
        self.queue.cancel(task.id)
        self.fail('Task failed to finish')

    def test_success_stdin_and_environment(self):
        with self.runner('import sys; print(sys.stdin.read())'), mock.patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'secret', 'BRIDGE_TOKEN': 'secret'}):
            result = self.finish(self.queue.submit('go-field-notes', '--dangerously-bypass-approvals-and-sandbox'))
        self.assertEqual(result['state'], 'succeeded')
        self.assertIn('--dangerously-bypass', result['output'])
        self.assertEqual(self.command[-1], '-')
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', self.command)
        self.assertEqual(self.command[self.command.index('--sandbox') + 1], 'read-only')
        self.assertIn('--ignore-user-config', self.command)
        self.assertEqual(set(self.kwargs['env']), {'HOME', 'CODEX_HOME', 'PATH', 'LANG'})
        self.assertFalse(self.kwargs['shell'])

    def test_nonzero_exit(self):
        with self.runner('import sys; sys.exit(7)'):
            result = self.finish(self.queue.submit('go-field-notes', 'inspect'))
        self.assertEqual((result['state'], result['exit_code']), ('failed', 7))

    def test_timeout(self):
        with self.runner('import time; time.sleep(30)'), mock.patch.object(task_queue, 'TIMEOUT_SECONDS', .1):
            result = self.finish(self.queue.submit('go-field-notes', 'inspect'))
        self.assertEqual(result['state'], 'timed_out')

    def test_busy_cancel_and_reuse(self):
        with self.runner('import time; time.sleep(30)'):
            task = self.queue.submit('go-field-notes', 'inspect')
            with self.assertRaisesRegex(RuntimeError, 'Another task'):
                self.queue.submit('go-field-notes', 'inspect')
            self.assertTrue(self.queue.cancel(task.id))
            self.assertEqual(self.finish(task)['state'], 'cancelled')
            self.assertFalse(self.queue.cancel(task.id))
        with self.runner('print("next")'):
            self.assertEqual(self.finish(self.queue.submit('go-field-notes', 'inspect'))['state'], 'succeeded')

    def test_closed_stdout_does_not_escape_timeout(self):
        with self.runner('import os, time; os.close(1); os.close(2); time.sleep(30)'), mock.patch.object(task_queue, 'TIMEOUT_SECONDS', .1):
            result = self.finish(self.queue.submit('go-field-notes', 'inspect'))
        self.assertEqual(result['state'], 'timed_out')

    def test_cancel_before_worker_starts(self):
        threads = []
        real_thread = task_queue.threading.Thread
        def delayed_thread(**kwargs):
            thread = real_thread(**kwargs)
            threads.append(thread)
            return mock.Mock(start=lambda: None)
        with self.runner('import time; time.sleep(30)'), mock.patch.object(task_queue.threading, 'Thread', side_effect=delayed_thread):
            task = self.queue.submit('go-field-notes', 'inspect')
            self.assertTrue(self.queue.cancel(task.id))
            threads[0].start()
            self.assertEqual(self.finish(task)['state'], 'cancelled')
            threads[0].join(1)

    def test_output_limit(self):
        with self.runner('import sys; sys.stdout.write("x" * 2000000)'):
            result = self.finish(self.queue.submit('go-field-notes', 'inspect'))
        self.assertEqual(result['state'], 'output_limited')
        self.assertLessEqual(len(result['output']), task_queue.MAX_OUTPUT)

    def test_secrets_redacted_before_truncation(self):
        with self.runner('print("github_pat_" + "a" * 13000)'):
            result = self.finish(self.queue.submit('go-field-notes', 'inspect'))
        self.assertNotIn('aaaa', result['output'])
        self.assertIn('[REDACTED]', result['output'])

    def test_spawn_failure_releases_slot(self):
        with mock.patch.object(task_queue.subprocess, 'Popen', side_effect=FileNotFoundError):
            self.assertEqual(self.finish(self.queue.submit('go-field-notes', 'inspect'))['state'], 'failed')
        self.assertIsNone(self.queue._active)

    def test_retention_and_restart(self):
        with self.runner('print("ok")'), mock.patch.object(task_queue, 'MAX_TASKS', 2):
            tasks = [self.queue.submit('go-field-notes', 'inspect')]
            self.finish(tasks[0])
            for _ in range(2):
                tasks.append(self.queue.submit('go-field-notes', 'inspect'))
                self.finish(tasks[-1])
        self.assertEqual(len(self.queue._tasks), 2)
        with self.assertRaises(KeyError):
            self.queue.get(tasks[0].id)
        fresh = TaskQueue(self.queue.workspaces)
        with self.assertRaises(KeyError):
            fresh.get(tasks[-1].id)
        with self.assertRaises(RuntimeError):
            fresh.submit('go-field-notes', 'inspect')

    def test_execution_requires_independent_home(self):
        queue = TaskQueue(self.queue.workspaces, execution_enabled=True)
        with self.assertRaisesRegex(RuntimeError, 'isolated home'):
            queue.submit('go-field-notes', 'inspect')
