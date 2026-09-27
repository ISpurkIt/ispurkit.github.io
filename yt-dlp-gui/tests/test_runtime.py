import io
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import runtime  # noqa: E402

ACTIVATE = textwrap.dedent('''
    import sys
    sys.path.insert(0, {root!r})
    from backend import runtime
    print(runtime.activate({config!r}))
    import yt_dlp
    print(yt_dlp.version.__version__)
''')


def fake_runtime(config, version, broken=False):
    folder = runtime.runtime_dir(config) / f'yt-dlp-{version}'
    package = folder / 'yt_dlp'
    package.mkdir(parents=True)
    (package / 'version.py').write_text(f'__version__ = {version!r}\n')
    body = 'raise ImportError("corrupted update")\n' if broken else 'from . import version\n'
    (package / '__init__.py').write_text(body)
    (runtime.runtime_dir(config) / 'current.txt').write_text(folder.name)
    return folder


class ActivateTest(unittest.TestCase):
    # activate() has to run before anything imports yt_dlp, so each case gets a fresh interpreter

    def run_activate(self, config):
        result = subprocess.run([sys.executable, '-c', ACTIVATE.format(root=str(ROOT), config=str(config))],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.split()

    def test_updated_copy_takes_precedence(self):
        with tempfile.TemporaryDirectory() as config:
            fake_runtime(config, '2099.01.01')
            self.assertEqual(self.run_activate(config), ['2099.01.01', '2099.01.01'])

    def test_broken_update_falls_back_to_bundled(self):
        with tempfile.TemporaryDirectory() as config:
            fake_runtime(config, '2099.01.01', broken=True)
            activated, loaded = self.run_activate(config)
            self.assertEqual(activated, 'None')
            self.assertNotEqual(loaded, '2099.01.01')
            # the broken update is switched off, so the next start doesn't try it again
            self.assertFalse((runtime.runtime_dir(config) / 'current.txt').exists())

    def test_nothing_installed(self):
        with tempfile.TemporaryDirectory() as config:
            self.assertEqual(self.run_activate(config)[0], 'None')

    def test_reset(self):
        with tempfile.TemporaryDirectory() as config:
            fake_runtime(config, '2099.01.01')
            runtime.reset(config)
            runtime.reset(config)  # idempotent
            self.assertEqual(self.run_activate(config)[0], 'None')


class HelpersTest(unittest.TestCase):
    def test_versions_compare_numerically(self):
        self.assertEqual(runtime._normalize('2026.08.19'), runtime._normalize('2026.8.19'))
        self.assertLess(runtime._normalize('2026.8.19'), runtime._normalize('2026.10.1'))

    def test_ejs_pin_from_wheel_metadata(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as wheel:
            wheel.writestr('yt_dlp-2099.1.1.dist-info/METADATA',
                           'Name: yt-dlp\nRequires-Dist: yt-dlp-ejs==0.9.1; extra == "default"\n')
        self.assertEqual(runtime._ejs_pin(zipfile.ZipFile(buffer)), '0.9.1')

    def test_picks_universal_wheel(self):
        release = {'urls': [
            {'packagetype': 'sdist', 'filename': 'yt_dlp-1.tar.gz', 'url': 'sdist', 'digests': {'sha256': 'a'}},
            {'packagetype': 'bdist_wheel', 'filename': 'yt_dlp-1-py3-none-any.whl', 'url': 'wheel',
             'digests': {'sha256': 'b'}},
        ]}
        self.assertEqual(runtime._wheel(release), ('wheel', 'b'))


if __name__ == '__main__':
    unittest.main()
