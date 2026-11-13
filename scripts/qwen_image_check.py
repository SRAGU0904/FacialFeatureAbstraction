#!/usr/bin/env python3
"""One tiny-image Qwen connectivity check, separate from formal experiments."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

from agent import ROOT, now, write_json
from openai_experiment import PROVIDERS, create_client, response_text, print_usage


def test_png():
    """Deterministic 256px diagnostic: red circle at left, blue square at right."""
    size = 256
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter: none
        for x in range(size):
            color = (255, 255, 255)
            if (x - 68) ** 2 + (y - 128) ** 2 <= 40 ** 2:
                color = (230, 30, 30)
            elif 152 <= x < 232 and 88 <= y < 168:
                color = (30, 70, 230)
            rows.extend(color)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(rows))) + chunk(b'IEND', b''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='HTTP mock; no real key or network')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'result-data/ai-results/archive/diagnostics/qwen-small-image')
    args = parser.parse_args()
    import httpx2
    image = test_png()
    body = {'model': 'qwen3.8-max', 'reasoning': {'effort': 'none'},
            'max_output_tokens': 256, 'store': False,
            'input': [{'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'Describe the shapes, colors, and left-to-right positions in this image in one short sentence.'},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,' + base64.b64encode(image).decode('ascii')}]}]}
    if args.dry_run:
        from openai import OpenAI, DefaultHttpxClient
        def mock(request):
            sent = json.loads(request.content)
            assert str(request.url) == PROVIDERS['qwen']['url'] + '/responses'
            assert sent == body
            assert base64.b64decode(sent['input'][0]['content'][1]['image_url'].split(',')[1]) == image
            return httpx2.Response(200, json={'id': 'simulated-image-check', 'status': 'completed',
                'usage': None, 'output': [{'type': 'message', 'content': [{'type': 'output_text',
                    'text': 'SIMULATED: a red circle on the left and a blue square on the right.'}]}]})
        client = OpenAI(api_key='dry-run-placeholder', base_url=PROVIDERS['qwen']['url'], max_retries=0,
                        http_client=DefaultHttpxClient(transport=httpx2.MockTransport(mock), trust_env=False))
    else:
        # Same endpoint, SDK, gzip, and network behavior as the experiment;
        # only payload, thinking, and timeouts differ. Key remains local.
        client, _ = create_client(False, httpx2.Timeout(60, connect=10, write=15, pool=10), 'qwen')
    args.output.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        folder = args.output / f'{"dry-run" if args.dry_run else "test"}-{number:03d}'
        try:
            folder.mkdir()
            break
        except FileExistsError:
            number += 1
    (folder / 'test-image.png').write_bytes(image)
    logged = json.loads(json.dumps(body))
    logged['input'][0]['content'][1] = {'type': 'input_image', 'localFile': 'test-image.png',
        'bytes': len(image), 'sha256': hashlib.sha256(image).hexdigest()}
    write_json(folder / 'request.json', logged)
    result = {'startedAt': now(), 'status': 'requesting', 'simulated': args.dry_run,
              'endpoint': PROVIDERS['qwen']['url'] + '/responses', 'model': 'qwen3.8-max',
              'reasoning': 'none', 'imageBytes': len(image), 'width': 256, 'height': 256,
              'timeoutsSeconds': {'connect': 10, 'write': 15, 'read': 60, 'pool': 10},
              'automaticRetries': 0, 'usage': None}
    write_json(folder / 'result.json', result)
    print(f'Records: {folder}', flush=True)
    print(f'Sending one 256 x 256 PNG ({len(image):,} bytes) to qwen3.8-max; thinking off.', flush=True)
    print('Upload timeout: 15s; response read timeout: 60s; automatic retries: 0.', flush=True)
    started = time.monotonic()
    try:
        with client:
            response = client.responses.with_raw_response.create(**body)
        (folder / 'api-response.json').write_bytes(response.http_response.content)
        raw = json.loads(response.http_response.text)
        result['usage'] = raw.get('usage')
        result['responseId'] = raw.get('id')
        answer = response_text(raw)
        (folder / 'answer.txt').write_text(answer + '\n', encoding='utf-8')
        result.update(status='completed', reply=answer)
        print('Reply:', answer)
        print_usage('Small-image check', [{'usage': raw.get('usage')}])
    except Exception as error:
        chain, seen = [], set()
        current = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            chain.append(type(current).__name__)
            current = current.__cause__ or current.__context__
        result.update(status='failed', errorTypes=chain, httpStatus=getattr(error, 'status_code', None))
        print('Failed:', ' -> '.join(chain), 'HTTP status:', result['httpStatus'])
        # No arbitrary exception text, headers, or environment values are logged.
    finally:
        result.update(finishedAt=now(), elapsedSeconds=round(time.monotonic() - started, 3))
        write_json(folder / 'result.json', result)
        print(f'Elapsed: {result["elapsedSeconds"]}s. Saved: {folder / "result.json"}')
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
