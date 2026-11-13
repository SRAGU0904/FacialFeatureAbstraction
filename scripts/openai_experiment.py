#!/usr/bin/env python3
"""Three-round FoodFace experiment using OpenAI/DeepSeek/Qwen Responses, or an offline mock."""
import argparse
import base64
from copy import deepcopy
import hashlib
from importlib import metadata as packages
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import traceback
import uuid

from agent import (ROOT, PORTRAITS, BrowserRenderer, hashes, now, parse_json,
                   read_json, start_run, submit_response, write_json)

MODEL = 'gpt-6.1-sol'
API_URL = 'https://api.openai.com/v1'
PROVIDERS = {
    'openai': {'url': API_URL, 'key': 'OPENAI_API_KEY', 'model': MODEL,
               'reasoning': 'medium', 'maxOutputTokens': 8192},
    'deepseek': {'url': 'https://api.deepseek.com', 'key': 'DEEPSEEK_API_KEY',
                 'model': 'deepseek-flash', 'reasoning': 'high', 'maxOutputTokens': 32768},
    'qwen': {'url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
             'key': 'DASHSCOPE_API_KEY', 'model': 'qwen3.8-max',
             'reasoning': 'xhigh', 'maxOutputTokens': 65536},
}
FIXTURES = ROOT / 'examples/openai-dry-run'
FINAL_PROMPT = ROOT / 'prompts/agent-final-explanation.txt'
PORTRAIT_NAMES = {'zhu': 'Zhu-Yuanzhang', 'euro': 'Rudolf-II'}


def layout_schema(ids, explain=False):
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
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['items'],
            'properties': {'items': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': fields, 'required': list(fields)}}}}
    if explain:
        schema['required'].append('explanation')
        schema['properties']['explanation'] = {
            'type': 'object', 'additionalProperties': False, 'required': ['overall', 'choices'],
            'properties': {
                'overall': {'type': 'string', 'minLength': 1},
                'choices': {'type': 'array', 'items': {
                    'type': 'object', 'additionalProperties': False,
                    'required': ['uids', 'feature', 'reason'],
                    'properties': {'uids': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}},
                                   'feature': {'type': 'string', 'minLength': 1},
                                   'reason': {'type': 'string', 'minLength': 1}}}},
            },
        }
    return schema


def split_output(text, explain):
    data = parse_json(text)
    expected = {'items', 'explanation'} if explain else {'items'}
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError('Unexpected response fields for this round.')
    if not isinstance(data['items'], list):
        raise ValueError('Expected a complete items array.')
    explanation = data.get('explanation')
    if explain:
        if not isinstance(explanation, dict) or set(explanation) != {'overall', 'choices'}:
            raise ValueError('Explanation must contain only overall and choices.')
        if not isinstance(explanation['overall'], str) or not explanation['overall'].strip():
            raise ValueError('Explanation overall must be nonempty text.')
        if not isinstance(explanation['choices'], list):
            raise ValueError('Explanation choices must be an array.')
        uids = {i.get('uid') for i in data['items']
                if isinstance(i, dict) and isinstance(i.get('uid'), str)}
        for choice in explanation['choices']:
            if not isinstance(choice, dict) or set(choice) != {'uids', 'feature', 'reason'}:
                raise ValueError('Each food choice needs uids, feature and reason.')
            refs = choice['uids']
            if (not isinstance(refs, list) or not refs
                    or any(not isinstance(uid, str) or uid not in uids for uid in refs)):
                raise ValueError('Explanation references an instance absent from the final layout.')
            if any(not isinstance(choice[k], str) or not choice[k].strip() for k in ('feature', 'reason')):
                raise ValueError('Food choice descriptions must be nonempty text.')
    return {'items': data['items']}, explanation


def normalize_sizes(layout):
    """Apply the authorized DeepSeek minimum-size rule, retaining an audit trail."""
    normalized = deepcopy(layout)
    changes = []
    for item in normalized['items']:
        value = item.get('size') if isinstance(item, dict) else None
        if type(value) in (int, float) and math.isfinite(value) and value < .03:
            changes.append({'uid': item.get('uid'), 'field': 'size', 'before': value, 'after': .03})
            item['size'] = .03
    return normalized, changes


