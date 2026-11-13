"""Offline archival checks: preservation, grouping, and failed-attempt handling."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

from ai_results import reserve_group, register_experiment, read, write, check_portraits_available


class ResultTests(unittest.TestCase):
    def fixture(self, root, portrait='zhu', status='completed'):
        batch = root / portrait
        run = batch / 'Person-001'
        items = [{'uid': 'one', 'id': 'pear'}]
        for number in (1, 2):
            write(run / f'round-{number}/feedback.json', {
                'scene': {'items': items}, 'snapshot': {'png': 'snapshot.png'}})
            (run / f'round-{number}/snapshot.png').write_bytes(b'PNG-test-bytes')
        write(run / 'calls/round-2/api-response.json', {'id': 'paid-response', 'usage': {'total_tokens': 100}})
        (run / 'final.png').write_bytes(b'PNG-test-bytes')
        write(batch / 'experiment.json', {'experimentId': batch.name, 'status': status,
            'settings': {'model': 'model', 'reasoning': 'high'},
            'trials': [{'portraitId': portrait, 'run': run.name, 'status': status,
                        'finalPng': 'Person-001/final.png'}]})
        return batch

    def test_move_preserves_paid_records_pairs_and_blocks_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            group = reserve_group(root / 'results', 'model', 'high')
            first = self.fixture(root)
            raw = (first / 'Person-001/calls/round-2/api-response.json').read_bytes()
            register_experiment(group, first, move=True)
            self.assertFalse(first.exists())
            self.assertEqual((group / 'records/attempt-001/Person-001/calls/round-2/api-response.json').read_bytes(), raw)
            self.assertFalse(read(group / 'summary.json')['completePair'])
            with self.assertRaises(ValueError):
                check_portraits_available(group, ['zhu'])
            register_experiment(group, self.fixture(root, 'euro'), move=True)
            self.assertTrue(read(group / 'summary.json')['completePair'])
            self.assertTrue((group / '02-Rudolf-II.png').exists())
            self.assertIn('2 张最终图', (root / 'results/index.html').read_text())
            self.assertEqual(len(read(root / 'results/organization-manifest.json')['paidResponses']), 2)
            next_group = reserve_group(root / 'results', 'model', 'high')
            self.assertEqual(next_group.name, 'model_high_02')

    def test_internal_failed_attempt_preserved_without_final_image(self):
        with tempfile.TemporaryDirectory() as temp:
            group = reserve_group(Path(temp), 'model', 'high')
            source = self.fixture(group / 'records', status='failed')
            register_experiment(group, source)
            register_experiment(group, source)
            self.assertEqual(len(read(group / 'summary.json')['sourceExperiments']), 1)
            self.assertFalse((group / '01-Zhu-Yuanzhang.png').exists())
            self.assertTrue((source / 'Person-001/calls/round-2/api-response.json').exists())

    def test_mismatched_model_is_not_moved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.fixture(root)
            group = reserve_group(root / 'results', 'different', 'high')
            with self.assertRaises(ValueError):
                register_experiment(group, source, move=True)
            self.assertTrue(source.exists())

    def test_cli_automatically_saves_live_layout_with_mock_transport(self):
        from openai_experiment import main, create_client
        from test_openai_experiment import StubRenderer
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch('ai_results.DEFAULT_ROOT', root), \
                 patch('openai_experiment.create_client', side_effect=lambda *a: create_client(True, 900)), \
                 patch('openai_experiment.BrowserRenderer') as renderer, \
                 patch('sys.argv', ['openai_experiment.py', '--portrait', 'all']), \
                 redirect_stdout(io.StringIO()):
                renderer.return_value.__enter__.return_value = StubRenderer()
                main()
            group = root / 'gpt-6.1-sol_medium_01'
            self.assertTrue(read(group / 'summary.json')['completePair'])
            self.assertTrue((group / '01-Zhu-Yuanzhang.png').exists())
            self.assertTrue((group / '02-Rudolf-II.png').exists())
            self.assertEqual(len(list((group / 'records').rglob('api-response.json'))), 6)


if __name__ == '__main__':
    unittest.main()
