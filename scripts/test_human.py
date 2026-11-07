"""Human submission contract; browser interaction is checked separately."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import functools
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from server import ROOT, StudioHandler, ThreadingHTTPServer, save_submission
from test_server import png_image


class HumanSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(
            StudioHandler, directory=ROOT, save_root=self.root))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.session = str(uuid.uuid4())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def payload(self, portrait='zhu', count=1):
        w, h = (1450, 1524) if portrait == 'zhu' else (1312, 1604)
        return {'sessionId': self.session, 'scene': {
            'schemaVersion': 1, 'assetVersion': '1', 'rendererVersion': '1',
            'portraitId': portrait, 'canvas': {'width': w, 'height': h},
            'items': [{'uid': str(i), 'id': 'pear', 'x': .4, 'y': .5,
                       'size': .3, 'angle': 0} for i in range(count)]},
            'png': base64.b64encode(png_image(w, h)).decode()}

    def post(self, payload):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request('POST', '/api/submissions', json.dumps(payload),
                           {'Content-Type': 'application/json'})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_both_portraits_share_session_and_have_distinct_trials(self):
        trials = []
        for portrait in ('zhu', 'euro'):
            status, result = self.post(self.payload(portrait, 151))
            self.assertEqual(status, 201)
            folder = self.root / Path(result['directory']).name
            self.assertEqual(len(list(folder.iterdir())), 2)
            document = json.loads((folder / Path(result['json']).name).read_text())
            self.assertEqual(document['experiment']['sessionId'], self.session)
            self.assertEqual(document['experiment']['actorType'], 'human')
            self.assertEqual(document['experiment']['status'], 'submitted')
            self.assertEqual(len(document['items']), 151)
            trials.append(document['experiment']['trialId'])
        self.assertNotEqual(*trials)

    def test_retry_is_idempotent_and_changed_submission_is_rejected(self):
        payload = self.payload()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.post, [payload, payload]))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], 201)
        self.assertEqual(len(list(self.root.iterdir())), 1)
        # Read the persisted result without any in-memory session registry.
        self.assertEqual(save_submission(self.root, payload['scene'],
                         base64.b64decode(payload['png']), self.session), results[0][1])
        changed = deepcopy(payload)
        changed['scene']['items'][0]['x'] = .6
        status, conflict = self.post(changed)
        self.assertEqual(status, 409)
        self.assertEqual(conflict['scene']['items'], payload['scene']['items'])
        self.assertEqual(self.post(payload), results[0])

    def test_submission_preserves_flips_and_rejects_changed_flip(self):
        for flip_x, flip_y in [(False, False), (True, False), (False, True), (True, True)]:
            with self.subTest(flipX=flip_x, flipY=flip_y):
                self.session = str(uuid.uuid4())
                payload = self.payload()
                item = payload['scene']['items'][0]
                item.update(flipX=flip_x, flipY=flip_y, angle=35)
                status, result = self.post(payload)
                self.assertEqual(status, 201)
                folder = self.root / Path(result['directory']).name
                document = json.loads((folder / Path(result['json']).name).read_text())
                self.assertEqual(document['items'], payload['scene']['items'])
                self.assertEqual(self.post(payload), (status, result))
                item['flipX'] = not flip_x
                self.assertEqual(self.post(payload)[0], 409)

    def test_reject_invalid_flip_flags(self):
        for key in ('flipX', 'flipY'):
            for value in (1, 0, 'true', None, [], {}):
                with self.subTest(key=key, value=value):
                    payload = self.payload()
                    payload['scene']['items'][0][key] = value
                    self.assertEqual(self.post(payload)[0], 400)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_new_session_does_not_overwrite_previous_submission(self):
        first = self.post(self.payload())[1]
        self.session = str(uuid.uuid4())
        second = self.post(self.payload())[1]
        self.assertNotEqual(first['snapshotId'], second['snapshotId'])
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_failed_write_can_be_retried(self):
        payload = self.payload()
        with patch.object(Path, 'write_text', side_effect=OSError('disk full')):
            self.assertEqual(self.post(payload)[0], 500)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.post(payload)[0], 201)

    def test_reject_invalid_session(self):
        for invalid in ('../escape', None, {}, ''):
            payload = self.payload()
            payload['sessionId'] = invalid
            self.assertEqual(self.post(payload)[0], 400)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