def build_request(run, number, previous_id, settings):
    """Return wire parameters and an equivalent log using local image references."""
    request, logged = build_round_request(run, number, previous_id, settings)
    if settings.get('provider') == 'qwen':
        # Bailian Responses uses the Chat-style nested json_schema container.
        # It supports stored history and developer messages, but not service_tier
        # or OpenAI's per-image detail option. Image bytes are unchanged.
        for body in (request, logged):
            body.pop('service_tier')
            fmt = body['text']['format']
            body['text']['format'] = {'type': 'json_schema', 'json_schema': {
                key: fmt[key] for key in ('name', 'schema', 'strict')}}
            for message in body['input']:
                if isinstance(message['content'], list):
                    for part in message['content']:
                        if part['type'] == 'input_image':
                            part.pop('detail', None)
        return request, logged
    if settings.get('provider', 'openai') == 'openai':
        return request, logged
    # DeepSeek is stateless and treats developer messages as user messages.
    # Replay observations + final assistant JSON, with the same prompt as system.
    # Never replay private reasoning or announce the final explanation early.
    history, logged_history = [], []
    for earlier in range(number):
        delta, delta_log = build_round_request(run, earlier, None if earlier == 0 else 'local-history', settings)
        history.extend(delta['input'])
        logged_history.extend(delta_log['input'])
        answer = (run / f'calls/round-{earlier}/model-output.txt').read_text(encoding='utf-8')
        if (run / f'calls/round-{earlier}/normalization.json').exists():
            # Replay the actual rendered layout when deterministic bounds were applied.
            answer = (run / f'round-{earlier}/response.txt').read_text(encoding='utf-8')
        history.append({'role': 'assistant', 'content': answer})
        logged_history.append({'role': 'assistant', 'content': answer})
    for body, messages in ((request, history), (logged, logged_history)):
        messages.extend(body['input'])
        instructions = '\n\n'.join(m['content'] for m in messages if m['role'] == 'developer')
        body['input'] = [{'role': 'system', 'content': instructions}] + [
            m for m in messages if m['role'] != 'developer']
        for unsupported in ('previous_response_id', 'store', 'service_tier'):
            body.pop(unsupported, None)
    return request, logged


def build_round_request(run, number, previous_id, settings):
    """One round's new observations; provider history handling lives above."""
    if number not in (0, 1, 2) or (number == 0) != (previous_id is None):
        raise ValueError('Invalid round or missing conversation predecessor.')
    manifest = read_json(run / 'inputs/manifest.json')
    explain = number == 2 and settings.get('finalExplanation', True)
    request = {
        'model': settings['model'], 'store': True, 'service_tier': 'default',
        'reasoning': {'effort': settings['reasoning']},
        'max_output_tokens': settings['maxOutputTokens'],
        'text': {'format': {'type': 'json_schema', 'name': 'foodface_layout',
                            'strict': True,
                            'schema': layout_schema((a['id'] for a in manifest['foods']), explain)}},
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
    if explain:
        # Disclosed only now, at the same instruction priority as the original
        # developer message whose layout-only format this replaces.
        request['input'].append({'role': 'developer', 'content': FINAL_PROMPT.read_text(encoding='utf-8')})
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


def output_schema(request):
    fmt = request['text']['format']
    return fmt.get('json_schema', fmt)['schema']


class DryResponses:
    """HTTP-level fixture transport: uses the real SDK, never opens an API connection."""
    def __init__(self, provider='openai'):
        self.provider = provider
        self.calls = []
        self.responses = {}
        self.branch_layouts = {}

    def seed_branch(self, response_id, layout):
        self.responses[response_id] = 1
        self.branch_layouts[response_id] = layout

    def __call__(self, request):
        import httpx2
        if str(request.url) != PROVIDERS[self.provider]['url'] + '/responses' or request.method != 'POST':
            raise ValueError('Dry run attempted an unexpected endpoint.')
        body = parse_json(request.content.decode('utf-8'))
        previous = body.get('previous_response_id')
        if self.provider == 'deepseek':
            if any(k in body for k in ('previous_response_id', 'store', 'service_tier')):
                raise ValueError('Unsupported DeepSeek history parameters.')
            number = sum(m['role'] == 'assistant' for m in body['input'])
            if ([m['role'] for m in body['input']]
                    != ['system', 'user'] + ['assistant', 'user'] * number):
                raise ValueError('DeepSeek requires complete local conversation history.')
        elif previous is None:
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
        if self.provider == 'qwen':
            if 'service_tier' in body or set(body['text']['format']) != {'type', 'json_schema'}:
                raise ValueError('Incorrect Bailian Responses parameters.')
            if any('detail' in part for part in images):
                raise ValueError('Bailian image input does not document detail.')
        explain = 'explanation' in output_schema(body)['properties']
        if explain and number != 2:
            raise ValueError('Explanation was disclosed before the final round.')
        if number == 1 and any(m['role'] == 'developer' for m in body['input']):
            raise ValueError('Adjustment unnecessarily repeats the initial prompt.')
        # Store only small diagnostics, not image payloads or Authorization headers.
        self.calls.append({'round': number, 'previousResponseId': previous, 'imageCount': len(images)})
        response_id = 'dry_resp_' + uuid.uuid4().hex
        self.responses[response_id] = number
        output = (FIXTURES / f'round-{number}.json').read_text(encoding='utf-8')
        if previous in self.branch_layouts:
            output = json.dumps(self.branch_layouts[previous])
        if explain:
            layout = parse_json(output)
            layout['explanation'] = {
                'overall': 'Simulated artwork description for an offline pipeline test.',
                'choices': [{'uids': [layout['items'][0]['uid']], 'feature': 'Face shape',
                             'reason': 'Simulated association between a food contour and the face.'}]
                if layout['items'] else [],
            }
            output = json.dumps(layout)
        return httpx2.Response(200, headers={'x-request-id': 'dry_req_' + uuid.uuid4().hex}, json={
            'id': response_id, 'object': 'response', 'created_at': 0, 'status': 'completed',
            'model': body['model'], 'error': None, 'incomplete_details': None,
            'output': [{'id': 'dry_msg_' + uuid.uuid4().hex, 'type': 'message',
                        'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': output, 'annotations': []}]}],
            # A dry run must not pretend to measure tokens, prices or model performance.
            'usage': None, 'metadata': {'simulated': 'true'},
        })


