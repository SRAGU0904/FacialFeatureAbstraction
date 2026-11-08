#!/usr/bin/env python3
"""Render one scene JSON or a folder of scene JSONs with the existing renderer."""
import argparse
import base64
from pathlib import Path

from agent import BrowserRenderer, food_ids, read_json
from server import validate_scene


def load_scene(source):
    # Participant metadata is retained in the source JSON, not used as render input.
    return validate_scene(read_json(source), food_ids())


def render_file(source, output, renderer):
    scene = load_scene(source)
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}')
    rendered = renderer.render(scene, 1024)
    png = base64.b64decode(rendered['full']['png'], validate=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(png)
    return output


def render_jobs(source, output=None):
    """Preflight every input/output before starting the browser or writing images."""
    if source.is_dir():
        if output is not None:
            raise ValueError('--output is only supported for a single JSON file.')
        sources = sorted(path for path in source.glob('*.json') if path.is_file())
        if not sources:
            raise ValueError(f'No .json files found directly inside: {source}')
        jobs = [(path, path.with_suffix('.png')) for path in sources]
    else:
        jobs = [(source, output if output is not None else source.with_suffix('.png'))]
    for path, destination in jobs:
        load_scene(path)
        if destination.exists():
            raise FileExistsError(f'Output already exists: {destination}')
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Full scene JSON or folder containing scene .json files')
    parser.add_argument('--output', type=Path,
                        help='Single-file output path; otherwise save each PNG beside its JSON')
    args = parser.parse_args()
    try:
        jobs = render_jobs(args.source, args.output)
        with BrowserRenderer() as renderer:
            for source, output in jobs:
                print(render_file(source, output, renderer), flush=True)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
