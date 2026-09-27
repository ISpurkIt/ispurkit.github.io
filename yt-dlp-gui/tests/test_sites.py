import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yt_dlp.extractor import gen_extractor_classes  # noqa: E402

from backend import options as opt  # noqa: E402
from backend.sites import error_hint, normalize_url, site_of, site_options  # noqa: E402
from backend.storage import DEFAULT_OPTIONS  # noqa: E402

EXTRACTORS = list(gen_extractor_classes())


def extractor_for(url):
    return next(ie for ie in EXTRACTORS if ie.suitable(url)).ie_key()


class TikTokUrlTest(unittest.TestCase):
    def test_urls_reach_tiktok_extractors(self):
        cases = {
            'https://www.tiktok.com/@user/video/7412345678901234567?is_from_webapp=1': 'TikTok',
            'https://tiktok.com/@user/video/7412345678901234567': 'TikTok',
            'https://m.tiktok.com/@user/video/7412345678901234567': 'TikTok',
            'https://m.tiktok.com/v/7412345678901234567.html': 'TikTok',
            'https://www.tiktok.com/@user/photo/7412345678901234567': 'TikTok',
            'https://vm.tiktok.com/ZMabc123/': 'TikTokVM',
            'https://vt.tiktok.com/ZSabc123/': 'TikTokVM',
            'https://www.tiktok.com/t/ZTabc123/': 'TikTokVM',
            'https://m.tiktok.com/@user': 'TikTokUser',
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(extractor_for(normalize_url(url)), expected)

    def test_other_sites_untouched(self):
        for url in ('https://youtu.be/abc', 'https://x.com/a/status/1', ' https://vk.com/video1_2 '):
            self.assertEqual(normalize_url(url), url.strip())
            self.assertIsNone(site_of(url))

    def test_tiktok_prefers_h264(self):
        opts = {**DEFAULT_OPTIONS, 'mode': 'video', 'vcodec': 'any', 'tiktok_h264': True}
        args = opt.build_args(site_options('https://vm.tiktok.com/x/', opts))
        self.assertIn('vcodec:h264', args[args.index('-S') + 1])
        # an explicit codec choice and other sites are left alone
        self.assertEqual(site_options('https://vm.tiktok.com/x/', {**opts, 'vcodec': 'av01'})['vcodec'], 'av01')
        self.assertEqual(site_options('https://youtu.be/x', opts)['vcodec'], 'any')
        self.assertEqual(site_options('https://vm.tiktok.com/x/', {**opts, 'tiktok_h264': False})['vcodec'], 'any')

    def test_title_limit(self):
        args = opt.build_args({**DEFAULT_OPTIONS, 'title_limit': '80', 'no_playlist': True})
        self.assertEqual(args[args.index('-o') + 1], '%(title).80s [%(id)s].%(ext)s')
        args = opt.build_args({**DEFAULT_OPTIONS, 'title_limit': '', 'no_playlist': True})
        self.assertEqual(args[args.index('-o') + 1], '%(title)s [%(id)s].%(ext)s')

    def test_error_hints(self):
        self.assertIn('curl_cffi', error_hint('[TikTok] 1: Unable to extract universal data for rehydration'))
        self.assertIn('прокси', error_hint('Your IP address is blocked from accessing this post'))
        self.assertIn('Cookies', error_hint('TikTok is requiring login for access to this content'))
        self.assertEqual(error_hint('something unexpected'), '')


if __name__ == '__main__':
    unittest.main()
