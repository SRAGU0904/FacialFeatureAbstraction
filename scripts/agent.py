#!/usr/bin/env python3
"""Local structured-layout / image-feedback runner. No model API calls."""
import argparse
import base64
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import functools
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import uuid

from server import ROOT, PORTRAITS, StudioHandler, ThreadingHTTPServer, save_snapshot, validate_scene

ITEM_FIELDS = {'uid', 'id', 'x', 'y', 'size', 'angle'}
OPTIONAL_ITEM_FIELDS = {'flipX', 'flipY'}
PROTOCOL_VERSION = 2


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def parse_json(text):
    # Duplicate keys are almost always a malformed model response; never silently discard them.
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def read_json(path):
    return parse_json(path.read_text(encoding='utf-8'))


def food_ids():
    return {a['id'] for a in read_json(ROOT / 'assets/foods/manifest.json')['assets']}


def empty_scene(portrait):
    w, h = PORTRAITS[portrait]
    return {'schemaVersion': 1, 'assetVersion': '1', 'rendererVersion': '1',
            'portraitId': portrait, 'canvas': {'width': w, 'height': h}, 'items': []}


def checked_items(items):
    if not isinstance(items, list):
        raise ValueError('Expected an array of complete items.')
    for item in items:
        if (not isinstance(item, dict) or not ITEM_FIELDS <= set(item)
                or set(item) - (ITEM_FIELDS | OPTIONAL_ITEM_FIELDS)):
            raise ValueError('Each item needs uid, id, x, y, size, angle; only flipX and flipY are optional.')
    return items


def apply_response(scene, response, used_uids=()):
    """Replace the full item list atomically, retaining stable instance identities."""
    if not isinstance(response, dict) or set(response) != {'items'}:
        raise ValueError('Every response must contain only a complete items array.')
    candidate = deepcopy(scene)
    candidate['items'] = deepcopy(checked_items(response['items']))
    candidate = validate_scene(candidate, food_ids())
    previous = {item['uid']: item['id'] for item in scene['items']}
    retired = set(used_uids) - previous.keys()
    for item in candidate['items']:
        if item['uid'] in retired:
            raise ValueError('A removed uid cannot be reused; use a fresh uid.')
        if item['uid'] in previous and item['id'] != previous[item['uid']]:
            raise ValueError('An existing uid must retain its asset id; use a fresh uid for a replacement.')
    return candidate


class QuietHandler(StudioHandler):
    def log_message(self, *_args):
        pass


class BrowserRenderer:
    """One isolated browser and temporary local server, reusable across rounds."""
    def __init__(self, headed=False):
        self.headed = headed

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=ROOT))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.playwright = None
        self.browser = None
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=not self.headed)
            self.page = None
            self.url = f'http://127.0.0.1:{self.server.server_port}'
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_args):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def inputs(self, portrait, max_edge):
        # Contact-sheet resampling can prime Chromium's image-scale cache. Keep it
        # in a separate context so it cannot affect subsequent scene pixels.
        page = self.browser.new_page()
        try:
            page.goto(self.url + '/agent-render.html')
            return page.evaluate('arg => window.FOODFACE_AGENT.inputs(arg)',
                                 {'portraitId': portrait, 'maxEdge': max_edge})
        finally:
            page.close()

    def render(self, scene, max_edge):
        # Fresh image resources also prevent earlier rounds at different scales
        # from influencing Chromium's resampling. The browser process is reused.
        if self.page:
            self.page.close()
        self.page = self.browser.new_page()
        self.page.goto(self.url + '/agent-render.html')
        return self.page.evaluate('arg => window.FOODFACE_AGENT.render(arg)',
                                  {'scene': scene, 'maxEdge': max_edge})


def hashes():
    files = [p for p in (ROOT / 'assets').rglob('*') if p.suffix in {'.png', '.js', '.json'}]
    files += [ROOT / name for name in ('agent-render.html', 'scripts/agent.py', 'scripts/server.py',
                                      'scripts/requirements-agent.txt', 'prompts/agent-layout.txt')]
    files += [p for p in (ROOT / 'scripts/openai_experiment.py', ROOT / 'scripts/requirements-openai.txt',
                         ROOT / 'prompts/agent-final-explanation.txt')
              if p.exists()]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def image_file(folder, name, image):
    (folder / name).write_bytes(base64.b64decode(image['png'], validate=True))
    return {'file': name, 'width': image['width'], 'height': image['height']}


def start_run(renderer, portrait, output_root, max_edge=1024):
    if not 256 <= max_edge <= 2048:
        raise ValueError('Observation max-edge must be in [256, 2048].')
    before = hashes()
    data = renderer.inputs(portrait, max_edge)
    if data['canvas'] != empty_scene(portrait)['canvas']:
        raise ValueError('Browser and Python portrait dimensions disagree.')
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    target = output_root / f'Agent-{portrait}-{run_id}'
    staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=output_root))
    try:
        inputs = staging / 'inputs'
        inputs.mkdir()
        images = {name: image_file(inputs, name + '.png', data[name]) for name in ('original', 'empty', 'foods')}
        write_json(inputs / 'manifest.json', {'portraitId': portrait, 'canvas': data['canvas'],
                                             'faceBounds': data['faceBounds'],
                                             'images': images, 'foods': data['catalog']})
        prompt = (ROOT / 'prompts/agent-layout.txt').read_text(encoding='utf-8')
        prompt = prompt.replace('{{WIDTH}}', str(data['canvas']['width'])).replace('{{HEIGHT}}', str(data['canvas']['height']))
        prompt = prompt.replace('{{FACE_BOUNDS}}', json.dumps(data['faceBounds'], separators=(',', ':')))
        catalog = '\n'.join(f"{a['id']}: crop {a['crop']['w']} x {a['crop']['h']} px" for a in data['catalog'])
        (inputs / 'prompt.txt').write_text(prompt.replace('{{CATALOG}}', catalog), encoding='utf-8')
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        if hashes() != before:
            raise ValueError('Assets or runner changed during input preparation; start again.')
        write_json(staging / 'run.json', {
            'runId': run_id, 'createdAt': now(), 'portraitId': portrait,
            'protocolVersion': PROTOCOL_VERSION, 'maxAdjustments': 2, 'maxEdge': max_edge,
            'responseSource': 'manual-json', 'model': None, 'modelParameters': None,
            'gitCommit': revision.stdout.strip() if revision.returncode == 0 else None,
            'fileHashes': before, 'browserVersion': renderer.browser.version,
        })
        staging.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


