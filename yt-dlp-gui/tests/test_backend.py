import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import options as opt  # noqa: E402
from backend.manager import parse_args  # noqa: E402
from backend.server import App, serve  # noqa: E402
from backend.storage import DEFAULT_OPTIONS, Storage  # noqa: E402


def make(**overrides):
    return {**DEFAULT_OPTIONS, **overrides}


class OptionsTest(unittest.TestCase):
    def test_defaults_parse(self):
        args = opt.build_args(make())
        parsed = parse_args([*args, 'https://example.com/v'])
        self.assertEqual(parsed.urls, ['https://example.com/v'])
        self.assertEqual(parsed.ydl_opts['format'], 'bv*+ba/b')

    def test_video_quality_sort(self):
        args = opt.build_args(make(quality='1080', container='mp4', vcodec='h264'))
        parsed = parse_args(args)
        self.assertEqual(parsed.ydl_opts['format_sort'], ['vcodec:h264', 'res:1080', 'ext:mp4:m4a'])
        self.assertEqual(parsed.ydl_opts['merge_output_format'], 'mp4')

    def test_audio_mode(self):
        args = opt.build_args(make(mode='audio', audio_format='mp3', audio_quality='192K'))
        parsed = parse_args(args)
        keys = [pp['key'] for pp in parsed.ydl_opts['postprocessors']]
        self.assertIn('FFmpegExtractAudio', keys)
        extract = next(pp for pp in parsed.ydl_opts['postprocessors'] if pp['key'] == 'FFmpegExtractAudio')
        self.assertEqual(extract['preferredcodec'], 'mp3')
        self.assertEqual(extract['preferredquality'], '192')
        self.assertNotIn('--embed-chapters', args)

    def test_custom_format(self):
        args = opt.build_args(make(mode='custom', custom_format='137+140', format_sort=''))
        self.assertEqual(parse_args(args).ydl_opts['format'], '137+140')

    def test_subs_sponsorblock_sections(self):
        args = opt.build_args(make(subtitles=True, sub_langs='ru,en', auto_subs=True, sponsorblock='remove',
                                   section_start='1:00', section_end='2:30'))
        params = parse_args(args).ydl_opts
        self.assertTrue(params['writesubtitles'])
        self.assertTrue(params['writeautomaticsub'])
        self.assertEqual(params['subtitleslangs'], ['ru', 'en'])
        self.assertIn('download_ranges', params)
        self.assertIn('--sponsorblock-remove', args)

    def test_playlist_template(self):
        args = opt.build_args(make(playlist_subfolder=True, playlist_numbering=True))
        tpl = args[args.index('-o') + 1]
        self.assertTrue(tpl.startswith('%(playlist_title&{}/|)s%(playlist_index&{} - |)s'))
        args = opt.build_args(make(no_playlist=True))
        self.assertEqual(args[args.index('-o') + 1], DEFAULT_OPTIONS['filename_template'])

    def test_extra_args_and_errors(self):
        args = opt.build_args(make(extra_args='--no-mtime --match-filter "duration < 600"'))
        self.assertEqual(args[-3:], ['--no-mtime', '--match-filter', 'duration < 600'])
        with self.assertRaises(ValueError):
            parse_args(opt.build_args(make(extra_args='--definitely-not-an-option')))

    def test_network(self):
        args = opt.build_args(make(cookies_browser='firefox', proxy='socks5://127.0.0.1:1080', rate_limit='5M'))
        params = parse_args(args).ydl_opts
        self.assertEqual(params['cookiesfrombrowser'][0], 'firefox')
        self.assertEqual(params['proxy'], 'socks5://127.0.0.1:1080')
        self.assertEqual(params['ratelimit'], 5 * 1024 * 1024)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = App(storage=Storage(Path(cls.tmp.name)))
        cls.server = serve(cls.app)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None, token=True, host=None):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}',
                                     data=None if body is None else json.dumps(body).encode(),
                                     method='GET' if body is None else 'POST')
        if token:
            req.add_header('X-Token', self.app.token)
        if host:
            req.add_header('Host', host)
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.read()

    def test_index_has_token(self):
        status, data = self.call('/', token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.app.token.encode(), data)

    def test_api_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.call('/api/state', token=False)
        self.assertEqual(ctx.exception.code, 403)

    def test_rejects_foreign_host(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.call('/', host='evil.example')
        self.assertEqual(ctx.exception.code, 403)

    def test_state_and_settings(self):
        _, data = self.call('/api/state')
        state = json.loads(data)
        self.assertIn('version', state)
        _, data = self.call('/api/settings', {'options': {'quality': '720', 'bogus': 1}, 'app': {'max_concurrent': 3}})
        saved = json.loads(data)
        self.assertEqual(saved['options']['quality'], '720')
        self.assertNotIn('bogus', saved['options'])
        self.assertEqual(self.app.manager.max_concurrent, 3)

    def test_command_preview(self):
        _, data = self.call('/api/command', {'options': {'mode': 'audio'}, 'urls': ['https://x.y/z']})
        result = json.loads(data)
        self.assertIn('-x', result['args'])
        self.assertTrue(result['command'].startswith('yt-dlp '))
        self.assertIsNone(result['error'])

    def test_download_bad_args_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.call('/api/download', {'items': [{'url': 'https://x.y/z'}], 'options': {'extra_args': '--nope'}})
        self.assertEqual(ctx.exception.code, 400)

    def test_open_unknown_path_forbidden(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.call('/api/open', {'path': '/etc'})
        self.assertEqual(ctx.exception.code, 403)

    def test_playlist_entry_split_keeps_folder(self):
        args = self.app.item_args(make(output_dir='/dl'), {
            'url': 'u', 'playlist_title': 'My: List', 'playlist_index': 7, 'playlist_count': 120})
        self.assertIn('--no-playlist', args)
        out_dir = args[args.index('-P') + 1]
        self.assertTrue(out_dir.startswith('/dl'))
        self.assertIn('List', out_dir)
        self.assertTrue(args[args.index('-o') + 1].startswith('007 - '))


if __name__ == '__main__':
    unittest.main()
