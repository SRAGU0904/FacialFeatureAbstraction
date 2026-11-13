"""Offline DeepSeek transport/history checks; never read real credentials."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import read_json
from openai_experiment import (PROVIDERS, DryResponses, create_client, run_experiment,
                               response_text, FINAL_PROMPT, normalize_sizes, repair_second_round)
from test_openai_experiment import StubRenderer

SETTINGS = {'provider': 'deepseek', 'model': 'deepseek-flash', 'reasoning': 'high',
            'maxOutputTokens': 32768, 'imageDetail': 'high', 'maxEdge': 1024,
            'timeoutSeconds': 900, 'finalExplanation': True}


class DeepSeekTests(unittest.TestCase):
    def test_full_history_images_explanation_and_usage_for_both_portraits(self):
        import base64
        import httpx2
        from openai import OpenAI, DefaultHttpxClient
        requests = []
        fixture = DryResponses('deepseek')

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            response = fixture(request)
            raw = response.json()
            if sum(m['role'] == 'assistant' for m in body['input']) == 1:
                layout = json.loads(raw['output'][0]['content'][0]['text'])
                layout['items'][0]['size'] = .022
                raw['output'][0]['content'][0]['text'] = json.dumps(layout)
            # Deliberately distinct from the artwork explanation; not replayed.
            raw['output'].insert(0, {'type': 'reasoning', 'content': [
                {'type': 'reasoning_text', 'text': 'PRIVATE-TEST-SENTINEL'}]})
            raw['usage'] = {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120,
                            'input_tokens_details': {'cached_tokens': 50},
                            'output_tokens_details': {'reasoning_tokens': 12}}
            return httpx2.Response(200, json=raw)

        with tempfile.TemporaryDirectory() as tmp, OpenAI(
                api_key='test-placeholder', base_url=PROVIDERS['deepseek']['url'], max_retries=0,
                http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler),
                                              trust_env=False)) as client:
            with redirect_stdout(io.StringIO()) as terminal:
                output = run_experiment(StubRenderer(), client, ['zhu', 'euro'], Path(tmp),
                                        SETTINGS, dry_run=True)
            self.assertIn('reasoning=72', terminal.getvalue())
            record = read_json(output / 'experiment.json')
            self.assertEqual(record['status'], 'completed')
            self.assertEqual(record['historyMode'], 'full_messages')
            self.assertEqual(record['endpoint'], 'https://api.deepseek.com/responses')
            self.assertEqual(record['usage']['input_tokens'], 600)
            self.assertEqual(record['usage']['total_tokens'], 720)
            self.assertEqual(len(requests), 6)
            for ti, trial in enumerate(record['trials']):
                run = output / trial['run']
                self.assertTrue((output / trial['finalPng']).exists())
                self.assertTrue((output / trial['explanationText']).exists())
                for n in range(3):
                    body = requests[ti * 3 + n]
                    logged = read_json(run / f'calls/round-{n}/request.json')
                    self.assertNotIn('PRIVATE-TEST-SENTINEL', json.dumps(body))
                    self.assertNotIn('data:image', json.dumps(logged))
                    for unsupported in ('store', 'service_tier', 'previous_response_id'):
                        self.assertNotIn(unsupported, body)
                    messages = body['input']
                    self.assertEqual([m['role'] for m in messages],
                                     ['system', 'user'] + ['assistant', 'user'] * n)
                    initial_prompt = (run / 'inputs/prompt.txt').read_text()
                    self.assertTrue(messages[0]['content'].startswith(initial_prompt))
                    self.assertEqual(FINAL_PROMPT.read_text() in messages[0]['content'], n == 2)
                    self.assertEqual('explanation' in body['text']['format']['schema']['properties'], n == 2)
                    self.assertEqual(messages[1], requests[ti * 3]['input'][1])
                    images = 0
                    for m, lm in zip(messages, logged['input']):
                        if m['role'] == 'user':
                            for p, lp in zip(m['content'], lm['content']):
                                if p['type'] == 'input_image':
                                    images += 1
                                    data = base64.b64decode(p['image_url'].split(',', 1)[1])
                                    self.assertEqual(data, (run / lp['localFile']).read_bytes())
                                    self.assertEqual(hashlib.sha256(data).hexdigest(), lp['sha256'])
                        elif m['role'] == 'assistant':
                            round_number = (messages.index(m) - 2) // 2
                            expected = (run / f'round-{round_number}/response.txt' if round_number == 1
                                        else run / f'calls/round-{round_number}/model-output.txt')
                            self.assertEqual(m['content'],
                                             expected.read_text())
                    self.assertEqual(images, 3 + n)
                self.assertEqual(read_json(run / 'calls/round-1/model-output.txt')['items'][0]['size'], .022)
                self.assertEqual(read_json(run / 'round-1/response.txt')['items'][0]['size'], .03)

    def test_minimum_size_only_preserves_original(self):
        original = {'items': [{'uid': 'small', 'size': .022}, {'uid': 'limit', 'size': .03},
                              {'uid': 'big', 'size': 1.0}, {'uid': 'invalid', 'size': True}]}
        fixed, changes = normalize_sizes(original)
        self.assertEqual(original['items'][0]['size'], .022)
        self.assertEqual(fixed['items'][0]['size'], .03)
        self.assertEqual(fixed['items'][1:], original['items'][1:])
        self.assertEqual(changes, [{'uid': 'small', 'field': 'size', 'before': .022, 'after': .03}])

    def test_local_repair_preserves_source_then_calls_only_round_three(self):
        import httpx2
        from openai import OpenAI, DefaultHttpxClient
        fixture = DryResponses('deepseek')
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            raw = fixture(request).json()
            if len(requests) == 2:
                data = json.loads(raw['output'][0]['content'][0]['text'])
                data['items'][0]['size'] = .022
                raw['output'][0]['content'][0]['text'] = json.dumps(data)
            return httpx2.Response(200, json=raw)

        with tempfile.TemporaryDirectory() as tmp, OpenAI(
                api_key='test-placeholder', base_url=PROVIDERS['deepseek']['url'], max_retries=0,
                http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler),
                                              trust_env=False)) as client, redirect_stdout(io.StringIO()):
            # Reproduce the old failure before automatic normalization existed.
            with patch('openai_experiment.normalize_sizes', side_effect=lambda layout: (layout, [])):
                with self.assertRaisesRegex(ValueError, 'Invalid item size'):
                    run_experiment(StubRenderer(), client, ['zhu'], Path(tmp), SETTINGS, dry_run=False)
            source_record = next(Path(tmp).glob('*/experiment.json'))
            source = source_record.parent / read_json(source_record)['trials'][0]['run']
            source_files = {str(p.relative_to(source_record.parent)): p.read_bytes()
                            for p in source_record.parent.rglob('*') if p.is_file()}
            repaired = repair_second_round(StubRenderer(), source, Path(tmp))
            self.assertEqual(len(requests), 2)  # Offline repair made no request.
            self.assertEqual(read_json(repaired / 'calls/round-1/model-output.txt')['items'][0]['size'], .022)
            self.assertEqual(read_json(repaired / 'round-1/response.txt')['items'][0]['size'], .03)
            for relative, data in source_files.items():
                self.assertEqual((source_record.parent / relative).read_bytes(), data)
            result = run_experiment(StubRenderer(), client, ['zhu'], Path(tmp), SETTINGS,
                                    dry_run=True, source=repaired)
            self.assertEqual(len(requests), 3)
            self.assertEqual(json.loads(requests[-1]['input'][-2]['content'])['items'][0]['size'], .03)
            record = read_json(result / 'experiment.json')
            self.assertEqual(record['status'], 'completed')
            self.assertEqual([c['round'] for c in record['trials'][0]['calls']], [2])
            self.assertEqual(record['maxCallsPerPortrait'], 1)

    def test_dry_client_does_not_request_a_real_key(self):
        with patch('openai_experiment.os.environ', {}):
            client, transport = create_client(True, 900, 'deepseek')
            with client:
                self.assertEqual(str(client.base_url), 'https://api.deepseek.com')
                self.assertEqual(client.api_key, 'dry-run-placeholder')
                self.assertEqual(transport.provider, 'deepseek')

    def test_missing_live_key_names_deepseek(self):
        with patch('openai_experiment.os.environ', {}):
            with self.assertRaisesRegex(ValueError, 'DEEPSEEK_API_KEY'):
                create_client(False, 900, 'deepseek')

    def test_token_limit_message_identifies_shared_budget(self):
        with self.assertRaisesRegex(ValueError, 'reasoning and JSON share this limit'):
            response_text({'status': 'incomplete',
                           'incomplete_details': {'reason': 'max_output_tokens'}})


if __name__ == '__main__':
    unittest.main()
