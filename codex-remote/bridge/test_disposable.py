"""Packaged disposable app: auth, blocked receipts, and sandbox fail-closed."""
import http.client
import importlib.util
import json
import pathlib
import secrets
import subprocess
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / 'codex-bridge-test'


def load(name, filename):
    import sys
    spec = importlib.util.spec_from_file_location(name, APP / 'runtime' / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


queue_module = load('disposable_queue', 'diagnostic_queue.py')
probe_module = load('disposable_probe', 'sandbox_probe.py')
server_module = load('disposable_server', 'server.py')
startup_module = load('disposable_startup', 'start.py')
boundary_module = load('disposable_boundary', 'boundary_check.py')


class DisposableTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(32)
        self.queue = queue_module.DiagnosticQueue({'status': 'blocked', 'codex_sandbox_verified': False})
        self.server = server_module.BridgeServer(('127.0.0.1', 0), token=self.token, queue=self.queue)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, body=None, token=True):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = 'Bearer ' + self.token
            connection.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
            result = connection.getresponse()
            return result.status, json.loads(result.read())
        finally:
            connection.close()

    def test_health_and_authenticated_receipt_roundtrip(self):
        self.assertEqual(self.request('GET', '/api/health', token=False)[0], 401)
        status, health = self.request('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertFalse(health['execution_enabled'])
        self.assertFalse(health['codex_installed'])
        prompt = 'sensitive prompt never retained'
        status, receipt = self.request('POST', '/api/tasks', {'project':'book-requests','prompt':prompt})
        self.assertEqual((status, receipt['state']), (202, 'blocked'))
        status, result = self.request('GET', '/api/tasks/' + receipt['id'])
        self.assertEqual(status, 200)
        self.assertEqual(result['reason'], 'execution_disabled')
        self.assertFalse(result['execution_enabled'])
        self.assertIsNone(result['exit_code'])
        self.assertEqual(result['output'], '')
        self.assertNotIn(prompt, repr(self.queue._tasks))
        self.assertEqual(self.request('POST', '/api/tasks/' + receipt['id'] + '/cancel')[0], 409)
        self.assertEqual(self.request('GET', '/api/tasks/' + receipt['id'], token=False)[0], 401)

    def test_no_http_execution_switch_or_arbitrary_projects(self):
        for body in [{'project':'book-requests','prompt':'probe','execution_enabled':True},
                     {'project':'../../config','prompt':'probe'},
                     {'project':'book-requests','prompt':'x'*4001}]:
            self.assertEqual(self.request('POST', '/api/tasks', body)[0], 400)
        with self.assertRaises(AttributeError):
            self.queue.execution_enabled = True
        self.assertEqual(self.request('POST', '/api/enable', {})[0], 404)

    def test_gateway_policy_is_distinct_from_ingress(self):
        gateway = startup_module.GatewayServer(('127.0.0.1', 0), token=self.token,
                                              queue=self.queue, ingress_only=True)
        self.addCleanup(gateway.server_close)
        self.assertTrue(gateway.verify_request(None, ('172.30.32.1', 123)))
        for peer in ['172.30.32.2', '172.30.33.5', '127.0.0.1', '192.168.1.2']:
            self.assertFalse(gateway.verify_request(None, (peer, 123)))
        self.server.ingress_only = True
        self.assertTrue(self.server.verify_request(None, ('172.30.32.2', 123)))
        self.assertFalse(self.server.verify_request(None, ('172.30.32.1', 123)))

    def test_retention_and_restart_are_explicit(self):
        with mock.patch.object(queue_module, 'MAX_TASKS', 2):
            first = self.queue.submit('book-requests', 'probe')
            self.queue.submit('book-requests', 'probe')
            self.queue.submit('book-requests', 'probe')
        with self.assertRaises(KeyError):
            self.queue.get(first.id)
        fresh = queue_module.DiagnosticQueue({})
        self.assertEqual(fresh._tasks, {})
        self.assertFalse(fresh.execution_enabled)

    def test_package_boundaries(self):
        config = json.loads((APP / 'config.json').read_text())
        for key in ['host_network', 'host_pid', 'host_ipc', 'host_dbus', 'full_access',
                    'hassio_api', 'homeassistant_api', 'docker_api']:
            self.assertIs(config[key], False)
        self.assertTrue(config['apparmor'])
        self.assertTrue(config['ingress'])
        self.assertEqual(config['ports'], {})
        self.assertEqual(config['map'], [])
        self.assertEqual(config['privileged'], [])
        self.assertEqual(config['boot'], 'manual')
        self.assertEqual(config['slug'], 'codex_bridge_test')
        # The image's transport copy must match the PR's tested shared transport.
        self.assertEqual((APP/'runtime/server.py').read_bytes(),
                         (ROOT/'codex-remote/bridge/server.py').read_bytes())
        self.assertFalse((APP/'runtime/task_queue.py').exists())

    def test_ingress_rejects_spoofed_forwarded_peer(self):
        self.server.ingress_only = True
        # Request contains valid bearer but local socket peer is not Supervisor.
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request('GET', '/api/health', headers={
                'Authorization': 'Bearer ' + self.token,
                'X-Forwarded-For':'172.30.32.2', 'X-Remote-User-Id':'spoofed'})
            with self.assertRaises((http.client.RemoteDisconnected, ConnectionResetError)):
                connection.getresponse()
        finally:
            connection.close()


class ProbeTests(unittest.TestCase):
    def run_probe(self, result=None, error=None):
        with mock.patch('builtins.open', mock.mock_open()), \
             mock.patch.object(pathlib.Path, 'read_bytes', return_value=b'public'), \
             mock.patch.object(probe_module.subprocess, 'run', return_value=result, side_effect=error):
            return probe_module.probe()

    def test_namespace_failure_never_enables_execution(self):
        result = self.run_probe(subprocess.CompletedProcess([], 1, b'', b'bwrap: namespace operation not permitted'))
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], 'namespace_or_policy_denied')
        self.assertFalse(result['codex_sandbox_verified'])

    def test_success_is_primitive_evidence_only(self):
        result = self.run_probe(subprocess.CompletedProcess([], 0, json.dumps({k:True for k in probe_module.CHECKS}).encode(), b''))
        self.assertEqual(result['status'], 'primitive_checks_passed')
        self.assertFalse(result['codex_sandbox_verified'])

    def test_timeout_and_invalid_results_fail_closed(self):
        for stdout in [b'not json', b'{}', b'[]', b'{"x":true}']:
            self.assertEqual(self.run_probe(subprocess.CompletedProcess([], 0, stdout, b''))['status'], 'failed')
        self.assertEqual(self.run_probe(error=subprocess.TimeoutExpired('bwrap', 5))['status'], 'unavailable')


