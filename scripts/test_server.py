"""Run with python3 -m unittest discover -s scripts -p 'test_*.py'."""
import base64
import functools
import hashlib
import http.client
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from server import ROOT, StudioHandler, ThreadingHTTPServer, save_snapshot


def png_image(width, height):
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' * (width * 4 + 1)) * height))
            + chunk(b'IEND', b''))


class SaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.save_root = Path(cls.temp.name) / 'result-data'
        handler = functools.partial(StudioHandler, directory=ROOT, save_root=cls.save_root)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def payload(self, portrait='zhu'):
        width, height = (1450, 1524) if portrait == 'zhu' else (1312, 1604)
        return {'scene': {
            'schemaVersion': 1, 'assetVersion': '1', 'rendererVersion': '1',
            'portraitId': portrait, 'canvas': {'width': width, 'height': height},
            'items': [{'uid': 'example-item', 'id': 'pear', 'x': .4, 'y': .5,
                       'size': .3, 'angle': 45}]},
            'png': base64.b64encode(png_image(width, height)).decode()}

    def post(self, payload, origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        connection.request('POST', '/api/snapshots', json.dumps(payload), headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_both_portraits_save_matching_files(self):
        for portrait in ['zhu', 'euro']:
            with self.subTest(portrait=portrait):
                payload = self.payload(portrait)
                status, result = self.post(payload)
                self.assertEqual(status, 201)
                folder = self.save_root / Path(result['directory']).name
                self.assertEqual(len(list(folder.iterdir())), 2)
                document = json.loads((folder / Path(result['json']).name).read_text())
                png = (folder / Path(result['png']).name).read_bytes()
                self.assertEqual(document['items'], payload['scene']['items'])
                self.assertEqual(document['portraitId'], portrait)
                self.assertEqual(document['snapshotId'], result['snapshotId'])
                self.assertEqual(document['image']['sha256'], hashlib.sha256(png).hexdigest())
                self.assertEqual(png, base64.b64decode(payload['png']))

    def test_repeated_saves_preserve_both_snapshots(self):
        first = self.post(self.payload())[1]
        second = self.post(self.payload())[1]
        self.assertNotEqual(first['snapshotId'], second['snapshotId'])
        for result in (first, second):
            self.assertTrue((self.save_root / Path(result['directory']).name).is_dir())

    def test_reject_invalid_data_without_writing(self):
        for field, value in [('x', 2), ('size', float('nan')), ('id', '../pear')]:
            payload = self.payload()
            payload['scene']['items'][0][field] = value
            before = set(self.save_root.iterdir()) if self.save_root.exists() else set()
            self.assertEqual(self.post(payload)[0], 400)
            self.assertEqual(set(self.save_root.iterdir()) if self.save_root.exists() else set(), before)

    def test_reject_wrong_image_dimensions(self):
        payload = self.payload()
        payload['png'] = base64.b64encode(png_image(1, 1)).decode()
        self.assertEqual(self.post(payload)[0], 400)

    def test_reject_cross_origin_write(self):
        self.assertEqual(self.post(self.payload(), 'https://example.com')[0], 403)

    def test_failed_second_write_removes_partial_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, 'write_text', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    save_snapshot(Path(directory), self.payload()['scene'], b'test-png')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_disk_error_returns_failure(self):
        with patch('server.save_snapshot', side_effect=OSError('disk full')):
            self.assertEqual(self.post(self.payload())[0], 500)


if __name__ == '__main__':
    unittest.main()