def create_client(dry_run, timeout, provider='openai'):
    from openai import OpenAI, DefaultHttpxClient
    config = PROVIDERS[provider]
    # Conda can supply an older brotlicffi that httpx2 detects and advertises,
    # but cannot call with output_buffer_limit. gzip uses Python's zlib and
    # avoids that optional decoder without changing model request parameters.
    headers = {'Accept-Encoding': 'gzip'}
    if dry_run:
        import httpx2
        transport = DryResponses(provider)
        return OpenAI(api_key='dry-run-placeholder', base_url=config['url'], max_retries=0,
                      timeout=timeout, default_headers=headers,
                      http_client=DefaultHttpxClient(transport=httpx2.MockTransport(transport),
                                                    trust_env=False)), transport
    key = os.environ.get(config['key'], '').strip()
    if not key:
        raise ValueError(f"Set {config['key']} in your terminal, or use --dry-run. No key is saved.")
    # Pin the official endpoint even if another project's OPENAI_BASE_URL is set.
    return OpenAI(api_key=key, base_url=config['url'], max_retries=0, timeout=timeout,
                  default_headers=headers), None


def response_text(response):
    if not isinstance(response, dict):
        raise ValueError('API response must be a JSON object; inspect api-response.json.')
    if response.get('status') != 'completed':
        if (response.get('incomplete_details') or {}).get('reason') == 'max_output_tokens':
            raise ValueError('Response reached max_output_tokens (reasoning and JSON share this limit). '
                             'No complete layout was accepted. Consider a larger --max-output-tokens '
                             'for a new run; inspect api-response.json. No retry was made.')
        raise ValueError('Response did not complete; inspect api-response.json for details. No retry was made.')
    if not isinstance(response.get('id'), str) or not response['id']:
        raise ValueError('Response has no conversation ID.')
    output = response.get('output')
    if not isinstance(output, list):
        raise ValueError('API response output must be an array; inspect api-response.json.')
    chunks = []
    for item in output:
        if not isinstance(item, dict) or item.get('type') != 'message':
            continue
        content = item.get('content')
        if not isinstance(content, list):
            raise ValueError('API message content must be an array; inspect api-response.json.')
        for part in content:
            if not isinstance(part, dict):
                raise ValueError('API message content must contain objects; inspect api-response.json.')
            if part.get('type') == 'refusal':
                raise ValueError('Model refused the request; inspect api-response.json. No retry was made.')
            if part.get('type') == 'output_text':
                if not isinstance(part.get('text'), str):
                    raise ValueError('API output text must be a string; inspect api-response.json.')
                chunks.append(part['text'])
    text = ''.join(chunks)
    if not text.strip():
        raise ValueError('Response contains no layout text.')
    return text


def error_details(error, stage):
    """Record useful stack locations without headers, local variables or credentials."""
    def redact(value):
        for key, secret in os.environ.items():
            if len(secret) >= 6 and any(s in key.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'sk-[A-Za-z0-9_-]+', '[REDACTED]', value)
        value = re.sub(r'(?i)Bearer\s+[^\s\"\'<>]+', 'Bearer [REDACTED]', value)
        value = re.sub(r'data:[^,\s]+;base64,[A-Za-z0-9+/=]+', '[IMAGE DATA]', value)
        return value[:1000]

    failure = {'type': type(error).__name__, 'at': now(), 'stage': stage,
               'frames': [{'file': f.filename, 'line': f.lineno, 'function': f.name}
                          for f in traceback.extract_tb(error.__traceback__)]}
    # Arbitrary HTTP/SDK exception strings can contain raw requests or headers.
    # Built-in programming/validation errors are useful after redaction.
    if type(error) in (TypeError, ValueError, AttributeError, KeyError, AssertionError):
        failure['message'] = redact(str(error))
    status = getattr(error, 'status_code', None)
    if isinstance(status, int):
        failure['httpStatus'] = status
    causes, seen = [], {id(error)}
    cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    while cause is not None and id(cause) not in seen and len(causes) < 4:
        seen.add(id(cause))
        detail = {'type': type(cause).__name__,
                  'frames': [{'file': f.filename, 'line': f.lineno, 'function': f.name}
                             for f in traceback.extract_tb(cause.__traceback__)]}
        if type(cause) in (TypeError, ValueError, AttributeError, KeyError, AssertionError):
            detail['message'] = redact(str(cause))
        causes.append(detail)
        cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
    if causes:
        failure['causes'] = causes
    return failure


