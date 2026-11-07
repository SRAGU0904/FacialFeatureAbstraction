#!/usr/bin/env python3
"""Render a received human or agent scene JSON with the existing agent renderer."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Full scene JSON received from a participant or agent')
    parser.add_argument('--output', type=Path, required=True, help='New full-resolution PNG file')
    args = parser.parse_args()
    try:
        load_scene(args.source)
        if args.output.exists():
            raise FileExistsError(f'Output already exists: {args.output}')
        with BrowserRenderer() as renderer:
            output = render_file(args.source, args.output, renderer)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(output)


if __name__ == '__main__':
    main()
