#!/usr/bin/env python3
"""Three-round FoodFace experiment using OpenAI Responses, or an offline HTTP mock."""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import uuid

from agent import (ROOT, PORTRAITS, BrowserRenderer, hashes, now, parse_json,
                   read_json, start_run, submit_response, write_json)

MODEL = 'gpt-6.1-sol'
API_URL = 'https://api.openai.com/v1'
FIXTURES = ROOT / 'examples/openai-dry-run'


def layout_schema(ids):
    # Strict Structured Outputs requires every property to be required.
    # Explicit false flips are compatible with the existing optional-flag protocol.
    fields = {
        'uid': {'type': 'string', 'minLength': 1, 'maxLength': 128},
        'id': {'type': 'string', 'enum': sorted(ids)},
        'x': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'y': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'size': {'type': 'number', 'minimum': .03, 'maximum': .9},
        'angle': {'type': 'number', 'minimum': -180, 'maximum': 180},
        'flipX': {'type': 'boolean'}, 'flipY': {'type': 'boolean'},
    }
    return {'type': 'object', 'additionalProperties': False, 'required': ['items'],
            'properties': {'items': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': fields, 'required': list(fields)}}}}


def build_request(run, number, previous_id, settings):
    """Return wire parameters and an equivalent log using local image references."""
    if number not in (0, 1, 2) or (number == 0) != (previous_id is None):
        raise ValueError('Invalid round or missing conversation predecessor.')
    manifest = read_json(run / 'inputs/manifest.json')
    request = {
        'model': settings['model'], 'store': True, 'service_tier': 'default',
        'reasoning': {'effort': settings['reasoning']},
        'max_output_tokens': settings['maxOutputTokens'],
        'text': {'format': {'type': 'json_schema', 'name': 'foodface_layout',
                            'strict': True,
                            'schema': layout_schema(a['id'] for a in manifest['foods'])}},
        'input': [],
    }
    if number == 0:
        # Keep the prompt in conversation history as a developer MESSAGE.
        # The top-level `instructions` field is not inherited with previous_response_id.
        prompt = (run / 'inputs/prompt.txt').read_text(encoding='utf-8')
        prompt += ('\nAPI OUTPUT REQUIREMENT\nInclude both flipX and flipY in every item; '
                   'use false when no flip is needed.\n')
        request['input'].append({'role': 'developer', 'content': prompt})
        text = 'Initial attempt (round 1 of 3). Return the complete layout JSON.'
        attachments = [('Original portrait', 'inputs/original.png'),
                       ('Empty-face portrait', 'inputs/empty.png'),
                       ('Food contact sheet with asset IDs and crop dimensions', 'inputs/foods.png')]
    else:
        request['previous_response_id'] = previous_id
        text = (run / f'round-{number - 1}/next-prompt.txt').read_text(encoding='utf-8')
        attachments = [('Latest rendered collage', f'round-{number - 1}/feedback.png')]
    content = [{'type': 'input_text', 'text': text}]
    logged_content = deepcopy(content)
    for label, relative in attachments:
        data = (run / relative).read_bytes()
        content.append({'type': 'input_text', 'text': label})
        logged_content.append({'type': 'input_text', 'text': label})
        content.append({'type': 'input_image', 'detail': settings['imageDetail'],
                        'image_url': 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')})
        logged_content.append({'type': 'input_image', 'detail': settings['imageDetail'],
                               'localFile': relative, 'bytes': len(data),
                               'sha256': hashlib.sha256(data).hexdigest()})
    request['input'].append({'role': 'user', 'content': content})
    logged = deepcopy(request)
    logged['input'][-1]['content'] = logged_content
    return request, logged


class DryResponses:
    """HTTP-level fixture transport: uses the real SDK, never opens an API connection."""
    def __init__(self):
        self.calls = []
        self.responses = {}

    def __call__(self, request):
        import httpx2
        if str(request.url) != API_URL + '/responses' or request.method != 'POST':
            raise ValueError('Dry run attempted an unexpected endpoint.')
        body = parse_json(request.content.decode('utf-8'))
        previous = body.get('previous_response_id')
        if previous is None:
            number = 0
        elif previous in self.responses:
            number = self.responses[previous] + 1
        else:
            raise ValueError('Dry run lost its conversation history.')
        if number > 2:
            raise ValueError('Dry run attempted a fourth call.')
        content = body['input'][-1]['content']
        images = [p for p in content if p['type'] == 'input_image']
        if len(images) != (3 if number == 0 else 1):
            raise ValueError('Incorrect number of observation images.')
        for part in images:
            raw = base64.b64decode(part['image_url'].split(',', 1)[1], validate=True)
            if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Observation is not a PNG.')
        if number > 0 and any(m['role'] == 'developer' for m in body['input']):
            raise ValueError('Adjustment unnecessarily repeats the initial prompt.')
        # Store only small diagnostics, not image payloads or Authorization headers.
        self.calls.append({'round': number, 'previousResponseId': previous, 'imageCount': len(images)})
        response_id = 'dry_resp_' + uuid.uuid4().hex
        self.responses[response_id] = number
        output = (FIXTURES / f'round-{number}.json').read_text(encoding='utf-8')
        return httpx2.Response(200, headers={'x-request-id': 'dry_req_' + uuid.uuid4().hex}, json={
            'id': response_id, 'object': 'response', 'created_at': 0, 'status': 'completed',
            'model': body['model'], 'error': None, 'incomplete_details': None,
            'output': [{'id': 'dry_msg_' + uuid.uuid4().hex, 'type': 'message',
                        'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': output, 'annotations': []}]}],
            # A dry run must not pretend to measure tokens, prices or model performance.
            'usage': None, 'metadata': {'simulated': 'true'},
        })


def create_client(dry_run, timeout):
    from openai import OpenAI, DefaultHttpxClient
    if dry_run:
        import httpx2
        transport = DryResponses()
        return OpenAI(api_key='dry-run-placeholder', base_url=API_URL, max_retries=0,
                      timeout=timeout,
                      http_client=DefaultHttpxClient(transport=httpx2.MockTransport(transport),
                                                    trust_env=False)), transport
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('Set OPENAI_API_KEY in your terminal, or use --dry-run. No key is saved.')
    # Pin the official endpoint even if another project's OPENAI_BASE_URL is set.
    return OpenAI(api_key=key, base_url=API_URL, max_retries=0, timeout=timeout), None


def response_text(response):
    if response.status != 'completed':
        raise ValueError('Response did not complete; inspect api-response.json for details. No retry was made.')
    for item in response.output:
        for part in getattr(item, 'content', []) or []:
            if getattr(part, 'type', None) == 'refusal':
                raise ValueError('Model refused the request; inspect api-response.json. No retry was made.')
    if not isinstance(response.id, str) or not response.id:
        raise ValueError('Response has no conversation ID.')
    if not response.output_text.strip():
        raise ValueError('Response contains no layout text.')
    return response.output_text


def usage_totals(calls):
    measured = [call['usage'] for call in calls if call.get('usage') is not None]
    if not measured:
        return None
    def total(values):
        # Missing API fields mean unknown, not zero usage.
        return sum(values) if all(type(v) is int for v in values) else None

    totals = {key: total([u.get(key) for u in measured])
              for key in ('input_tokens', 'output_tokens', 'total_tokens')}
    for group, key in [('input_tokens_details', 'cached_tokens'), ('output_tokens_details', 'reasoning_tokens')]:
        totals[key] = total([(u.get(group) or {}).get(key) for u in measured])
    return totals


def print_usage(label, calls):
    totals = usage_totals(calls)
    reported = sum(call.get('usage') is not None for call in calls)
    def value(key):
        count = (totals or {}).get(key)
        return f'{count:,}' if count is not None else 'N/A'
    print(f'  {label} tokens: input={value("input_tokens")} | '
          f'output={value("output_tokens")} | reasoning={value("reasoning_tokens")} | '
          f'cached input={value("cached_tokens")} | total={value("total_tokens")} '
          f'(usage reported for {reported}/{len(calls)} requests)', flush=True)


def run_experiment(renderer, client, portraits, output, settings, dry_run=False):
    import openai
    mode = 'dry-run' if dry_run else 'live'
    directory = output / f'Experiment-{mode}-{uuid.uuid4()}'
    directory.mkdir(parents=True)
    record = {'experimentId': directory.name, 'createdAt': now(), 'status': 'running',
              'mode': mode, 'simulated': dry_run, 'settings': settings,
              'endpoint': API_URL + '/responses', 'sdkVersion': openai.__version__,
              'historyMode': 'previous_response_id', 'maxCallsPerPortrait': 3,
              'automaticRetries': 0, 'trials': []}

    def save():
        for trial in record['trials']:
            trial['usage'] = usage_totals(trial['calls'])
        calls = [call for trial in record['trials'] for call in trial['calls']]
        record['usage'] = usage_totals(calls)
        write_json(directory / 'experiment.json', record)
        # Compact companion file for checking tokens without opening all API responses.
        write_json(directory / 'token-usage.json', {
            'experimentId': record['experimentId'], 'status': record['status'],
            'simulated': dry_run, 'updatedAt': now(),
            'note': 'Reasoning tokens are included in output tokens. Total is input + output. '
                    'Totals cover reported usage only; null means unavailable, not zero.',
            'requests': len(calls),
            'requestsWithUsage': sum(call.get('usage') is not None for call in calls),
            'totals': record['usage'],
            'portraits': [{'portraitId': trial['portraitId'], 'totals': trial['usage'],
                          'rounds': [{'round': call['round'] + 1, 'status': call['status'],
                                      'tokens': usage_totals([call])} for call in trial['calls']]}
                         for trial in record['trials']],
        })

    save()
    print(f'Experiment: {directory}', flush=True)
    print('Token accounting: reasoning is included in output; total = input + output. '
          'N/A means no API measurement.', flush=True)
    try:
        for portrait in portraits:
            run = start_run(renderer, portrait, directory, settings['maxEdge'])
            metadata = read_json(run / 'run.json')
            metadata.update(responseSource='openai-dry-run' if dry_run else 'openai-responses',
                            model=settings['model'], modelParameters=settings,
                            simulated=dry_run, sdkVersion=openai.__version__)
            write_json(run / 'run.json', metadata)
            trial = {'portraitId': portrait, 'run': run.name, 'status': 'running', 'calls': []}
            record['trials'].append(trial)
            save()
            previous_id = None
            for number in range(3):
                if metadata['fileHashes'] != hashes():
                    raise ValueError('Sources changed before the API call; start a new experiment.')
                folder = run / 'calls' / f'round-{number}'
                folder.mkdir(parents=True)
                params, logged = build_request(run, number, previous_id, settings)
                write_json(folder / 'request.json', logged)
                call = {'round': number, 'startedAt': now(), 'status': 'requesting',
                        'request': str((folder / 'request.json').relative_to(directory)),
                        'previousResponseId': previous_id}
                trial['calls'].append(call)
                save()
                print(f'  {portrait}: round {number + 1}/3 ({mode})', flush=True)
                response = client.responses.create(**params)
                raw = response.model_dump(mode='json')
                write_json(folder / 'api-response.json', raw)
                call.update(receivedAt=now(), responseId=response.id,
                            requestId=getattr(response, '_request_id', None),
                            actualModel=None if dry_run else response.model,
                            usage=raw.get('usage'), status='received')
                save()
                print_usage(f'{portrait} round {number + 1}/3', [call])
                text = response_text(response)
                source = folder / 'layout.json'
                source.write_text(text, encoding='utf-8')
                # Local validation also enforces identity rules across rounds.
                accepted = submit_response(renderer, run, source)
                call.update(status='rendered', completedAt=now(),
                            feedback=str((accepted / 'feedback.png').relative_to(directory)))
                previous_id = response.id
                save()
            feedback = read_json(run / 'round-2/feedback.json')
            trial.update(status='completed', finalFeedback=f'{run.name}/round-2/feedback.png',
                         finalPng=f"{run.name}/round-2/{feedback['snapshot']['png']}",
                         finalScene=f"{run.name}/round-2/{feedback['snapshot']['json']}",
                         usage=usage_totals(trial['calls']))
            save()
            print_usage(f'{portrait} subtotal', trial['calls'])
        record.update(status='completed', completedAt=now(),
                      usage=usage_totals([c for t in record['trials'] for c in t['calls']]))
        save()
        print_usage('Experiment total', [c for t in record['trials'] for c in t['calls']])
    except (Exception, KeyboardInterrupt) as error:
        # Do not persist raw SDK exception strings/headers, which may contain credentials.
        failure = {'type': type(error).__name__, 'at': now()}
        if type(error) is ValueError:
            failure['message'] = str(error)
        status = getattr(error, 'status_code', None)
        if isinstance(status, int):
            failure['httpStatus'] = status
        record.update(status='failed', error=failure)
        if record['trials'] and record['trials'][-1]['status'] == 'running':
            trial = record['trials'][-1]
            trial['status'] = 'failed'
            if trial['calls'] and trial['calls'][-1]['status'] != 'rendered':
                trial['calls'][-1]['status'] = 'failed'
            trial['usage'] = usage_totals(trial['calls'])
        record['usage'] = usage_totals([c for t in record['trials'] for c in t['calls']])
        save()
        print_usage('Experiment stopped; reported subtotal',
                    [c for t in record['trials'] for c in t['calls']])
        raise
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Use fabricated responses; no API connection or key')
    parser.add_argument('--portrait', choices=['all', *PORTRAITS], default='all')
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--reasoning', choices=['low', 'medium', 'high', 'xhigh', 'max'], default='medium')
    parser.add_argument('--max-output-tokens', type=int, default=8192, help='Per-call limit including reasoning tokens')
    parser.add_argument('--image-detail', choices=['low', 'high', 'auto'], default='high')
    parser.add_argument('--max-edge', type=int, default=1024)
    parser.add_argument('--timeout', type=float, default=180, help='Per-request timeout in seconds; retries disabled')
    parser.add_argument('--output', type=Path, default=ROOT / 'result-data/openai-experiments')
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    if args.max_output_tokens < 1 or not 256 <= args.max_edge <= 2048 or args.timeout <= 0:
        parser.error('Use positive output tokens/timeout and max-edge in [256, 2048].')
    settings = {'model': args.model, 'reasoning': args.reasoning,
                'maxOutputTokens': args.max_output_tokens, 'imageDetail': args.image_detail,
                'maxEdge': args.max_edge, 'timeoutSeconds': args.timeout}
    portraits = list(PORTRAITS) if args.portrait == 'all' else [args.portrait]
    try:
        client, _transport = create_client(args.dry_run, args.timeout)
        with client, BrowserRenderer(args.headed) as renderer:
            directory = run_experiment(renderer, client, portraits, args.output.resolve(), settings, args.dry_run)
        print(f'Completed: {directory / "experiment.json"}')
        print(f'Token usage: {directory / "token-usage.json"}')
        record = read_json(directory / 'experiment.json')
        for trial in record['trials']:
            print(f'  {trial["portraitId"]} final PNG: {directory / trial["finalPng"]}')
        if args.dry_run:
            print('SIMULATED OUTPUTS: no API calls, token measurements or model-performance claims.')
    except ImportError:
        parser.exit(1, 'Install scripts/requirements-openai.txt and Chromium; see docs/openai-experiment.md.\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Interrupted. Inspect experiment.json before starting another paid run.\n')
    except Exception as error:
        message = str(error) if type(error) is ValueError else type(error).__name__
        parser.exit(1, f'Experiment stopped: {message}. Inspect saved records; no automatic retry.\n')


if __name__ == '__main__':
    main()
