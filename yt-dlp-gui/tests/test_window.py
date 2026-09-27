import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import window  # noqa: E402
from backend.server import App  # noqa: E402
from backend.storage import Storage  # noqa: E402


class ResolveModeTest(unittest.TestCase):
    def test_explicit_modes(self):
        self.assertEqual(window.resolve_mode('window'), 'window')
        self.assertEqual(window.resolve_mode('browser'), 'browser')

    def test_auto_depends_on_pywebview(self):
        with mock.patch.object(window, 'webview_available', return_value=True):
            self.assertEqual(window.resolve_mode('auto'), 'window')
            self.assertEqual(window.resolve_mode(None), 'window')
        with mock.patch.object(window, 'webview_available', return_value=False):
            self.assertEqual(window.resolve_mode('auto'), 'browser')
            self.assertEqual(window.resolve_mode('bogus'), 'browser')


class SwitchUiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(storage=Storage(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_switch_saves_mode_and_restarts(self):
        with mock.patch('backend.server.webview_available', return_value=True):
            result = self.app.api('POST', '/api/ui/switch', {'mode': 'window'})
        self.assertEqual(result, {'installing': False})
        self.assertTrue(self.app.restart_requested.is_set())
        self.assertEqual(self.app.storage.load_settings()['app']['ui_mode'], 'window')

    def test_switch_to_window_installs_pywebview_first(self):
        with mock.patch('backend.server.webview_available', return_value=False), \
                mock.patch.object(App, 'start_update') as start_update:
            result = self.app.api('POST', '/api/ui/switch', {'mode': 'window'})
        self.assertEqual(result, {'installing': True})
        self.assertFalse(self.app.restart_requested.is_set())
        kwargs = start_update.call_args.kwargs
        self.assertEqual(kwargs['label'], 'pywebview')
        self.assertTrue(kwargs['restart_after'])
        self.assertTrue(any(p.startswith('pywebview') for p in kwargs['packages']))

    def test_failed_install_does_not_restart(self):
        with mock.patch('backend.server.subprocess.run') as run:
            run.return_value = mock.Mock(returncode=1, stdout='', stderr='boom')
            self.app.run_update(packages=['pywebview'], label='pywebview', restart_after=True)
        self.assertFalse(self.app.update_state['ok'])
        self.assertFalse(self.app.restart_requested.is_set())

    def test_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            self.app.api('POST', '/api/ui/switch', {'mode': 'fullscreen'})

    def test_state_reports_window(self):
        state = self.app.state()
        self.assertEqual(state['window']['current'], 'browser')
        self.assertIn('boot_id', state)


if __name__ == '__main__':
    unittest.main()
