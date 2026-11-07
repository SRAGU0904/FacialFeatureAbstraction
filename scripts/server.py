#!/usr/bin/env python3
"""Serve FoodFace locally without dependencies or uploading any files."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import base64
import binascii
from datetime import datetime, timezone
import functools
import hashlib
import json
import math
import shutil
import struct
import tempfile
import threading
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 32 * 1024 * 1024
PORTRAITS = {'zhu': (1450, 1524), 'euro': (1312, 1604)}
SUBMISSION_LOCK = threading.Lock()


def validate_scene(scene, food_ids):
    if not isinstance(scene, dict):
        raise ValueError('Missing scene data.')
    if (scene.get('schemaVersion') != 1 or scene.get('assetVersion') != '1'
            or scene.get('rendererVersion') != '1'):
        raise ValueError('Unsupported scene version.')
    portrait = scene.get('portraitId')
    if not isinstance(portrait, str) or portrait not in PORTRAITS:
        raise ValueError('Unknown portrait.')
    width, height = PORTRAITS[portrait]
    if scene.get('canvas') != {'width': width, 'height': height}:
        raise ValueError('Incorrect canvas dimensions.')
    items = scene.get('items')
    if not isinstance(items, list):
        raise ValueError('Scene items must be a list.')
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid item.')
        item_id, food = item.get('uid'), item.get('id')
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 128 or item_id in seen:
            raise ValueError('Item IDs must be unique nonempty strings.')
        seen.add(item_id)
        if not isinstance(food, str) or food not in food_ids:
            raise ValueError('Unknown food asset.')
        for key, low, high in [('x', 0, 1), ('y', 0, 1), ('size', .03, .9), ('angle', -180, 180)]:
            value = item.get(key)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not low <= value <= high):
                raise ValueError(f'Invalid item {key}.')
        for key in ('flipX', 'flipY'):
            if key in item and type(item[key]) is not bool:
                raise ValueError(f'Invalid item {key}.')
    clean_scene = {key: scene[key] for key in
                   ('schemaVersion', 'assetVersion', 'rendererVersion', 'portraitId', 'canvas')}
    clean_scene['items'] = [
        {key: item[key] for key in ('uid', 'id', 'x', 'y', 'size', 'angle', 'flipX', 'flipY')
         if key in item} for item in items]
    return clean_scene


def validate_payload(payload, food_ids):
    if not isinstance(payload, dict):
        raise ValueError("Missing scene data.")
    clean_scene = validate_scene(payload.get("scene"), food_ids)
    width, height = PORTRAITS[clean_scene["portraitId"]]
    try:
        png = base64.b64decode(payload['png'], validate=True)
    except (KeyError, ValueError, TypeError, binascii.Error) as error:
        raise ValueError('Invalid PNG data.') from error
    if (len(png) < 33 or png[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
            or struct.unpack('>II', png[16:24]) != (width, height)
            or png[-12:] != b'\x00\x00\x00\x00IEND\xaeB`\x82'):
        raise ValueError('PNG dimensions or format do not match the scene.')
    return clean_scene, png


def save_snapshot(save_root, scene, png, *, snapshot_id=None):
    """Publish the pair together; failed writes never expose a partial snapshot."""
    snapshot_id = snapshot_id or str(uuid.uuid4())
    saved_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    stem = f"FoodFace-{scene['portraitId']}-{snapshot_id}"
    document = {**scene, 'snapshotId': snapshot_id, 'savedAt': saved_at,
                'image': {'file': stem + '.png', 'sha256': hashlib.sha256(png).hexdigest()}}
    save_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=save_root))
    try:
        (staging / (stem + '.png')).write_bytes(png)
        (staging / (stem + '.json')).write_text(
            json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        staging.rename(save_root / stem)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {'snapshotId': snapshot_id, 'directory': f'result-data/{stem}',
            'json': f'result-data/{stem}/{stem}.json', 'png': f'result-data/{stem}/{stem}.png'}


class SubmissionConflict(ValueError):
    def __init__(self, document):
        super().__init__('This portrait has already been submitted and cannot be changed.')
        self.document = document


def save_submission(save_root, scene, png, session_id):
    """One immutable result per portrait/session; identical retries reuse the receipt."""
    trial_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'foodface:human:{session_id}:{scene["portraitId"]}'))
    stem = f"FoodFace-{scene['portraitId']}-{trial_id}"
    scene = {**scene, 'experiment': {'actorType': 'human', 'sessionId': session_id,
                                   'trialId': trial_id, 'status': 'submitted'}}
    with SUBMISSION_LOCK:
        existing = save_root / stem / (stem + '.json')
        if existing.exists():
            document = json.loads(existing.read_text(encoding='utf-8'))
            if (any(document.get(key) != value for key, value in scene.items())
                    or document['image']['sha256'] != hashlib.sha256(png).hexdigest()):
                raise SubmissionConflict(document)
            return {'snapshotId': trial_id, 'directory': f'result-data/{stem}',
                    'json': f'result-data/{stem}/{stem}.json', 'png': f'result-data/{stem}/{stem}.png'}
        return save_snapshot(save_root, scene, png, snapshot_id=trial_id)


class StudioHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=ROOT, save_root=None, **kwargs):
        self.save_root = Path(save_root) if save_root is not None else Path(directory) / 'result-data'
        manifest = json.loads((Path(directory) / 'assets/foods/manifest.json').read_text(encoding='utf-8'))
        self.food_ids = {asset['id'] for asset in manifest['assets']}
        super().__init__(*args, directory=str(directory), **kwargs)

    def reply(self, status, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ('/api/snapshots', '/api/submissions'):
            self.reply(404, {'error': 'Unknown endpoint.'})
            return
        # Only this local studio may write; reject cross-site browser requests.
        hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        host = self.headers.get('Host')
        origin = self.headers.get('Origin')
        if host not in hosts or (origin is not None and origin != f'http://{host}'):
            self.reply(403, {'error': 'Save from the local FoodFace page.'})
            return
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            self.reply(415, {'error': 'Expected JSON.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                self.reply(413, {'error': 'Save request is empty or too large.'})
                return
            payload = json.loads(self.rfile.read(length))
            scene, png = validate_payload(payload, self.food_ids)
            session_id = payload.get('sessionId')
            if self.path == '/api/submissions':
                if not isinstance(session_id, str) or str(uuid.UUID(session_id)) != session_id:
                    raise ValueError('Invalid session ID.')
        except (ValueError, OverflowError, RecursionError):
            self.reply(400, {'error': 'Invalid scene, PNG or session. Keep this page open and try again.'})
            return
        try:
            if self.path == '/api/submissions':
                result = save_submission(self.save_root, scene, png, session_id)
            else:
                result = save_snapshot(self.save_root, scene, png)
        except SubmissionConflict as error:
            self.reply(409, {'error': str(error), 'scene': error.document})
            return
        except OSError:
            self.reply(500, {'error': 'Could not write files. Check disk space and folder permissions.'})
            return
        self.reply(201, result)


def main():
    parser = argparse.ArgumentParser(description='FoodFace local studio')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    handler = functools.partial(StudioHandler, directory=ROOT)
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError:
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    address = f'http://127.0.0.1:{server.server_port}'
    print(f'\nFoodFace is running at {address}\nKeep this window open. Press Control+C to stop.\n', flush=True)
    if not args.no_browser:
        threading.Timer(.5, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nFoodFace stopped.')
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
