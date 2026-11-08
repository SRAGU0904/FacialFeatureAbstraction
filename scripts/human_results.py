#!/usr/bin/env python3
"""Archive received human JSON locally and render it with the existing renderer."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from agent import BrowserRenderer, food_ids, hashes, parse_json
from render_scene import render_file
from server import ROOT, validate_scene

DEFAULT_ROOT = ROOT / 'result-data' / 'human'
COLLECTIONS = ('formal', 'self-test')


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def human_document(raw):
    """Validate without rewriting the received bytes or dropping metadata."""
    try:
        document = parse_json(raw.decode('utf-8'))
    except json.JSONDecodeError as error:
        raise ValueError('Copy one complete JSON object without Markdown fences or extra text; '
                         f'save as UTF-8 without BOM. {error}') from error
    validate_scene(document, food_ids())
    experiment = document.get('experiment')
    if (not isinstance(experiment, dict) or experiment.get('actorType') != 'human'
            or experiment.get('status') != 'submitted'):
        raise ValueError('Expected a submitted human result, not an agent scene.')
    for key in ('sessionId', 'trialId'):
        value = experiment.get(key)
        if not isinstance(value, str):
            raise ValueError(f'Missing experiment.{key}.')
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError()
        except ValueError:
            raise ValueError(f'experiment.{key} must be a canonical UUID.') from None
    if not isinstance(document.get('demographics'), dict):
        raise ValueError('Missing demographics object.')
    # Reject nonstandard NaN/Infinity even in metadata; preserve all other fields.
    json.dumps(document, allow_nan=False)
    return document


def collection_path(root, collection):
    if collection not in COLLECTIONS:
        raise ValueError('Choose formal or self-test explicitly.')
    return root if collection == 'formal' else root / collection


@contextmanager
def archive_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.archive.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def find_trial(root, collection, trial_id):
    # Validate before interpolating into a filesystem glob.
    if str(uuid.UUID(trial_id)) != trial_id:
        raise ValueError('Expected a complete trial UUID.')
    matches = list(collection_path(root, collection).glob(f'session-*/*-{trial_id}/original.json'))
    if len(matches) != 1:
        raise ValueError(f'Expected one archived trial {trial_id}; found {len(matches)}.')
    return matches[0].parent


def import_result(raw, root, collection):
    document = human_document(raw)
    experiment = document['experiment']
    folder = collection_path(root, collection)
    with archive_lock(folder):
        matches = list(folder.glob(f'session-*/*-{experiment["trialId"]}/original.json'))
        if matches:
            if len(matches) != 1 or human_document(matches[0].read_bytes()) != document:
                raise ValueError('Conflicting content for an existing trialId; nothing was overwritten.')
            return matches[0].parent, False
        parent = folder / ('session-' + experiment['sessionId'])
        parent.mkdir(exist_ok=True)
        destination = parent / (document['portraitId'] + '-' + experiment['trialId'])
        staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=parent))
        try:
            (staging / 'original.json').write_bytes(raw)
            write_json(staging / 'receipt.json', {
                'collection': collection,
                'formalResearchData': collection == 'formal',
                'receivedAt': now(),
                'sourceSha256': sha256(raw),
                'sessionId': experiment['sessionId'],
                'trialId': experiment['trialId'],
                'portraitId': document['portraitId'],
            })
            staging.rename(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return destination, True


def render_sources():
    provenance = hashes()
    for name in ('scripts/render_scene.py', 'scripts/human_results.py'):
        provenance[name] = sha256((ROOT / name).read_bytes())
    return provenance


def rendered_images(folder):
    return sorted(path for path in folder.glob('renders/*/result.png')
                  if not path.parent.name.startswith('.'))


def render_trial(folder, renderer):
    source = folder / 'original.json'
    raw = source.read_bytes()
    receipt = json.loads((folder / 'receipt.json').read_text(encoding='utf-8'))
    if sha256(raw) != receipt['sourceSha256']:
        raise ValueError('Archived original.json has changed; restore it before rendering.')
    document = human_document(raw)
    provenance = render_sources()
    renders = folder / 'renders'
    renders.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=renders))
    destination = renders / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
    try:
        # Reuse the same validated scene-to-PNG implementation as manual rendering.
        render_file(source, staging / 'result.png', renderer)
        if source.read_bytes() != raw:
            raise ValueError('Source changed during rendering.')
        if render_sources() != provenance:
            raise ValueError('Project assets or code changed during rendering; retry.')
        write_json(staging / 'render.json', {
            'renderedAt': now(), 'sourceSha256': sha256(raw),
            'pngSha256': sha256((staging / 'result.png').read_bytes()),
            'canvas': document['canvas'], 'browserVersion': renderer.browser.version,
            'playwrightVersion': importlib.metadata.version('playwright'),
            'sourceFiles': provenance,
        })
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination / 'result.png'


def list_results(root, collection):
    folder = collection_path(root, collection)
    sources = sorted(folder.glob('session-*/*/original.json'))
    if not sources:
        print(f'No results in {collection}: {folder}')
        return
    sessions = {}
    for source in sources:
        document = human_document(source.read_bytes())
        sessions.setdefault(document['experiment']['sessionId'], []).append((source, document))
    print(f'{collection}: {len(sources)} results in {len(sessions)} sessions (not a participant count).')
    for session, entries in sessions.items():
        counts = {portrait: sum(doc['portraitId'] == portrait for _, doc in entries)
                  for portrait in ('zhu', 'euro')}
        print(f'\nSession {session}: zhu={counts["zhu"]}, euro={counts["euro"]}')
        for source, document in entries:
            images = rendered_images(source.parent)
            print(f'  {document["portraitId"]}  {document["experiment"]["trialId"]}  '
                  + (f'{len(images)} render(s)' if images else 'PENDING RENDER'))
            print(f'    {source.parent}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=DEFAULT_ROOT,
                        help='Private archive root (default: result-data/human)')
    commands = parser.add_subparsers(dest='command', required=True)
    ingest = commands.add_parser('import', help='Archive one complete human JSON and render it')
    source = ingest.add_mutually_exclusive_group(required=True)
    source.add_argument('--file', type=Path, help='UTF-8 JSON file')
    source.add_argument('--clipboard', action='store_true', help='Read the macOS clipboard')
    ingest.add_argument('--no-render', action='store_true', help='Archive now, render later')
    render = commands.add_parser('render', help='Create a new PNG without replacing prior renders')
    render.add_argument('trial_id', help='Complete trialId shown by list or import')
    listing = commands.add_parser('list', help='Show sessions, portrait counts and render status')
    for command in (ingest, render, listing):
        command.add_argument('--collection', choices=COLLECTIONS, required=True,
                             help='Keep formal research and self-tests separate')
    args = parser.parse_args()
    try:
        if args.command == 'list':
            list_results(args.data_root, args.collection)
            return
        if args.command == 'import':
            raw = (subprocess.run(['pbpaste'], check=True, capture_output=True).stdout
                   if args.clipboard else args.file.read_bytes())
            folder, created = import_result(raw, args.data_root, args.collection)
            print(('Archived: ' if created else 'Already archived (unchanged): ') + str(folder), flush=True)
            if args.no_render:
                return
            if not created and rendered_images(folder):
                print('Existing renders kept. Use render with the trialId to create another.')
                return
        else:
            folder = find_trial(args.data_root, args.collection, args.trial_id)
        trial_id = human_document((folder / 'original.json').read_bytes())['experiment']['trialId']
        try:
            with BrowserRenderer() as renderer:
                print(render_trial(folder, renderer))
        except Exception as error:
            raise RuntimeError(f'JSON remains archived at {folder}. Rendering failed: {error}\n'
                               f'Retry with: render {trial_id} --collection {args.collection}') from error
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
