"""Check received human JSON compatibility without launching a browser."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent import apply_response, empty_scene
from render_scene import load_scene, main, render_file, render_jobs
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

    def test_numbered_folder_renders_both_portraits_beside_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / '0001'
            folder.mkdir()
            originals = {}
            for portrait in ('euro', 'zhu'):
                source = folder / f'{portrait}.json'
                source.write_text(json.dumps(empty_scene(portrait)), encoding='utf-8')
                originals[source] = source.read_bytes()
            # Only immediate JSON files are inputs; a nested participant stays separate.
            (folder / 'nested').mkdir()
            (folder / 'nested' / 'bad.json').write_text('{}')
            (folder / 'notes.txt').write_text('Test notes')
            renderer = Mock()
            renderer.render.side_effect = lambda scene, _: {'full': {'png': base64.b64encode(
                png_image(scene['canvas']['width'], scene['canvas']['height'])).decode()}}
            with patch('render_scene.BrowserRenderer') as browser, patch('sys.argv', ['render_scene.py', str(folder)]):
                browser.return_value.__enter__.return_value = renderer
                main()
                browser.assert_called_once_with()
            self.assertEqual(renderer.render.call_count, 2)
            for source, original in originals.items():
                self.assertEqual(source.read_bytes(), original)
                self.assertTrue(source.with_suffix('.png').exists())

    def test_folder_preflight_rejects_bad_scene_or_existing_output_before_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'euro.json').write_text(json.dumps(empty_scene('euro')))
            (folder / 'zhu.json').write_text('{}')
            with patch('render_scene.BrowserRenderer') as browser, patch('sys.argv', ['render_scene.py', str(folder)]):
                with self.assertRaises(SystemExit):
                    main()
                browser.assert_not_called()
            self.assertFalse((folder / 'euro.png').exists())
            (folder / 'zhu.json').write_text(json.dumps(empty_scene('zhu')))
            (folder / 'zhu.png').write_bytes(b'Existing image')
            with self.assertRaises(FileExistsError):
                render_jobs(folder)
            self.assertEqual((folder / 'zhu.png').read_bytes(), b'Existing image')
            self.assertFalse((folder / 'euro.png').exists())

    def test_single_file_defaults_and_invalid_folder_options(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with self.assertRaisesRegex(ValueError, 'No .json'):
                render_jobs(folder)
            source = folder / 'zhu.json'
            source.write_text(json.dumps(empty_scene('zhu')))
            self.assertEqual(render_jobs(source), [(source, folder / 'zhu.png')])
            custom = folder / 'custom.png'
            self.assertEqual(render_jobs(source, custom), [(source, custom)])
            with self.assertRaisesRegex(ValueError, '--output'):
                render_jobs(folder, custom)


if __name__ == '__main__':
    unittest.main()
