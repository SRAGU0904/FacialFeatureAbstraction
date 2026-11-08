"""Local intake custody, duplicate handling, collection isolation and render recovery."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
import uuid

from agent import empty_scene
from human_results import (human_document, import_result, list_results, render_trial,
                           rendered_images, sha256)
from test_server import png_image


class HumanResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.document = {**empty_scene('zhu'), 'demographics': {
            'gender': 'prefer-not-to-say', 'age': 23, 'nationality': 'Test'},
            'feedback': '测试', 'researchNotice': 'Test notice',
            'experiment': {'actorType': 'human', 'status': 'submitted',
                           'sessionId': str(uuid.uuid4()), 'trialId': str(uuid.uuid4())}}
        self.raw = json.dumps(self.document, ensure_ascii=False, indent=2).encode() + b'\n'

    def renderer(self):
        renderer = Mock()
        renderer.browser.version = 'test-browser'
        renderer.render.return_value = {'full': {'png': base64.b64encode(
            png_image(1450, 1524)).decode()}}
        return renderer

    def test_exact_bytes_metadata_and_duplicate_import_preserved(self):
        folder, created = import_result(self.raw, self.root, 'formal')
        self.assertTrue(created)
        self.assertEqual(folder.parent.parent, self.root)
        self.assertFalse((self.root / 'formal').exists())
        self.assertEqual((folder / 'original.json').read_bytes(), self.raw)
        receipt_bytes = (folder / 'receipt.json').read_bytes()
        receipt = json.loads(receipt_bytes)
        self.assertEqual(receipt['sourceSha256'], sha256(self.raw))
        same = json.dumps(self.document).encode()
        self.assertEqual(import_result(same, self.root, 'formal'), (folder, False))
        self.assertEqual((folder / 'original.json').read_bytes(), self.raw)
        self.assertEqual((folder / 'receipt.json').read_bytes(), receipt_bytes)

    def test_conflicting_trial_rejected_even_if_session_or_metadata_changed(self):
        folder, _ = import_result(self.raw, self.root, 'formal')
        for field in ('session', 'demographics', 'scene'):
            document = deepcopy(self.document)
            if field == 'session':
                document['experiment']['sessionId'] = str(uuid.uuid4())
            elif field == 'demographics':
                document['demographics']['age'] = 24
            else:
                document.update(empty_scene('euro'))
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                import_result(json.dumps(document).encode(), self.root, 'formal')
        self.assertEqual((folder / 'original.json').read_bytes(), self.raw)

    def test_concurrent_duplicate_import_publishes_one_record(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: import_result(self.raw, self.root, 'formal'), range(2)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len(list(self.root.rglob('original.json'))), 1)

    def test_collections_and_session_pairing(self):
        folder, _ = import_result(self.raw, self.root, 'self-test')
        self.assertFalse((self.root / 'formal').exists())
        self.assertFalse(json.loads((folder / 'receipt.json').read_text())['formalResearchData'])
        second = deepcopy(self.document)
        second.update(empty_scene('euro'))
        second['experiment']['trialId'] = str(uuid.uuid4())
        second['demographics']['age'] = 24
        other, _ = import_result(json.dumps(second).encode(), self.root, 'self-test')
        self.assertEqual(folder.parent, other.parent)
        output = io.StringIO()
        with redirect_stdout(output):
            list_results(self.root, 'self-test')
        self.assertIn('zhu=1, euro=1', output.getvalue())
        self.assertEqual(output.getvalue().count('PENDING RENDER'), 2)

    def test_invalid_input_writes_nothing(self):
        invalid = [b'{"items": []}', self.raw + self.raw, b'```json\n' + self.raw + b'```']
        bad = deepcopy(self.document)
        bad['experiment']['trialId'] = '../escape'
        invalid.append(json.dumps(bad).encode())
        invalid.append(self.raw.replace(b'"schemaVersion": 1', b'"schemaVersion": 1, "schemaVersion": 1'))
        for raw in invalid:
            with self.assertRaises(ValueError):
                import_result(raw, self.root, 'formal')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_failed_archive_write_leaves_no_partial_record(self):
        with patch('human_results.write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                import_result(self.raw, self.root, 'formal')
        self.assertEqual(list(self.root.rglob('original.json')), [])
        self.assertEqual(list(self.root.rglob('.pending-*')), [])
        self.assertTrue(import_result(self.raw, self.root, 'formal')[1])

    @patch('human_results.importlib.metadata.version', return_value='test-playwright')
    @patch('human_results.render_sources', return_value={'test-file': 'test-hash'})
    def test_render_failure_recovery_and_versioned_outputs(self, *_mocks):
        folder, _ = import_result(self.raw, self.root, 'self-test')
        renderer = self.renderer()
        renderer.render.side_effect = RuntimeError('browser failure')
        with self.assertRaises(RuntimeError):
            render_trial(folder, renderer)
        self.assertEqual((folder / 'original.json').read_bytes(), self.raw)
        self.assertEqual(rendered_images(folder), [])
        self.assertEqual(list(folder.rglob('.pending-*')), [])
        renderer.render.side_effect = None
        first = render_trial(folder, renderer)
        second = render_trial(folder, renderer)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(len(rendered_images(folder)), 2)
        provenance = json.loads((second.parent / 'render.json').read_text())
        self.assertEqual(provenance['sourceSha256'], sha256(self.raw))
        self.assertEqual(provenance['pngSha256'], sha256(second.read_bytes()))
        self.assertEqual(provenance['browserVersion'], 'test-browser')
        self.assertEqual((folder / 'original.json').read_bytes(), self.raw)

    def test_modified_original_cannot_be_rendered(self):
        folder, _ = import_result(self.raw, self.root, 'self-test')
        (folder / 'original.json').write_bytes(self.raw + b'\n')
        renderer = self.renderer()
        with self.assertRaisesRegex(ValueError, 'has changed'):
            render_trial(folder, renderer)
        renderer.render.assert_not_called()


if __name__ == '__main__':
    unittest.main()