@contextmanager
def run_lock(run):
    lock = run / '.lock'
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError('This run is busy. If a runner crashed, remove its stale .lock directory.') from error
    try:
        yield
    finally:
        lock.rmdir()


def submit_response(renderer, run, response_path):
    with run_lock(run):
        metadata = read_json(run / 'run.json')
        if metadata.get('protocolVersion') != PROTOCOL_VERSION:
            raise ValueError('Unsupported response protocol. Start a new run.')
        if metadata['fileHashes'] != hashes():
            raise ValueError('Assets or runner changed since this run began. Start a new run.')
        if metadata['browserVersion'] != renderer.browser.version:
            raise ValueError('Browser version changed. Start a new run.')
        rounds = sorted(run.glob('round-[0-2]'))
        number = len(rounds)
        if number >= 3:
            raise ValueError('Run complete: initial layout and two adjustments already rendered.')
        scene = empty_scene(metadata['portraitId'])
        used = set()
        for folder in rounds:
            scene = read_json(folder / 'feedback.json')['scene']
            used.update(i['uid'] for i in scene['items'])
        submitted_at = now()
        raw = response_path.read_text(encoding='utf-8')
        try:
            response = parse_json(raw)
            scene = apply_response(scene, response, used_uids=used)
        except ValueError as error:
            write_json(run / f'rejected-{uuid.uuid4()}.json',
                       {'submittedAt': submitted_at, 'round': number, 'rawResponse': raw, 'error': str(error)})
            raise
        result = renderer.render(scene, metadata['maxEdge'])
        if metadata['fileHashes'] != hashes():
            raise ValueError('Assets or runner changed during rendering; response not committed.')
        staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=run))
        try:
            (staging / 'response.txt').write_text(raw, encoding='utf-8')
            full = base64.b64decode(result['full']['png'], validate=True)
            snapshot = save_snapshot(staging, scene, full)
            pair = Path(snapshot['directory']).name
            snapshot = {k: f"{pair}/{Path(snapshot[k]).name}" for k in ('json', 'png')}
            image = image_file(staging, 'feedback.png', result['feedback'])
            feedback = {'round': number, 'remainingAdjustments': 2 - number,
                        'submittedAt': submitted_at, 'renderedAt': now(),
                        'scene': scene, 'image': image, 'snapshot': snapshot}
            write_json(staging / 'feedback.json', feedback)
            if number < 2:
                message = (f'Review round {number + 2} of 3. Inspect the attached latest collage. '
                           'Use the original portrait and asset reference supplied initially. '
                           'Changes are optional. If the current collage is good enough, return exactly '
                           'the same complete JSON layout as in your previous response. '
                           'Do not make changes just because another round is available. '
                           'Return the complete layout as {\"items\":[...]}, including unchanged items. '
                           'Keep existing uids for retained instances; use fresh uids for new ones. '
                           'Omitted items are removed. Later array entries cover earlier entries.\n')
            else:
                message = 'Run complete. This is the final collage; no further response is requested.\n'
            (staging / 'next-prompt.txt').write_text(message, encoding='utf-8')
            destination = run / f'round-{number}'
            staging.rename(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headed', action='store_true', help='Show the isolated browser while rendering')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('start', 'demo'):
        p = commands.add_parser(name)
        p.add_argument('--portrait', choices=PORTRAITS, default='zhu')
        p.add_argument('--output', type=Path, default=ROOT / 'result-data/agent-runs')
        p.add_argument('--max-edge', type=int, default=1024, help='Observation longest edge; saved snapshots stay full resolution')
    p = commands.add_parser('apply')
    p.add_argument('run', type=Path)
    p.add_argument('response', type=Path)
    args = parser.parse_args()
    try:
        with BrowserRenderer(args.headed) as renderer:
            if args.command == 'apply':
                folder = submit_response(renderer, args.run.resolve(), args.response.resolve())
                print(json.dumps({'round': str(folder), 'feedback': str(folder / 'feedback.png')}, indent=2))
            else:
                run = start_run(renderer, args.portrait, args.output.resolve(), args.max_edge)
                if args.command == 'demo':
                    for name in ('initial', 'adjust-1', 'adjust-2'):
                        submit_response(renderer, run, ROOT / f'examples/agent/{name}.json')
                print(json.dumps({'run': str(run), 'inputs': str(run / 'inputs'),
                                  'finalFeedback': str(run / 'round-2/feedback.png') if args.command == 'demo' else None}, indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f'Error: {error}\n')
    except ImportError:
        parser.exit(1, 'Install scripts/requirements-agent.txt and run: python -m playwright install chromium\n')


if __name__ == '__main__':
    main()
