"""Offline adapter tests; no real API key or external model calls."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import gzip
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
                               run_experiment, usage_totals, build_request, split_output,
                               numbered_experiment)
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
    def test_readable_names_increment_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, number = numbered_experiment(root, ['zhu', 'euro'], 'live')
            self.assertEqual(first.name, 'Experiment-live-Zhu-Yuanzhang_Rudolf-II-001')
            (first / 'keep.txt').write_text('original')
            second, number = numbered_experiment(root, ['zhu', 'euro'], 'live')
            self.assertEqual(number, 2)
            self.assertTrue(second.name.endswith('-002'))
            self.assertEqual((first / 'keep.txt').read_text(), 'original')
            dry, number = numbered_experiment(root, ['zhu', 'euro'], 'dry-run')
            self.assertEqual(number, 1)
            self.assertNotEqual(dry, first)

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
                expected_name = ('Zhu-Yuanzhang' if trial['portraitId'] == 'zhu' else 'Rudolf-II') + '-001'
                self.assertEqual(run.name, expected_name)
                self.assertEqual(Path(trial['finalPng']).name, expected_name + '.png')
                final_scene = read_json(output / trial['finalScene'])
                self.assertEqual(final_scene['image']['file'], expected_name + '.png')
                self.assertEqual(final_scene['image']['sha256'],
                                 hashlib.sha256((output / trial['finalPng']).read_bytes()).hexdigest())
                self.assertEqual(read_json(output / trial['explanation']),
                                 read_json(run / 'round-2/explanation.json'))
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
                        self.assertEqual(len(request['input']), 2 if number == 2 else 1)
                    schema = request['text']['format']['schema']
                    self.assertEqual(list(schema['properties']),
                                     ['items', 'explanation'] if number == 2 else ['items'])
                    if number < 2:
                        control, _ = build_request(run, number, call['previousResponseId'],
                                                   {**SETTINGS, 'finalExplanation': False})
                        self.assertEqual(request, control)
                    else:
                        self.assertEqual(request['input'][0]['role'], 'developer')
                        self.assertIn('FINAL-ROUND RESPONSE REQUIREMENT', request['input'][0]['content'])
                        full = read_json(run / 'calls/round-2/model-output.txt')
                        self.assertEqual(full['explanation'], read_json(run / 'round-2/explanation.json'))
                        self.assertEqual(set(read_json(run / 'round-2/response.txt')), {'items'})
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

    def test_explanation_validation(self):
        layout = read_json(FIXTURES / 'round-2.json')
        valid = {**layout, 'explanation': {'overall': 'Distinctive contours.', 'choices': [
            {'uids': [layout['items'][0]['uid']], 'feature': 'Face', 'reason': 'Similar contour.'}]}}
        self.assertEqual(split_output(json.dumps(valid), True), (layout, valid['explanation']))
        with self.assertRaises(ValueError):
            split_output(json.dumps(valid), False)
        for kind in ('unknown-uid', 'final-decision', 'missing-explanation'):
            invalid = deepcopy(valid)
            if kind == 'unknown-uid':
                invalid['explanation']['choices'][0]['uids'] = ['not-in-layout']
            elif kind == 'final-decision':
                invalid['explanation']['finalDecision'] = 'Done'
            else:
                del invalid['explanation']
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                split_output(json.dumps(invalid), True)

    def test_branch_uses_second_response_once_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client, _ = create_client(True, 30)
            with client:
                original = self.run_case(root, client)
            # A temporary fixture represents a saved live run; no external API is used.
            record = read_json(original / 'experiment.json')
            source = original / record['trials'][0]['run']
            for path in (original / 'experiment.json', source / 'run.json'):
                data = read_json(path)
                data['simulated'] = False
                path.write_text(json.dumps(data))
            before = {str(p.relative_to(original)): p.read_bytes() for p in original.rglob('*') if p.is_file()}
            second_id = record['trials'][0]['calls'][1]['responseId']
            layout = read_json(source / 'round-1/response.txt')
            client, fixture = create_client(True, 30)
            fixture.seed_branch(second_id, layout)
            with client, redirect_stdout(io.StringIO()):
                output = run_experiment(StubRenderer(), client, ['zhu'], root, SETTINGS, True, source)
            result = read_json(output / 'experiment.json')
            trial = result['trials'][0]
            run = output / trial['run']
            self.assertEqual(fixture.calls, [{'round': 2, 'previousResponseId': second_id, 'imageCount': 1}])
            self.assertEqual(len(trial['calls']), 1)
            self.assertEqual(len(trial['inheritedCalls']), 2)
            self.assertEqual(read_json(output / 'token-usage.json')['requests'], 1)
            self.assertTrue(trial['fork']['renderReplayMatched'])
            self.assertTrue((run / 'round-2/explanation.txt').exists())
            self.assertEqual(read_json(run / 'round-2/response.txt'), layout)
            self.assertTrue((run / 'comparison.json').exists())
            for n in (0, 1):
                self.assertEqual((run / f'round-{n}/feedback.png').read_bytes(),
                                 (source / f'round-{n}/feedback.png').read_bytes())
            self.assertEqual(before, {str(p.relative_to(original)): p.read_bytes()
                                      for p in original.rglob('*') if p.is_file()})

            # Pixel mismatch must stop before making even one request.
            broken = StubRenderer()
            broken.render = lambda scene, edge: {'full': broken.image(), 'feedback': broken.image()}
            client, fixture = create_client(True, 30)
            fixture.seed_branch(second_id, layout)
            with client, redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'changed pixels'):
                run_experiment(broken, client, ['zhu'], root, SETTINGS, True, source)
            self.assertEqual(fixture.calls, [])

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

    def test_live_client_negotiates_gzip_and_decodes_compressed_response(self):
        import httpx2
        fixture = DryResponses()
        encodings = []

        def handle(request):
            encodings.append(request.headers.get('accept-encoding'))
            self.assertEqual(encodings[-1], 'gzip')
            payload = fixture(request).content
            # A streaming body makes the actual HTTPX decoder run on read(),
            # instead of handing the SDK an already-decoded JSON fixture.
            return httpx2.Response(200, headers={'content-type': 'application/json',
                                               'content-encoding': 'gzip'},
                                   stream=httpx2.ByteStream(gzip.compress(payload)))

        # Intercept the real client's transport before any network access.
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), \
                patch.object(httpx2.HTTPTransport, 'handle_request', side_effect=handle):
            client, _ = create_client(False, 30)
            with client, tempfile.TemporaryDirectory() as directory:
                output = self.run_case(Path(directory), client)
                self.assertEqual(read_json(output / 'experiment.json')['status'], 'completed')
        self.assertEqual(encodings, ['gzip'] * 3)

    def test_raw_response_path_does_not_depend_on_sdk_typed_conversion(self):
        client, fixture = create_client(True, 30)
        with client, tempfile.TemporaryDirectory() as directory:
            # Typed SDK parsing may fail for an unexpected response variant;
            # the experiment only needs the raw JSON envelope and message text.
            with patch.object(client, '_process_response_data',
                              side_effect=TypeError('Fixture typed-conversion failure')) as typed:
                output = self.run_case(Path(directory), client)
            typed.assert_not_called()
            record = read_json(output / 'experiment.json')
            self.assertEqual(record['status'], 'completed')
            self.assertEqual(len(fixture.calls), 3)
            run = output / record['trials'][0]['run']
            self.assertTrue((run / 'round-2/explanation.txt').exists())
            self.assertTrue((run / 'calls/round-2/api-response.json').exists())

    def test_invalid_envelope_is_saved_with_usage_before_validation(self):
        import httpx2
        fixture = DryResponses()

        def handler(request):
            raw = fixture(request).json()
            raw['output'] = None
            raw['usage'] = {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}
            return httpx2.Response(200, json=raw)

        with tempfile.TemporaryDirectory() as directory, self.custom_client(handler) as client:
            with self.assertRaisesRegex(ValueError, 'output must be an array'):
                self.run_case(Path(directory), client)
            output = next(Path(directory).iterdir())
            record = read_json(output / 'experiment.json')
            run = output / record['trials'][0]['run']
            self.assertIsNone(read_json(run / 'calls/round-0/api-response.json')['output'])
            self.assertEqual(record['usage']['total_tokens'], 120)
            diagnostic = read_json(output / 'error.json')
            self.assertEqual(diagnostic['stage'], 'validate-model-output')
            self.assertTrue(diagnostic['frames'])
            self.assertEqual(len(fixture.calls), 1)

    def test_type_error_reports_location_without_credentials(self):
        def handler(request):
            raise TypeError('Fixture failure with env-secret-sentinel and Bearer sk-test-sentinel')

        with tempfile.TemporaryDirectory() as directory, self.custom_client(handler) as client:
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'env-secret-sentinel'}), self.assertRaises(Exception):
                self.run_case(Path(directory), client)
            output = next(Path(directory).iterdir())
            diagnostic = read_json(output / 'error.json')
            # The SDK can wrap a transport exception as APIConnectionError.
            self.assertEqual(diagnostic['stage'], 'api-request')
            self.assertTrue(diagnostic['frames'])
            cause = diagnostic['causes'][-1] if diagnostic.get('causes') else diagnostic
            self.assertEqual(cause['type'], 'TypeError')
            self.assertIn('Fixture failure', cause['message'])
            self.assertIn('[REDACTED]', cause['message'])
            for path in output.rglob('*.json'):
                self.assertNotIn('env-secret-sentinel', path.read_text())
                self.assertNotIn('sk-test-sentinel', path.read_text())

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
