"""Bailian Responses contract tests with an HTTP mock; no real credentials."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import read_json
from openai_experiment import (PROVIDERS, DryResponses, create_client, run_experiment,
                               FINAL_PROMPT, output_schema)
from test_openai_experiment import StubRenderer

SETTINGS = {'provider': 'qwen', 'model': 'qwen3.8-max', 'reasoning': 'xhigh',
            'maxOutputTokens': 65536, 'imageDetail': 'auto', 'maxEdge': 1024,
            'timeoutSeconds': 900, 'finalExplanation': True, 'region': 'cn-beijing'}


class QwenTests(unittest.TestCase):
    def test_both_portraits_history_schema_explanation_usage_and_archive(self):
        import httpx2
        from openai import OpenAI, DefaultHttpxClient
        from ai_results import reserve_group, register_experiment
        fixture = DryResponses('qwen')
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            raw = fixture(request).json()
            raw['output'].insert(0, {'type': 'reasoning', 'summary': [
                {'type': 'summary_text', 'text': 'PRIVATE-MOCK-SENTINEL'}]})
            raw['usage'] = {'input_tokens': 100, 'output_tokens': 40, 'total_tokens': 140,
                            'input_tokens_details': {'cached_tokens': 50},
                            'output_tokens_details': {'reasoning_tokens': 30}}
            return httpx2.Response(200, json=raw)

        with tempfile.TemporaryDirectory() as temp, OpenAI(
                api_key='test-placeholder', base_url=PROVIDERS['qwen']['url'], max_retries=0,
                http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler),
                                              trust_env=False)) as client:
            with redirect_stdout(io.StringIO()) as terminal:
                directory = run_experiment(StubRenderer(), client, ['zhu', 'euro'], Path(temp) / 'raw',
                                           SETTINGS, dry_run=False)
            self.assertIn('reasoning=180', terminal.getvalue())
            record = read_json(directory / 'experiment.json')
            self.assertEqual(record['status'], 'completed')
            self.assertEqual(record['endpoint'], 'https://dashscope.aliyuncs.com/compatible-mode/v1/responses')
            self.assertEqual(record['historyMode'], 'previous_response_id')
            self.assertEqual(record['usage']['total_tokens'], 840)
            self.assertEqual(len(requests), 6)
            for index, trial in enumerate(record['trials']):
                run = directory / trial['run']
                for number, call in enumerate(trial['calls']):
                    body = requests[index * 3 + number]
                    logged = read_json(run / f'calls/round-{number}/request.json')
                    self.assertNotIn('service_tier', body)
                    self.assertTrue(body['store'])
                    self.assertEqual(body['reasoning'], {'effort': 'xhigh'})
                    self.assertEqual(body['max_output_tokens'], 65536)
                    self.assertTrue(body['text']['format']['json_schema']['strict'])
                    self.assertEqual('explanation' in output_schema(body)['properties'], number == 2)
                    instructions = '\n'.join(m['content'] for m in body['input']
                                             if m['role'] == 'developer')
                    self.assertEqual(FINAL_PROMPT.read_text() in instructions, number == 2)
                    if number:
                        self.assertEqual(body['previous_response_id'], trial['calls'][number-1]['responseId'])
                    else:
                        self.assertNotIn('previous_response_id', body)
                        self.assertEqual(body['input'][0]['content'], (run / 'inputs/prompt.txt').read_text() +
                            '\nAPI OUTPUT REQUIREMENT\nInclude both flipX and flipY in every item; use false when no flip is needed.\n')
                    images = [part for msg in body['input'] if isinstance(msg['content'], list)
                              for part in msg['content'] if part['type'] == 'input_image']
                    self.assertEqual(len(images), 3 if number == 0 else 1)
                    self.assertTrue(all(set(i) == {'type', 'image_url'} for i in images))
                    self.assertNotIn('data:image', json.dumps(logged))
                    self.assertNotIn('PRIVATE-MOCK-SENTINEL', (run / f'calls/round-{number}/model-output.txt').read_text())
                self.assertTrue((directory / trial['finalPng']).exists())
                self.assertTrue((directory / trial['explanationText']).exists())
            group = reserve_group(Path(temp) / 'gallery', 'qwen3.8-max', 'xhigh')
            register_experiment(group, directory)
            self.assertTrue(read_json(group / 'summary.json')['completePair'])

    def test_dry_run_uses_no_real_key_and_pins_beijing(self):
        with patch('openai_experiment.os.environ', {}):
            client, transport = create_client(True, 900, 'qwen')
            with client:
                self.assertEqual(str(client.base_url).rstrip('/'), PROVIDERS['qwen']['url'])
                self.assertEqual(client.api_key, 'dry-run-placeholder')
                self.assertEqual(transport.provider, 'qwen')
            with self.assertRaisesRegex(ValueError, 'DASHSCOPE_API_KEY'):
                create_client(False, 900, 'qwen')


if __name__ == '__main__':
    unittest.main()