def runtime_info():
    versions = {}
    for name in ('openai', 'pydantic', 'pydantic-core', 'httpx2', 'brotli', 'brotlicffi', 'playwright'):
        try:
            versions[name] = packages.version(name)
        except packages.PackageNotFoundError:
            versions[name] = None
    return {'pythonExecutable': sys.executable, 'pythonVersion': sys.version, 'packages': versions}


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


def branch_source(source, repair=False):
    """Read the saved second round, never the original third round as history."""
    source = source.resolve()
    metadata = read_json(source / 'run.json')
    experiment = read_json(source.parent / 'experiment.json')
    trial = next((t for t in experiment['trials'] if t['run'] == source.name), None)
    if trial is None or metadata.get('simulated') or experiment.get('simulated'):
        raise ValueError('Select a portrait directory from a real experiment.')
    calls = {c['round']: c for c in trial['calls']}
    if repair and (experiment['settings'].get('provider') != 'deepseek'
                   or (source / 'round-1').exists() or set(calls) != {0, 1}):
        raise ValueError('Repair needs a DeepSeek run with a rendered first round and unrendered second round.')
    if any(n not in calls or (calls[n]['status'] != 'rendered' and not (repair and n == 1))
           for n in (0, 1)):
        raise ValueError('The source must contain two completed rounds.')
    for n in (0, 1):
        response = read_json(source / f'calls/round-{n}/api-response.json')
        if response.get('status') != 'completed' or response.get('id') != calls[n]['responseId']:
            raise ValueError('Source response IDs/status do not match the saved trial.')
        if 'explanation' in output_schema(read_json(source / f'calls/round-{n}/request.json'))['properties']:
            raise ValueError('Source rounds already requested explanations.')
        if repair and n == 1:
            layout, _ = split_output(response_text(response), False)
            if layout != read_json(source / 'calls/round-1/model-output.txt'):
                raise ValueError('Saved model output differs from the API response.')
            if not normalize_sizes(layout)[1]:
                raise ValueError('The saved second round has no size below the minimum to repair.')
            continue
        layout = read_json(source / f'round-{n}/response.txt')
        if layout['items'] != read_json(source / f'round-{n}/feedback.json')['scene']['items']:
            raise ValueError('Source layout and saved scene disagree.')
    if calls[1]['previousResponseId'] != calls[0]['responseId']:
        raise ValueError('Source history is not a contiguous response chain.')
    settings = deepcopy(experiment['settings'])
    settings['finalExplanation'] = True
    return metadata, trial, settings


def prepare_branch(renderer, source, directory, settings, repair=False):
    metadata, trial, _ = branch_source(source, repair=repair)
    current = hashes()
    # Runner/prompt/UI changes are allowed for a new branch; changes affecting
    # rendering are not. Replay below also checks the actual saved pixels.
    critical = lambda p: (p.endswith('.png') or p in {
        'assets/js/renderer.js', 'assets/js/agent-render.js',
        'assets/js/portrait-paths.js', 'assets/js/catalog.js', 'agent-render.html'})
    old = {p: h for p, h in metadata['fileHashes'].items() if critical(p)}
    new = {p: h for p, h in current.items() if critical(p)}
    if old != new or metadata['browserVersion'] != renderer.browser.version:
        raise ValueError('Source rendering assets/code or browser changed; exact continuation is not supported.')
    if (source / '.lock').exists():
        raise ValueError('Source run is locked; do not fork an active writer.')
    source_files = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in source.rglob('*') if p.is_file() and p.name != '.DS_Store'}
    run_id = str(uuid.uuid4())
    run = directory / f'Agent-{metadata["portraitId"]}-{run_id}'
    run.mkdir()
    shutil.copytree(source / 'inputs', run / 'inputs')
    write_json(run / 'run.json', {**metadata, 'fileHashes': current})
    for n in (0, 1):
        shutil.copytree(source / f'calls/round-{n}', run / f'calls/round-{n}')
        if repair and n == 1:
            folder = run / 'calls/round-1'
            layout, _ = split_output(response_text(read_json(folder / 'api-response.json')), False)
            layout, changes = normalize_sizes(layout)
            write_json(folder / 'layout.json', layout)
            write_json(folder / 'normalization.json', {'policy': 'minimum-size-0.03', 'changes': changes})
            submit_response(renderer, run, folder / 'layout.json')
            continue
        shutil.copytree(source / f'round-{n}', run / f'round-{n}')
        feedback = read_json(run / f'round-{n}/feedback.json')
        replay = renderer.render(feedback['scene'], settings['maxEdge'])
        for image_type, relative in [('full', feedback['snapshot']['png']), ('feedback', 'feedback.png')]:
            actual = base64.b64decode(replay[image_type]['png'], validate=True)
            if actual != (run / f'round-{n}' / relative).read_bytes():
                raise ValueError('Replaying the source scene changed pixels; branch stopped before any API call.')
    if (source / 'round-2').is_dir():
        shutil.copytree(source / 'round-2', run / 'baseline-round-3')
    shutil.copy2(source / 'run.json', run / 'source-run.json')
    shutil.copy2(source.parent / 'experiment.json', run / 'source-experiment.json')
    if any(not (source / p).is_file() or hashlib.sha256((source / p).read_bytes()).hexdigest() != h
           for p, h in source_files.items()):
        raise ValueError('Source changed while preparing the branch.')
    inherited = sorted((deepcopy(c) for c in trial['calls'] if c['round'] in (0, 1)),
                       key=lambda c: c['round'])
    if repair:
        inherited[1].update(status='rendered', locallyRepairedAt=now(),
                            normalization='calls/round-1/normalization.json')
    fork = {'sourceRun': str(source), 'sourceResponseId': inherited[-1]['responseId'],
            'sourceFiles': source_files, 'sourceFileHashes': metadata['fileHashes'],
            'inheritedRounds': [0, 1], 'renderReplayMatched': True,
            'replayedRounds': [0] if repair else [0, 1], 'localSizeRepair': repair}
    metadata.update(runId=run_id, createdAt=now(), fileHashes=current, fork=fork)
    write_json(run / 'run.json', metadata)
    return run, inherited, fork