class BoundaryTests(unittest.TestCase):
    def test_permission_probe_never_reads_or_modifies_contents(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'public-canary'
            path.write_text('unchanged')
            self.assertEqual(boundary_module.inaccessible(path), 'accessible')
            self.assertEqual(boundary_module.inaccessible(path, os.O_WRONLY), 'accessible')
            self.assertEqual(path.read_text(), 'unchanged')
            self.assertEqual(boundary_module.inaccessible(path.parent / 'missing'), 'absent')
        with mock.patch.object(boundary_module.os, 'open', side_effect=PermissionError):
            self.assertEqual(boundary_module.inaccessible('/unused'), 'denied')
        with mock.patch.object(boundary_module.os, 'open', side_effect=OSError):
            self.assertEqual(boundary_module.inaccessible('/unused'), 'unverified')

    def test_real_tcp_positive_control_and_closed_port_are_not_security_passes(self):
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            target = listener.getsockname()
            with mock.patch.object(boundary_module, 'TARGETS', {'control': target}):
                result = boundary_module.check()
            self.assertEqual(result['network']['control'], 'reachable')
            self.assertEqual(result['reason'], 'network_reachable')
            self.assertFalse(result['execution_boundary_verified'])
        with mock.patch.object(boundary_module, 'TARGETS', {'control': target}):
            result = boundary_module.check()
        self.assertEqual(result['network']['control'], 'not_reached_unverified')
        self.assertFalse(result['execution_boundary_verified'])
