"""YT-DLP Studio — desktop application.

This is the entry point of the Windows build (PyInstaller, no console) and can also be run from
source: `python desktop.py` (or `pythonw desktop.py` on Windows to hide the console).

Compared with main.py it always uses a native window, allows only one running copy, writes a log
file instead of printing to a console, asks before closing while downloads are running and, in the
packaged build, updates yt-dlp from PyPI into the user's folder (there is no pip inside an .exe).
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

FROZEN = getattr(sys, 'frozen', False)
if not FROZEN:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import runtime  # noqa: E402  (must not import yt_dlp: runtime.activate() has to run first)
from backend.storage import config_dir  # noqa: E402
from backend.version import APP_VERSION  # noqa: E402

APP_NAME = 'YT-DLP Studio'
WEBVIEW2_URL = 'https://developer.microsoft.com/microsoft-edge/webview2/'
ACTIVE = {'queued', 'starting', 'downloading', 'processing'}
log = logging.getLogger('desktop')


# --- process plumbing ---------------------------------------------------------

class _LogStream:
    """Replaces stdout/stderr in the windowed build, where they are None."""

    def __init__(self, level):
        self.level = level

    def write(self, text):
        for line in text.rstrip().splitlines():
            logging.getLogger('stdio').log(self.level, line)

    def flush(self):
        pass

    def isatty(self):
        return False


def setup_logging(root):
    log_dir = root / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / 'app.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    if FROZEN or sys.stdout is None:
        sys.stdout, sys.stderr = _LogStream(logging.INFO), _LogStream(logging.ERROR)
    sys.excepthook = lambda *exc: logging.critical('unhandled exception', exc_info=exc)
    threading.excepthook = lambda a: logging.error(
        'thread %s crashed', a.thread.name if a.thread else '?', exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return log_dir


def message_box(text, error=True):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
    else:
        print(text, file=sys.__stderr__ or sys.stderr)


def open_folder(path):
    if sys.platform == 'win32':
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])


def _local_request(port, token, path, body=None, timeout=2):
    # never route loopback calls through a system proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f'http://127.0.0.1:{port}{path}', data=None if body is None else json.dumps(body).encode(),
        headers={'X-Token': token, 'Content-Type': 'application/json'}, method='GET' if body is None else 'POST')
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read() or b'{}')


def bring_running_copy_to_front(instance_file):
    """If another copy is already running, show its window and return True."""
    try:
        info = json.loads(instance_file.read_text('utf-8'))
        _local_request(info['port'], info['token'], '/api/desktop/show', {})
        return True
    except Exception:
        return False


def relaunch():
    os.environ['YTDLP_GUI_RESTARTED'] = '1'
    args = [sys.executable, *([] if FROZEN else [os.path.abspath(__file__)]), *sys.argv[1:]]
    subprocess.Popen(args, close_fds=True)
    os._exit(0)


# --- window ---------------------------------------------------------------------

def _system_uses_dark_theme():
    if sys.platform != 'win32':
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except OSError:
        return True


class DesktopHost:
    """What the server can ask of the desktop shell (see App.desktop)."""

    frozen = FROZEN

    def __init__(self, app, log_dir, yt_dlp_updated):
        self.app = app
        self.log_dir = log_dir
        self.yt_dlp_updated = yt_dlp_updated
        self.window = None
        self.hwnd = None
        self.allow_close = False
        self.quit_event = threading.Event()

    def describe(self):
        return {
            'version': APP_VERSION,
            'frozen': FROZEN,
            'window': self.window is not None,
            'log_dir': str(self.log_dir),
            'yt_dlp_updated': bool(self.yt_dlp_updated),
        }

    def has_window(self):
        return self.window is not None

    def pick(self, kind, initial):
        import webview
        dialog = webview.FileDialog.OPEN if kind == 'file' else webview.FileDialog.FOLDER
        result = self.window.create_file_dialog(dialog, directory=initial)
        if not result:
            return ''
        return result if isinstance(result, str) else result[0]

    def show(self):
        if not self.window:
            webbrowser.open(self.app_url)
            return
        try:
            self.window.restore()
            self.window.show()
            self.window.on_top = True   # the usual trick to raise a window above the others
            self.window.on_top = False
        except Exception:
            log.exception('could not bring the window to front')

    def quit(self):
        self.allow_close = True
        if self.window:
            self.window.destroy()
        self.quit_event.set()

    def open_logs(self):
        open_folder(self.log_dir)

    def apply_theme(self, theme):
        """Dark or light Windows title bar to match the app theme."""
        if sys.platform != 'win32' or not self.hwnd:
            return
        dark = _system_uses_dark_theme() if theme == 'system' else theme != 'light'
        try:
            import ctypes
            value = ctypes.c_int(1 if dark else 0)
            for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 11 / older Windows 10)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        self.hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            log.exception('could not set the title bar theme')

    # --- window events ---

    def on_shown(self):
        try:
            self.hwnd = int(self.window.native.Handle.ToInt64())
        except Exception:
            self.hwnd = None
        self.apply_theme(self.app.storage.load_settings()['app'].get('theme', 'dark'))

    def on_closing(self):
        if self.allow_close:
            return True
        active = [t for t in self.app.manager.snapshot() if t['status'] in ACTIVE]
        if not active:
            self.save_geometry()
            return True
        # this runs on the UI thread, so the dialog has to come from another one
        threading.Thread(target=self._confirm_close, args=(len(active),), daemon=True).start()
        return False

    def _confirm_close(self, count):
        if self.window.create_confirmation_dialog(
                APP_NAME, f'Ещё не закончены загрузки: {count}. Закрыть приложение?\n\n'
                          'Недокачанные файлы можно будет продолжить позже — просто добавьте ссылку снова.'):
            self.save_geometry()
            self.allow_close = True
            self.window.destroy()

    def save_geometry(self):
        try:
            w = self.window
            geometry = {'width': int(w.width), 'height': int(w.height), 'x': int(w.x), 'y': int(w.y)}
            if geometry['width'] >= 640 and geometry['height'] >= 480:
                self.app.storage.save_settings({'app': {'window_geometry': geometry}})
        except Exception:
            log.exception('could not save the window geometry')


def window_geometry(saved):
    geometry = {'width': 1360, 'height': 880, 'x': None, 'y': None}
    if isinstance(saved, dict):
        geometry.update({k: saved.get(k) for k in geometry if isinstance(saved.get(k), int)})
    try:
        import webview
        screens = webview.screens
        on_screen = any(
            s.x - 50 <= (geometry['x'] or 0) < s.x + s.width - 100 and s.y - 50 <= (geometry['y'] or 0) < s.y + s.height - 100
            for s in screens)
        if geometry['x'] is not None and not on_screen:  # the monitor it was on is gone
            geometry['x'] = geometry['y'] = None
    except Exception:
        pass
    return geometry


def run_window(host, url, root):
    import webview

    geometry = window_geometry(host.app.storage.load_settings()['app'].get('window_geometry'))
    window = webview.create_window(
        APP_NAME, url, width=geometry['width'], height=geometry['height'], x=geometry['x'], y=geometry['y'],
        min_size=(980, 640), background_color='#09090f', text_select=True)
    host.window = window
    window.events.closing += host.on_closing
    window.events.shown += host.on_shown
    webview.start(
        # never fall back to the legacy Internet Explorer engine: it cannot run the interface
        gui='edgechromium' if sys.platform == 'win32' else None,
        private_mode=False,
        storage_path=str(root / 'webview'),
    )


# --- self-test (used by the CI build) --------------------------------------------

def self_test(app, port, out):
    report, ok = {}, True
    try:
        state = _local_request(port, app.token, '/api/state', timeout=30)
        report.update({k: state[k] for k in ('version', 'ffmpeg', 'deno', 'impersonate', 'desktop')})
        ok &= bool(state['ffmpeg']) and bool(state['deno']) and state['impersonate']['state'] == 'ok'
        for tool in ('ffmpeg', 'deno'):
            result = subprocess.run([state[tool], '-version' if tool == 'ffmpeg' else '--version'],
                                    capture_output=True, text=True, timeout=60)
            report[f'{tool}_run'] = (result.stdout or result.stderr).splitlines()[0] if result.returncode == 0 else 'FAILED'
            ok &= result.returncode == 0
        import webview  # noqa: F401
        if sys.platform == 'win32':
            from webview.platforms import winforms  # noqa: F401  (pythonnet + WebView2 bindings are bundled)
        report['webview'] = 'ok'
        command = _local_request(port, app.token, '/api/command', {'options': {}, 'urls': ['https://youtu.be/x']})
        report['command_ok'] = command['error'] is None
        ok &= report['command_ok']
    except Exception as e:
        log.exception('self-test failed')
        report['exception'] = f'{e.__class__.__name__}: {e}'
        ok = False
    report['ok'] = ok
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    return 0 if ok else 1


# --- main -------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument('--self-test', metavar='REPORT.json', help='проверить сборку и выйти')
    args, _ = parser.parse_known_args()

    root = config_dir()
    log_dir = setup_logging(root)
    log.info('%s %s starting (frozen=%s, python %s)', APP_NAME, APP_VERSION, FROZEN, sys.version.split()[0])
    instance_file = root / 'instance.json'
    restarted = os.environ.pop('YTDLP_GUI_RESTARTED', None)
    if not restarted and not args.self_test and bring_running_copy_to_front(instance_file):
        log.info('another copy is running — brought it to front')
        return 0

    updated = runtime.activate(root)
    from backend.server import App, serve  # imports yt_dlp — after activate()

    app = App()
    host = DesktopHost(app, log_dir, updated)
    app.desktop = host
    app.ui_mode = 'window'
    server = serve(app)
    port = server.server_address[1]
    host.app_url = url = f'http://127.0.0.1:{port}/'
    threading.Thread(target=server.serve_forever, daemon=True, name='http').start()
    log.info('serving %s', url)

    if args.self_test:
        code = self_test(app, port, args.self_test)
        server.shutdown()
        return code

    instance_file.write_text(json.dumps({'port': port, 'token': app.token, 'pid': os.getpid()}), 'utf-8')

    def cleanup():
        try:
            if json.loads(instance_file.read_text('utf-8')).get('pid') == os.getpid():
                instance_file.unlink()
        except (OSError, ValueError):
            pass

    def watch_restart():
        app.restart_requested.wait()
        log.info('restarting')
        cleanup()
        server.shutdown()
        server.server_close()
        relaunch()

    threading.Thread(target=watch_restart, daemon=True, name='restart').start()

    try:
        run_window(host, url, root)
    except Exception as e:
        log.exception('the window could not be opened')
        host.window = None
        app.ui_mode = 'browser'
        app.ui_error = f'{e.__class__.__name__}: {e}'
        message_box(
            'Не удалось открыть окно приложения.\n\n'
            'Скорее всего, в системе нет компонента Microsoft Edge WebView2 '
            f'(его можно скачать здесь: {WEBVIEW2_URL}).\n\n'
            'Сейчас YT-DLP Studio откроется в браузере. Чтобы завершить приложение, '
            'нажмите «Выход» в разделе Настройки.')
        webbrowser.open(url)
        host.quit_event.wait()
    finally:
        cleanup()
        log.info('stopped')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        logging.critical('fatal error', exc_info=True)
        message_box(f'YT-DLP Studio не смог запуститься:\n\n{e}\n\nПодробности — в журнале:\n'
                    f'{config_dir() / "logs" / "app.log"}')
        sys.exit(1)
