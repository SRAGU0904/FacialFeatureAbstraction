"""Check received human JSON compatibility without launching a browser."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from agent import apply_response, empty_scene
from render_scene import load_scene, render_file
from test_server import png_image


class ReceivedSceneTests(unittest.TestCase):
    def test_human_metadata_does_not_change_agent_render_input(self):
        for portrait in ('zhu', 'euro'):
            with self.subTest(portrait=portrait), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                item = dict(uid='test-food', id='pear', x=.45, y=.5, size=.3,
                            angle=35, flipX=True, flipY=True)
                expected = apply_response(empty_scene(portrait), {'items': [item]})
                result = {**expected, 'demographics': {
                    'gender': 'prefer-not-to-say', 'age': 25, 'nationality': 'Test'},
                    'experiment': {'actorType': 'human', 'sessionId': 'test-session'},
                    'researchNotice': 'Test notice'}
                source, output = root / 'result.json', root / 'result.png'
                source.write_text(json.dumps(result), encoding='utf-8')
                original = source.read_bytes()
                png = png_image(expected['canvas']['width'], expected['canvas']['height'])
                renderer = Mock()
                renderer.render.return_value = {'full': {'png': base64.b64encode(png).decode()}}
                self.assertEqual(load_scene(source), expected)
                self.assertEqual(render_file(source, output, renderer), output)
                renderer.render.assert_called_once_with(expected, 1024)
                self.assertEqual(output.read_bytes(), png)
                self.assertEqual(source.read_bytes(), original)
                with self.assertRaises(FileExistsError):
                    render_file(source, output, renderer)
                self.assertEqual(renderer.render.call_count, 1)

    def test_invalid_scene_is_rejected_before_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'bad.json', Path(directory) / 'bad.png'
            source.write_text(json.dumps({'items': []}), encoding='utf-8')
            renderer = Mock()
            with self.assertRaises(ValueError):
                render_file(source, output, renderer)
            renderer.render.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
