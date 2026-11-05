"""HTTP contract/security tests over real loopback sockets, no live HA writes."""
import http.client
import json
import secrets
import threading
import unittest

from server import BridgeServer
from task_queue import TaskQueue
import test_execution


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(32)
        self.server = BridgeServer(('127.0.0.1', 0), token=self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method='GET', path='/api/health', body=None, headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        self.addCleanup(conn.close)
        conn.request(method, path, body=body, headers=headers if headers is not None else self.headers())
        response = conn.getresponse()
        data = json.loads(response.read())
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
        return response.status, data

    def headers(self):
        return {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}

    def test_all_routes_require_auth(self):
        for method, path in [('GET', '/api/health'), ('POST', '/api/tasks'), ('GET', '/api/tasks/' + 'a'*32), ('POST', '/api/tasks/' + 'a'*32 + '/cancel')]:
            self.assertEqual(self.request(method, path, headers={})[0], 401)

    def test_health_and_execution_gate(self):
        self.assertFalse(self.request()[1]['execution_enabled'])
        self.assertEqual(self.request('POST', '/api/tasks', json.dumps({'project':'go-field-notes','prompt':'inspect'}))[0], 503)

    def test_malformed_json_and_schema(self):
        for body in ['{', '[]', 'null', '{"project": [], "prompt": "x"}', '{"project": "go-field-notes", "prompt": "x", "env": {}}']:
            # Enable validation, with no usable workspace: invalid schema must never spawn.
            self.server.queue = TaskQueue(execution_enabled=True)
            self.assertEqual(self.request('POST', '/api/tasks', body)[0], 400)

    def test_framing_and_content_type(self):
        self.assertEqual(self.request('POST', '/api/tasks', 'x' * 8193)[0], 413)
        self.assertEqual(self.request('POST', '/api/tasks', '{}', {'Authorization': 'Bearer '+self.token})[0], 415)
        headers = self.headers() | {'Transfer-Encoding':'chunked'}
        self.assertEqual(self.request('POST', '/api/tasks', '{}', headers)[0], 400)

    def test_hostile_authorization_and_paths(self):
        self.assertEqual(self.request(headers={'Authorization': 'Bearer é'})[0], 401)
        self.assertEqual(self.request(path='/api/health?token=abc')[0], 400)
        self.assertEqual(self.request(path='/api/tasks/../config')[0], 404)
        self.assertEqual(self.request(path='/api/tasks/not-an-id')[0], 400)
        self.assertEqual(self.request(path='/api/tasks/'+'a'*32)[0], 404)

    def test_startup_and_ingress_peer_gate(self):
        for token in ['', 'short', 'a'*32, 'é'*43]:
            with self.assertRaises(ValueError):
                BridgeServer(('127.0.0.1', 0), token=token)
        with self.assertRaises(ValueError):
            BridgeServer(('0.0.0.0', 0), token=self.token)
        self.server.ingress_only = True
        self.assertFalse(self.server.verify_request(None, ('127.0.0.1', 123)))
        self.assertFalse(self.server.verify_request(None, ('172.30.33.2', 123)))
        self.assertTrue(self.server.verify_request(None, ('172.30.32.2', 123)))

    def test_submit_retrieve_cancel_end_to_end_fixture(self):
        fixture = test_execution.ExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.server.queue = fixture.queue
        with fixture.runner('import sys; print("fixture-result:", sys.stdin.read())'):
            status, submitted = self.request('POST', '/api/tasks', json.dumps({'project':'go-field-notes','prompt':'read-only fixture'}))
            self.assertEqual(status, 202)
            task = type('TaskID', (), {'id':submitted['id']})()
            fixture.finish(task)
            status, result = self.request(path='/api/tasks/'+task.id)
            self.assertEqual((status, result['state']), (200, 'succeeded'))
            self.assertIn('fixture-result: read-only fixture', result['output'])
        with fixture.runner('import time; time.sleep(30)'):
            _, submitted = self.request('POST', '/api/tasks', json.dumps({'project':'go-field-notes','prompt':'inspect'}))
            task.id = submitted['id']
            status, result = self.request('POST', '/api/tasks/'+task.id+'/cancel')
            self.assertEqual((status, result['cancelled']), (200, True))
            fixture.finish(task)