def repair_second_round(renderer, source, output):
    """Create a preserved, locally repaired checkpoint without any API client."""
    metadata, _, settings = branch_source(source, repair=True)
    settings['sizePolicy'] = 'minimum-size-0.03'
    portrait = metadata['portraitId']
    directory, number = numbered_experiment(output, [portrait], 'repaired')
    run, inherited, fork = prepare_branch(renderer, source, directory, settings, repair=True)
    target = directory / f'{PORTRAIT_NAMES[portrait]}-{number:03d}'
    run.rename(target)
    repaired_metadata = read_json(target / 'run.json')
    repaired_metadata.update(modelParameters=settings, localSizeRepair=True)
    write_json(target / 'run.json', repaired_metadata)
    for call in inherited:
        n = call['round']
        call.update(request=f'{target.name}/calls/round-{n}/request.json',
                    feedback=f'{target.name}/round-{n}/feedback.png')
    record = {'experimentId': directory.name, 'createdAt': now(), 'status': 'ready-for-round-3',
              'mode': 'local-repair', 'simulated': False, 'provider': 'deepseek',
              'settings': settings, 'historyMode': 'full_messages', 'apiCallsMade': 0,
              'automaticRetries': 0, 'fork': fork,
              'trials': [{'portraitId': portrait, 'run': target.name, 'status': 'ready-for-round-3',
                          'calls': inherited, 'usage': usage_totals(inherited)}],
              'usage': usage_totals(inherited),
              'usageNote': 'All usage is inherited from the source. Local repair makes zero API calls.'}
    write_json(directory / 'experiment.json', record)
    write_json(directory / 'token-usage.json', {'requests': 0, 'requestsWithUsage': 0,
               'totals': None, 'inheritedTotals': record['usage'], 'note': record['usageNote']})
    return target


def compare_branch(run):
    if not (run / 'baseline-round-3/feedback.json').exists():
        return None
    before = read_json(run / 'baseline-round-3/feedback.json')['scene']['items']
    after = read_json(run / 'round-2/feedback.json')['scene']['items']
    a, b = ({i['uid']: i for i in items} for items in (before, after))
    comparison = {'comparison': 'Original third round vs branched third round',
                  'originalHasExplanation': (run / 'baseline-round-3/explanation.json').exists(),
                  'branchHasExplanation': (run / 'round-2/explanation.json').exists(),
                  'sameSecondRound': True, 'identicalLayout': before == after,
                  'addedUids': sorted(b.keys() - a.keys()), 'removedUids': sorted(a.keys() - b.keys()),
                  'changedItems': {uid: {'before': a[uid], 'after': b[uid]}
                                   for uid in a.keys() & b.keys() if a[uid] != b[uid]},
                  'originalOrder': [i['uid'] for i in before], 'branchOrder': [i['uid'] for i in after],
                  'note': 'One comparison cannot separate the explanation instruction effect from sampling variability.'}
    write_json(run / 'comparison.json', comparison)
    return str(Path(run.name) / 'comparison.json')


