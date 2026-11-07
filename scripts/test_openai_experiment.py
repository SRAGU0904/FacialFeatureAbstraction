"""Offline adapter tests; no real API key or external model calls."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent import BrowserRenderer, PORTRAITS, food_ids, read_json
from openai_experiment import (API_URL, FIXTURES, MODEL, DryResponses, create_client,
                               run_experiment, usage_totals)
from test_server import png_image

HAS_SDK = importlib.util.find_spec('openai') is not None
SETTINGS = {'model': MODEL, 'reasoning': 'medium', 'maxOutputTokens': 8192,
            'imageDetail': 'high', 'maxEdge': 1024, 'timeoutSeconds': 180}


class StubRenderer:
    """Only for fast failure tests. Real pixels are exercised by BrowserTests below."""
    browser = SimpleNamespace(version='unit-test-stub')

    def image(self, width=1, height=1):
        return {'width': width, 'height': height,
                'png': base64.b64encode(png_image(width, height)).decode()}

    def inputs(self, portrait, _max_edge):
        width, height = PORTRAITS[portrait]
        return {'canvas': {'width': width, 'height': height},
                'original': self.image(), 'empty': self.image(), 'foods': self.image(),
                'catalog': [{'id': key, 'crop': {'w': 10, 'h': 20}} for key in sorted(food_ids())],
                'faceBounds': {'left': .3, 'top': .2, 'right': .7, 'bottom': .7}}

    def render(self, scene, _max_edge):
        return {'full': self.image(scene['canvas']['width'], scene['canvas']['height']),
                'feedback': self.image()}


@unittest.skipUnless(HAS_SDK, 'Install scripts/requirements-openai.txt')
class AdapterTests(unittest.TestCase):
    def run_case(self, root, client, portraits=('zhu',), renderer=None):
        with redirect_stdout(io.StringIO()):
            return run_experiment(renderer or StubRenderer(), client, portraits, root,
                                  deepcopy(SETTINGS), dry_run=True)

    def custom_client(self, handler):
        import httpx2
        from openai import OpenAI, DefaultHttpxClient
        return OpenAI(api_key='test-placeholder', base_url=API_URL, max_retries=0,
                      http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler), trust_env=False))

    def test_sdk_history_images_full_layouts_and_safe_logs(self):
        requests = []
        fixture = DryResponses()

        def handler(request):
            requests.append(json.loads(request.content))
            return fixture(request)

        with tempfile.TemporaryDirectory() as directory, self.custom_client(handler) as client:
            output = self.run_case(Path(directory), client, ('zhu', 'euro'))
            record = read_json(output / 'experiment.json')
            self.assertEqual(record['status'], 'completed')
            self.assertEqual(len(requests), 6)
            self.assertIsNone(record['usage'])
            for trial_index, trial in enumerate(record['trials']):
                run = output / trial['run']
                self.assertTrue((output / trial['finalPng']).exists())
                for number, call in enumerate(trial['calls']):
                    request = requests[trial_index * 3 + number]
                    self.assertEqual(request['service_tier'], 'default')
                    self.assertTrue(request['store'])
                    self.assertTrue(request['text']['format']['strict'])
                    self.assertIsNone(call['actualModel'])
                    if number == 0:
                        self.assertNotIn('previous_response_id', request)
                        self.assertEqual(request['input'][0]['role'], 'developer')
                    else:
                        self.assertEqual(request['previous_response_id'], trial['calls'][number - 1]['responseId'])
                        self.assertEqual(len(request['input']), 1)
                    saved = read_json(output / call['request'])
                    parts = request['input'][-1]['content']
                    logged_parts = saved['input'][-1]['content']
                    self.assertEqual(sum(p['type'] == 'input_image' for p in parts), 3 if number == 0 else 1)
                    for wire, logged in zip(parts, logged_parts):
                        if wire['type'] != 'input_image':
                            self.assertEqual(wire, logged)
                            continue
                        png = base64.b64decode(wire['image_url'].split(',', 1)[1])
                        self.assertEqual(png, (run / logged['localFile']).read_bytes())
                        self.assertEqual(hashlib.sha256(png).hexdigest(), logged['sha256'])
                        self.assertNotIn('image_url', logged)
                    scene = read_json(run / f'round-{number}/feedback.json')['scene']
                    self.assertEqual(scene['items'], read_json(FIXTURES / f'round-{number}.json')['items'])
                    self.assertEqual(call['status'], 'rendered')
                self.assertFalse((run / 'round-3').exists())
                all_logs = '\n'.join(p.read_text() for p in run.rglob('*.json'))
                self.assertNotIn('test-placeholder', all_logs)
                self.assertNotIn('Authorization', all_logs)

    def test_dry_client_ignores_real_key_and_base_url_environment(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'secret-sentinel',
                                    'OPENAI_BASE_URL': 'https://example.invalid/v1'}):
            client, fixture = create_client(True, 30)
            with client, tempfile.TemporaryDirectory() as directory:
                output = self.run_case(Path(directory), client)
                self.assertEqual(client.api_key, 'dry-run-placeholder')
                self.assertEqual(len(fixture.calls), 3)
                for path in output.rglob('*.json'):
                    self.assertNotIn('secret-sentinel', path.read_text())

    def test_live_requires_key_before_rendering(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
                create_client(False, 30)

    def test_bad_responses_stop_and_preserve_prior_round(self):
        import httpx2
        for kind in ('incomplete', 'refusal', 'invalid-json', 'retired-identity', 'render-error'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                fixture = DryResponses()
                count = 0

                def handler(request):
                    nonlocal count
                    result = fixture(request)
                    count += 1
                    if count == 2:
                        raw = result.json()
                        if kind == 'incomplete':
                            raw['status'] = 'incomplete'
                            raw['incomplete_details'] = {'reason': 'max_output_tokens'}
                        elif kind == 'refusal':
                            raw['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'Fixture refusal'}]
                        elif kind == 'invalid-json':
                            raw['output'][0]['content'][0]['text'] = '{"items":[],"items":[]}'
                        elif kind == 'retired-identity':
                            layout = read_json(FIXTURES / 'round-1.json')
                            layout['items'][0]['id'] = 'pear'
                            raw['output'][0]['content'][0]['text'] = json.dumps(layout)
                        return httpx2.Response(200, json=raw)
                    return result

                renderer = StubRenderer()
                original_render = renderer.render
                render_count = 0

                def render(scene, edge):
                    nonlocal render_count
                    render_count += 1
                    if kind == 'render-error' and render_count == 2:
                        raise OSError('Fixture disk/render failure')
                    return original_render(scene, edge)

                renderer.render = render
                with self.custom_client(handler) as client, self.assertRaises((ValueError, OSError)):
                    self.run_case(Path(directory), client, renderer=renderer)
                output = next(Path(directory).iterdir())
                record = read_json(output / 'experiment.json')
                self.assertEqual(record['status'], 'failed')
                self.assertEqual(count, 2)
                trial = record['trials'][0]
                self.assertEqual(trial['calls'][0]['status'], 'rendered')
                self.assertEqual(trial['calls'][1]['status'], 'failed')
                run = output / trial['run']
                self.assertTrue((run / 'round-0/feedback.png').exists())
                self.assertTrue((run / 'calls/round-1/api-response.json').exists())
                self.assertFalse((run / 'round-1').exists())
                self.assertFalse((run / '.lock').exists())

    def test_http_errors_and_timeouts_are_not_retried_or_logged_with_secrets(self):
        import httpx2
        for failure in ('timeout', 'rate-limit'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                count = 0

                def handler(request):
                    nonlocal count
                    count += 1
                    if failure == 'timeout':
                        raise httpx2.ReadTimeout('secret-sentinel', request=request)
                    return httpx2.Response(429, json={'error': {'message': 'secret-sentinel', 'type': 'rate_limit'}})

                with self.custom_client(handler) as client, self.assertRaises(Exception):
                    self.run_case(Path(directory), client)
                self.assertEqual(count, 1)
                record_path = next(Path(directory).glob('*/experiment.json'))
                record = read_json(record_path)
                self.assertEqual(record['status'], 'failed')
                self.assertNotIn('secret-sentinel', record_path.read_text())
                if failure == 'rate-limit':
                    self.assertEqual(record['error']['httpStatus'], 429)

    def test_usage_counts_reasoning_and_cache_without_inventing_dry_usage(self):
        self.assertIsNone(usage_totals([{'usage': None}]))
        usage = {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150,
                 'input_tokens_details': {'cached_tokens': 80},
                 'output_tokens_details': {'reasoning_tokens': 30}}
        self.assertEqual(usage_totals([{'usage': usage}] * 2),
                         {'input_tokens': 200, 'output_tokens': 100, 'total_tokens': 300,
                          'cached_tokens': 160, 'reasoning_tokens': 60})
        missing = {**usage, 'output_tokens_details': None}
        self.assertIsNone(usage_totals([{'usage': missing}])['reasoning_tokens'])

    def test_token_report_matches_terminal_and_preserves_partial_usage(self):
        import httpx2
        for fail_second in (False, True):
            with self.subTest(fail_second=fail_second), tempfile.TemporaryDirectory() as directory:
                fixture = DryResponses()
                requests = 0

                def handler(request):
                    nonlocal requests
                    requests += 1
                    if fail_second and requests == 2:
                        raise httpx2.ReadTimeout('Fixture timeout', request=request)
                    raw = fixture(request).json()
                    raw['usage'] = {'input_tokens': 1000, 'output_tokens': 500, 'total_tokens': 1500,
                                    'input_tokens_details': {'cached_tokens': 200},
                                    'output_tokens_details': {'reasoning_tokens': 300}}
                    return httpx2.Response(200, json=raw)

                terminal = io.StringIO()
                with self.custom_client(handler) as client, redirect_stdout(terminal):
                    if fail_second:
                        with self.assertRaises(Exception):
                            run_experiment(StubRenderer(), client, ['zhu'], Path(directory), SETTINGS, True)
                    else:
                        run_experiment(StubRenderer(), client, ['zhu'], Path(directory), SETTINGS, True)
                output = next(Path(directory).iterdir())
                summary = read_json(output / 'token-usage.json')
                record = read_json(output / 'experiment.json')
                self.assertEqual(summary['totals'], record['usage'])
                self.assertEqual(summary['requestsWithUsage'], 1 if fail_second else 3)
                self.assertEqual(summary['requests'], 2 if fail_second else 3)
                self.assertEqual(summary['status'], 'failed' if fail_second else 'completed')
                self.assertEqual(summary['totals']['input_tokens'], 1000 if fail_second else 3000)
                self.assertEqual(summary['totals']['output_tokens'], 500 if fail_second else 1500)
                self.assertEqual(summary['totals']['reasoning_tokens'], 300 if fail_second else 900)
                self.assertIn('input=1,000 | output=500 | reasoning=300', terminal.getvalue())
                if fail_second:
                    self.assertIsNone(summary['portraits'][0]['rounds'][1]['tokens'])
                    self.assertIn('usage reported for 1/2 requests', terminal.getvalue())
                else:
                    self.assertIn('Experiment total tokens: input=3,000 | output=1,500 | reasoning=900',
                                  terminal.getvalue())


@unittest.skipUnless(HAS_SDK and os.environ.get('FOODFACE_BROWSER_TEST') == '1',
                     'Install SDK and set FOODFACE_BROWSER_TEST=1 for Chromium tests')
class OpenAIBrowserTests(unittest.TestCase):
    def test_both_portraits_complete_with_real_rendering(self):
        client, fixture = create_client(True, 30)
        with tempfile.TemporaryDirectory() as directory, client, BrowserRenderer() as renderer:
            with redirect_stdout(io.StringIO()):
                output = run_experiment(renderer, client, list(PORTRAITS), Path(directory), SETTINGS, True)
            record = read_json(output / 'experiment.json')
            self.assertEqual(record['status'], 'completed')
            self.assertEqual([call['imageCount'] for call in fixture.calls], [3, 1, 1, 3, 1, 1])
            for trial in record['trials']:
                run = output / trial['run']
                png_hashes = set()
                for number in range(3):
                    folder = run / f'round-{number}'
                    feedback = read_json(folder / 'feedback.json')
                    snapshot = read_json(folder / feedback['snapshot']['json'])
                    png = (folder / feedback['snapshot']['png']).read_bytes()
                    self.assertEqual(snapshot['image']['sha256'], hashlib.sha256(png).hexdigest())
                    self.assertEqual(snapshot['items'], read_json(FIXTURES / f'round-{number}.json')['items'])
                    self.assertEqual(feedback['remainingAdjustments'], 2 - number)
                    png_hashes.add(hashlib.sha256(png).hexdigest())
                self.assertEqual(len(png_hashes), 3)
                self.assertEqual(len(list(run.glob('round-*'))), 3)


if __name__ == '__main__':
    unittest.main()
