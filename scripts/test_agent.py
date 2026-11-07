"""Protocol tests; opt into real Chromium with FOODFACE_BROWSER_TEST=1."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import (ROOT, BrowserRenderer, apply_response, empty_scene, read_json,
                   start_run, submit_response, write_json)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.initial = read_json(ROOT / 'examples/agent/initial.json')
        self.scene = apply_response(empty_scene('zhu'), self.initial)

    def test_complete_layout_keeps_uids_and_original_state(self):
        original = deepcopy(self.scene)
        response = deepcopy(self.initial)
        response['items'][1]['x'] = .6
        result = apply_response(self.scene, response)
        self.assertEqual(self.scene, original)
        self.assertEqual(result['items'][1]['x'], .6)
        self.assertEqual(result['items'][2], original['items'][2])
        self.assertEqual(result['items'][1]['id'], result['items'][2]['id'])

    def test_full_replacement_adds_omits_and_reorders(self):
        new = {**self.scene['items'][1], 'uid': 'f4'}
        response = {'items': [new, self.scene['items'][2], self.scene['items'][0]]}
        result = apply_response(self.scene, response)
        self.assertEqual([i['uid'] for i in result['items']], ['f4', 'f3', 'f1'])
        self.assertEqual(apply_response(result, response), result)
        self.assertEqual(apply_response(result, {'items': []})['items'], [])

    def test_reject_invalid_full_layout_atomically(self):
        original = deepcopy(self.scene)
        item = original['items'][0]
        cases = [
            {}, {'update': []}, {'remove': []}, {'add': []}, {'order': []},
            {'items': [], 'update': []},
            {'items': [{**item, 'x': 2}]},
            {'items': [{**item, 'size': float('nan')}]},
            {'items': [{**item, 'angle': True}]},
            {'items': [{**item, 'id': 'pear'}]},
            {'items': [{**item, 'id': 'unknown'}]},
            {'items': [{**item, 'uid': 'retired'}]},
            {'items': [{**item, 'uid': []}]},
            {'items': [item, item]}, {'items': [{**item, 'scaleY': 2}]},
            {'items': [{'uid': 'f1'}]}, {'items': [], 'reasoning': 'text'},
        ]
        for response in cases:
            with self.subTest(response=response), self.assertRaises(ValueError):
                apply_response(self.scene, response, used_uids={'retired'})
            self.assertEqual(self.scene, original)

    def test_removed_uid_cannot_return_but_fresh_replacement_can(self):
        result = apply_response(self.scene, {'items': self.scene['items'][1:]})
        with self.assertRaisesRegex(ValueError, 'removed uid'):
            apply_response(result, self.initial, used_uids={'f1', 'f2', 'f3'})
        replacement = {**self.scene['items'][0], 'uid': 'f4', 'id': 'pear'}
        result = apply_response(self.scene, {'items': [replacement]})
        self.assertEqual(result['items'], [replacement])

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'response.json'
            path.write_text('{"items":[],"items":[]}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
                read_json(path)

    def test_no_stale_150_item_limit(self):
        items = [{**self.initial['items'][0], 'uid': str(i)} for i in range(151)]
        self.assertEqual(len(apply_response(empty_scene('zhu'), {'items': items})['items']), 151)

    def test_flip_flags_preserve_geometry_and_follow_full_state_semantics(self):
        original = deepcopy(self.scene)
        for flip_x, flip_y in ((True, False), (False, True), (True, True), (False, False)):
            with self.subTest(flipX=flip_x, flipY=flip_y):
                response = deepcopy(self.initial)
                response['items'][0].update(flipX=flip_x, flipY=flip_y)
                result = apply_response(self.scene, response)
                self.assertEqual(result['items'][0], response['items'][0])
                for field in ('uid', 'id', 'x', 'y', 'size', 'angle'):
                    self.assertEqual(result['items'][0][field], original['items'][0][field])
                # An omitted flag in the next complete layout is false, not inherited.
                restored = apply_response(result, self.initial)
                self.assertFalse(restored['items'][0].get('flipX', False))
                self.assertFalse(restored['items'][0].get('flipY', False))
        self.assertEqual(self.scene, original)

    def test_flip_flags_require_booleans(self):
        for field in ('flipX', 'flipY'):
            for value in (0, 1, 'true', 'false', None, [], {}):
                response = deepcopy(self.initial)
                response['items'][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    apply_response(self.scene, response)


@unittest.skipUnless(os.environ.get('FOODFACE_BROWSER_TEST') == '1', 'Set FOODFACE_BROWSER_TEST=1 for Chromium tests')
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = BrowserRenderer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.renderer.__exit__(None, None, None)

    def test_three_rounds_both_portraits_and_export_parity(self):
        for portrait in ('zhu', 'euro'):
            with self.subTest(portrait=portrait), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run = start_run(self.renderer, portrait, root)
                manifest = read_json(run / 'inputs/manifest.json')
                self.assertEqual(len(manifest['foods']), 16)
                self.assertEqual(manifest['images']['original']['width'], manifest['images']['empty']['width'])
                self.assertLess(manifest['faceBounds']['left'], manifest['faceBounds']['right'])
                for food in manifest['foods']:
                    self.assertGreater(food['crop']['w'], 0)
                    self.assertGreater(food['crop']['h'], 0)
                prompt = (run / 'inputs/prompt.txt').read_text()
                self.assertNotIn('{{', prompt)
                self.assertEqual(read_json(run / 'run.json')['protocolVersion'], 2)
                bad = root / 'bad.json'
                bad.write_text('{"items":[{"uid":"f1"}]}')
                with self.assertRaises(ValueError):
                    submit_response(self.renderer, run, bad)
                self.assertFalse(list(run.glob('round-*')))
                self.assertEqual(len(list(run.glob('rejected-*.json'))), 1)
                for number, name in enumerate(('initial', 'adjust-1', 'adjust-2')):
                    source = ROOT / f'examples/agent/{name}.json'
                    folder = submit_response(self.renderer, run, source)
                    feedback = read_json(folder / 'feedback.json')
                    self.assertEqual(feedback['remainingAdjustments'], 2 - number)
                    self.assertEqual((folder / 'response.txt').read_text(), source.read_text())
                    document = read_json(folder / feedback['snapshot']['json'])
                    png = (folder / feedback['snapshot']['png']).read_bytes()
                    self.assertEqual(document['image']['sha256'], hashlib.sha256(png).hexdigest())
                    self.assertEqual(document['items'], feedback['scene']['items'])
                    self.assertEqual(feedback['scene']['items'], read_json(source)['items'])
                    next_prompt = (folder / 'next-prompt.txt').read_text()
                    if number < 2:
                        self.assertIn('complete layout', next_prompt)
                        self.assertNotIn('Current items', next_prompt)
                with self.assertRaisesRegex(ValueError, 'Run complete'):
                    submit_response(self.renderer, run, source)
                self.assertEqual(len(list(run.glob('round-*'))), 3)
                # Compare a human-page submission with the agent rendering of
                # that exact scene, without relying on browser draft storage.
                page = self.renderer.browser.new_page()
                try:
                    submissions = []
                    page.on('request', lambda request: submissions.append(request.url)
                            if request.method == 'POST' else None)
                    page.goto(self.renderer.url + '/index.html')
                    page.locator(f'[data-portrait="{portrait}"]').click()
                    for food in ('mango', 'blueberry', 'blueberry', 'chili'):
                        page.locator(f'[data-food="{food}"]').click()
                    self.assertEqual(page.locator('#objectCount').inner_text(), '4 items')
                    page.locator('#undo').click()
                    self.assertEqual(page.locator('#objectCount').inner_text(), '3 items')
                    page.locator('#redo').click()
                    self.assertEqual(page.locator('#objectCount').inner_text(), '4 items')
                    page.locator('.layer-chip').first.click()
                    page.locator('#rotation').evaluate('e => {e.value="80";e.dispatchEvent(new Event("input"));e.dispatchEvent(new Event("change"))}')
                    page.locator('#size').evaluate('e => {e.value="27";e.dispatchEvent(new Event("input"));e.dispatchEvent(new Event("change"))}')
                    page.locator('#flipHorizontal').click()
                    if portrait == 'euro':
                        page.locator('#flipVertical').click()
                    page.locator('#gender').select_option('prefer-not-to-say')
                    page.locator('#age').fill('25')
                    page.locator('#nationality').fill('Test nationality')
                    page.locator('[data-language="zh"]').click()
                    page.locator('#export').click()
                    page.locator('#confirmSubmission').click()
                    page.locator('#jsonResult').wait_for(state='visible')
                    raw = page.locator('#resultJson').input_value()
                    scene = json.loads(raw)
                    self.assertEqual(scene['demographics'], {
                        'gender': 'prefer-not-to-say', 'age': 25, 'nationality': 'Test nationality'})
                    self.assertEqual(scene['experiment']['interfaceLanguage'], 'zh')
                    self.assertEqual(submissions, [])
                    page.locator('[data-language="en"]').click()
                    self.assertEqual(page.locator('#resultJson').input_value(), raw)
                    human_png = page.locator('#collage').evaluate('canvas => canvas.toDataURL("image/png").split(",")[1]')
                    self.assertEqual(len(scene['items']), 4)
                    self.assertTrue(scene['items'][0]['flipX'])
                    self.assertEqual(scene['items'][0]['flipY'], portrait == 'euro')
                    result = self.renderer.render(scene, 1024)
                    self.assertEqual(hashlib.sha256(base64.b64decode(human_png)).hexdigest(),
                                     hashlib.sha256(base64.b64decode(result['full']['png'])).hexdigest())
                finally:
                    page.close()

    def test_failed_write_does_not_consume_round_and_source_changes_stop_run(self):
        with tempfile.TemporaryDirectory() as directory:
            run = start_run(self.renderer, 'zhu', Path(directory))
            source = ROOT / 'examples/agent/initial.json'
            with patch('agent.save_snapshot', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    submit_response(self.renderer, run, source)
            self.assertFalse(list(run.glob('round-*')))
            self.assertFalse(list(run.glob('.pending-*')))
            self.assertFalse((run / '.lock').exists())
            with patch('agent.hashes', return_value={}):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    submit_response(self.renderer, run, source)
            folder = submit_response(self.renderer, run, source)
            self.assertEqual(folder.name, 'round-0')


if __name__ == '__main__':
    unittest.main()