def numbered_experiment(output, portraits, mode, branch=False):
    """Reserve a readable batch directory without overwriting prior attempts."""
    output.mkdir(parents=True, exist_ok=True)
    names = '_'.join(PORTRAIT_NAMES[p] for p in portraits)
    prefix = f'Experiment-{mode}{"-branch" if branch else ""}-{names}-'
    pattern = re.compile(re.escape(prefix) + r'(\d+)$')
    numbers = [int(match.group(1)) for p in output.iterdir()
               if (match := pattern.fullmatch(p.name))]
    number = max(numbers, default=0) + 1
    while True:
        directory = output / f'{prefix}{number:03d}'
        try:
            directory.mkdir()
            return directory, number
        except FileExistsError:
            number += 1


def export_final(run, feedback):
    """Put readable final files beside the detailed per-round records."""
    stem = run.name
    shutil.copyfile(run / 'round-2' / feedback['snapshot']['png'], run / f'{stem}.png')
    scene = read_json(run / 'round-2' / feedback['snapshot']['json'])
    scene['image']['file'] = f'{stem}.png'
    write_json(run / f'{stem}.json', scene)
    paths = {'finalPng': f'{stem}/{stem}.png', 'finalScene': f'{stem}/{stem}.json'}
    if (run / 'round-2/explanation.json').exists():
        for extension in ('json', 'txt'):
            shutil.copyfile(run / f'round-2/explanation.{extension}',
                            run / f'{stem}-explanation.{extension}')
        paths['explanation'] = f'{stem}/{stem}-explanation.json'
        paths['explanationText'] = f'{stem}/{stem}-explanation.txt'
    return paths


def run_experiment(renderer, client, portraits, output, settings, dry_run=False, source=None):
    import openai
    portraits = list(portraits)
    mode = 'dry-run' if dry_run else 'live'
    provider = settings.get('provider', 'openai')
    directory, number_in_series = numbered_experiment(output, portraits, mode, bool(source))
    record = {'experimentId': directory.name, 'createdAt': now(), 'status': 'running',
              'mode': mode, 'simulated': dry_run, 'settings': settings,
              'provider': provider, 'endpoint': PROVIDERS[provider]['url'] + '/responses',
              'sdkVersion': openai.__version__,
              'runtime': runtime_info(),
              'historyMode': 'full_messages' if provider == 'deepseek' else 'previous_response_id',
              'maxCallsPerPortrait': 1 if source else 3,
              'finalExplanation': settings.get('finalExplanation', True),
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
    stage = 'prepare-rendering'
    try:
        for portrait in portraits:
            if source:
                run, inherited, fork = prepare_branch(renderer, source, directory, settings)
            else:
                run = start_run(renderer, portrait, directory, settings['maxEdge'])
            readable_run = directory / f'{PORTRAIT_NAMES[portrait]}-{number_in_series:03d}'
            run.rename(readable_run)
            run = readable_run
            metadata = read_json(run / 'run.json')
            metadata.update(responseSource=f'{provider}-dry-run' if dry_run else f'{provider}-responses',
                            model=settings['model'], modelParameters=settings,
                            simulated=dry_run, sdkVersion=openai.__version__)
            write_json(run / 'run.json', metadata)
            trial = {'portraitId': portrait, 'run': run.name, 'status': 'running', 'calls': []}
            if source:
                trial.update(fork=fork, inheritedCalls=inherited)
            record['trials'].append(trial)
            save()
            previous_id = fork['sourceResponseId'] if source else None
            for number in (range(2, 3) if source else range(3)):
                if metadata['fileHashes'] != hashes():
                    raise ValueError('Sources changed before the API call; start a new experiment.')
                folder = run / 'calls' / f'round-{number}'
                folder.mkdir(parents=True)
                stage = 'build-request'
                params, logged = build_request(run, number, previous_id, settings)
                write_json(folder / 'request.json', logged)
                call = {'round': number, 'startedAt': now(), 'status': 'requesting',
                        'request': str((folder / 'request.json').relative_to(directory)),
                        'previousResponseId': previous_id}
                trial['calls'].append(call)
                save()
                print(f'  {portrait}: round {number + 1}/3 ({mode})', flush=True)
                stage = 'api-request'
                # Keep the SDK for transport/authentication, but save the response
                # before any typed-model conversion. No parse()/model_dump() step
                # is needed for this JSON-only experiment.
                response = client.responses.with_raw_response.create(**params)
                stage = 'save-api-response'
                (folder / 'api-response.json').write_bytes(response.http_response.content)
                stage = 'decode-api-response'
                raw = parse_json(response.http_response.text)
                if not isinstance(raw, dict):
                    raise ValueError('API response must be a JSON object; inspect api-response.json.')
                call.update(receivedAt=now(), responseId=raw.get('id'),
                            requestId=response.headers.get('x-request-id'),
                            actualModel=None if dry_run else raw.get('model'),
                            usage=raw.get('usage'), status='received')
                save()
                print_usage(f'{portrait} round {number + 1}/3', [call])
                stage = 'validate-model-output'
                text = response_text(raw)
                (folder / 'model-output.txt').write_text(text, encoding='utf-8')
                explain = number == 2 and settings.get('finalExplanation', True)
                layout, explanation = split_output(text, explain)
                changes = []
                if provider == 'deepseek':
                    layout, changes = normalize_sizes(layout)
                    if changes:
                        write_json(folder / 'normalization.json',
                                   {'policy': 'minimum-size-0.03', 'changes': changes})
                        call['normalization'] = str((folder / 'normalization.json').relative_to(directory))
                        print(f'  Applied minimum size 0.03 to {len(changes)} item(s).', flush=True)
                layout_path = folder / 'layout.json'
                if explain or changes:
                    write_json(layout_path, layout)
                else:
                    layout_path.write_text(text, encoding='utf-8')
                if explain:
                    write_json(folder / 'explanation.json', explanation)
                # Local validation also enforces identity rules across rounds.
                stage = 'render-layout'
                accepted = submit_response(renderer, run, layout_path)
                if explanation is not None:
                    write_json(accepted / 'explanation.json', explanation)
                    report = explanation['overall'] + '\n\n' + '\n'.join(
                        f"{', '.join(c['uids'])} — {c['feature']}: {c['reason']}" for c in explanation['choices'])
                    (accepted / 'explanation.txt').write_text(report + '\n', encoding='utf-8')
                    trial['explanation'] = str((accepted / 'explanation.json').relative_to(directory))
                    print(f'  Explanation: {accepted / "explanation.txt"}', flush=True)
                call.update(status='rendered', completedAt=now(),
                            feedback=str((accepted / 'feedback.png').relative_to(directory)))
                previous_id = raw['id']
                save()
            feedback = read_json(run / 'round-2/feedback.json')
            stage = 'export-final-files'
            final_paths = export_final(run, feedback)
            trial.update(status='completed', finalFeedback=f'{run.name}/round-2/feedback.png',
                         **final_paths,
                         usage=usage_totals(trial['calls']))
            if source:
                trial['comparison'] = compare_branch(run)
            save()
            print_usage(f'{portrait} subtotal', trial['calls'])
        record.update(status='completed', completedAt=now(),
                      usage=usage_totals([c for t in record['trials'] for c in t['calls']]))
        save()
        print_usage('Experiment total', [c for t in record['trials'] for c in t['calls']])
    except (Exception, KeyboardInterrupt) as error:
        failure = error_details(error, stage)
        write_json(directory / 'error.json', {**failure, 'runtime': record['runtime']})
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
        print(f'Failure stage: {stage}. Diagnostics: {directory / "error.json"}', flush=True)
        if failure.get('message'):
            print(f'{failure["type"]}: {failure["message"]}', flush=True)
        if failure['frames']:
            last = failure['frames'][-1]
            print(f'Location: {last["file"]}:{last["line"]} in {last["function"]}', flush=True)
        raise
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Use fabricated responses; no API connection or key')
    parser.add_argument('--portrait', choices=['all', *PORTRAITS], default='all')
    parser.add_argument('--provider', choices=list(PROVIDERS), default='openai')
    parser.add_argument('--model')
    parser.add_argument('--reasoning', choices=['none', 'low', 'medium', 'high', 'xhigh', 'max'])
    parser.add_argument('--max-output-tokens', type=int,
                        help='Per-call limit including reasoning tokens; default OpenAI 8192, DeepSeek 32768, Qwen 65536')
    parser.add_argument('--image-detail', choices=['low', 'high', 'auto'])
    parser.add_argument('--max-edge', type=int)
    parser.add_argument('--timeout', type=float, help='Per-request timeout; default 900 seconds, retries disabled')
    continuation = parser.add_mutually_exclusive_group()
    continuation.add_argument('--from-round-2', type=Path,
                              help='Fork a saved portrait after its second round; call only round 3')
    continuation.add_argument('--repair-round-2', type=Path,
                              help='Locally clamp and render a saved DeepSeek second round; no API call')
    parser.add_argument('--no-final-explanation', action='store_true', help='Keep the legacy layout-only control condition')
    parser.add_argument('--output', type=Path, help='Optional raw-record directory; live results are still organized in ai-results')
    parser.add_argument('--result-group', help='Existing model_reasoning_number group to complete with a missing portrait')
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    config = PROVIDERS[args.provider]
    settings = {'provider': args.provider, 'model': config['model'],
                'reasoning': config['reasoning'], 'maxOutputTokens': config['maxOutputTokens'],
                'imageDetail': 'high', 'maxEdge': 1024, 'timeoutSeconds': 900}
    overrides = {'model': args.model, 'reasoning': args.reasoning,
                 'maxOutputTokens': args.max_output_tokens, 'imageDetail': args.image_detail,
                 'maxEdge': args.max_edge, 'timeoutSeconds': args.timeout}
    portraits = list(PORTRAITS) if args.portrait == 'all' else [args.portrait]
    try:
        if args.repair_round_2:
            if args.provider != 'deepseek' or args.dry_run:
                raise ValueError('Local repair requires --provider deepseek and no --dry-run.')
            output = args.output or ROOT / 'result-data/deepseek-experiments'
            with BrowserRenderer(args.headed) as renderer:
                repaired = repair_second_round(renderer, args.repair_round_2.resolve(), output.resolve())
            print(f'Repaired second-round checkpoint: {repaired}')
            print(f'Feedback PNG: {repaired / "round-1/feedback.png"}')
            print('No API calls made. Continue using --provider deepseek --from-round-2 with this path.')
            return
        source = args.from_round_2.resolve() if args.from_round_2 else None
        if source:
            original, source_trial, settings = branch_source(source)
            if settings.get('provider', 'openai') != args.provider:
                raise ValueError('--provider must match the source experiment.')
            portraits = [original['portraitId']]
            if args.portrait != 'all' and args.portrait != portraits[0]:
                raise ValueError('Portrait must match the source trial.')
            if any(value is not None and value != settings[key] for key, value in overrides.items()):
                raise ValueError('A branch inherits the original model and parameters; do not override them.')
        else:
            settings.update({key: value for key, value in overrides.items() if value is not None})
        settings['finalExplanation'] = not args.no_final_explanation
        if args.provider == 'deepseek':
            settings['sizePolicy'] = 'minimum-size-0.03'
            if settings['model'] != 'deepseek-flash':
                raise ValueError('Use deepseek-flash for this image-input experiment.')
            if settings['reasoning'] not in ('none', 'low', 'high', 'max'):
                raise ValueError('DeepSeek native reasoning levels: none, low, high, max. '
                                 'Use high instead of the medium/xhigh aliases.')
        if args.provider == 'qwen':
            if settings['model'] not in ('qwen3.8-max', 'qwen3.8-max-0902', 'qwen3.8-flash'):
                raise ValueError('Use qwen3.8-max, qwen3.8-max-0902, or qwen3.8-flash for this adapter.')
            if settings['reasoning'] not in ('none', 'low', 'medium', 'xhigh'):
                raise ValueError('Qwen 3.8 native reasoning levels: none, low, medium, xhigh. '
                                 'Use xhigh rather than the high/max aliases so records stay unambiguous.')
            if settings['maxOutputTokens'] > 131072:
                raise ValueError('Qwen 3.8 max-output-tokens cannot exceed 131072.')
            settings['region'] = 'cn-beijing'
            settings['imageDetail'] = 'auto'
        if (settings['maxOutputTokens'] < 16 or not 256 <= settings['maxEdge'] <= 2048
                or settings['timeoutSeconds'] <= 0):
            raise ValueError('Use at least 16 output tokens, positive timeout and max-edge in [256, 2048].')
        if args.dry_run and args.result_group:
            raise ValueError('Dry runs cannot be added to real result groups.')
        from ai_results import DEFAULT_ROOT, reserve_group, check_portraits_available, register_experiment
        group = None
        if not args.dry_run:
            group = reserve_group(DEFAULT_ROOT, settings['model'], settings['reasoning'], args.result_group)
            check_portraits_available(group, portraits)
            print(f'Result folder: {group}', flush=True)
        client, transport = create_client(args.dry_run, settings['timeoutSeconds'], args.provider)
        if source and transport:
            second = next(c for c in source_trial['calls'] if c['round'] == 1)
            transport.seed_branch(second['responseId'], read_json(source / 'round-1/response.txt'))
        with client, BrowserRenderer(args.headed) as renderer:
            output = (args.output or (group / 'records' if group else
                      ROOT / 'result-data' / f'{args.provider}-experiments')).resolve()
            previous = set(output.glob('*/experiment.json'))
            try:
                directory = run_experiment(renderer, client, portraits, output, settings, args.dry_run, source)
            finally:
                if group:
                    # Organize completed portraits even if a later portrait failed.
                    # Never retry an API call because gallery generation failed.
                    for saved in sorted(set(output.glob('*/experiment.json')) - previous):
                        try:
                            register_experiment(group, saved.parent, move=False)
                        except Exception as archive_error:
                            print(f'Result organization failed ({type(archive_error).__name__}); '
                                  f'original records remain at {saved.parent}', flush=True)
                    print(f'Result gallery: {group / "index.html"}', flush=True)
        print(f'Completed: {directory / "experiment.json"}')
        print(f'Token usage: {directory / "token-usage.json"}')
        record = read_json(directory / 'experiment.json')
        for trial in record['trials']:
            print(f'  {trial["portraitId"]} final PNG: {directory / trial["finalPng"]}')
            if trial.get('explanationText'):
                print(f'  Explanation: {directory / trial["explanationText"]}')
            if trial.get('comparison'):
                print(f'  Layout comparison: {directory / trial["comparison"]}')
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
