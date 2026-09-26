"""Local HTTP server: serves the web UI and a small JSON API around the manager."""

import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.utils import sanitize_filename

from . import options as opt
from .manager import APP_DIR, Manager, extract_info, find_ffmpeg, parse_args
from .storage import DEFAULT_OPTIONS, Storage

WEB_DIR = APP_DIR / 'web'


class App:
    def __init__(self, storage=None, token=None):
        self.storage = storage or Storage()
        self.manager = Manager(self.storage)
        self.token = token or secrets.token_urlsafe(24)
        self.update_state = {'running': False, 'output': '', 'ok': None}
        self.restart_requested = threading.Event()

    # --- helpers -----------------------------------------------------------

    def options_from(self, body):
        saved = self.storage.load_settings()['options']
        return {**saved, **(body.get('options') or {})}

    def item_args(self, options, item):
        """Per-item args; entries of a playlist split into separate tasks keep folder/numbering."""
        options = dict(options)
        playlist_title = item.get('playlist_title')
        if playlist_title:
            if options.get('playlist_subfolder'):
                folder = sanitize_filename(playlist_title, restricted=bool(options.get('restrict_filenames')))
                options['output_dir'] = str(Path(os.path.expanduser(options.get('output_dir') or '.')) / folder)
            if options.get('playlist_numbering') and item.get('playlist_index'):
                width = max(2, len(str(item.get('playlist_count') or 0)))
                options['filename_template'] = (
                    f"{int(item['playlist_index']):0{width}d} - "
                    + (options.get('filename_template') or DEFAULT_OPTIONS['filename_template']))
            options['playlist_subfolder'] = False
            options['playlist_numbering'] = False
            options['no_playlist'] = True
            options['playlist_items'] = ''
        return opt.build_args(options, self.storage.archive_file)

    def known_paths(self):
        settings = self.storage.load_settings()
        paths = {os.path.expanduser(settings['options'].get('output_dir') or '')}
        for task in self.manager.snapshot():
            paths.update(task['files'])
        for entry in self.storage.load_history():
            paths.update(entry.get('files') or [])
        return {os.path.normcase(os.path.abspath(p)) for p in paths if p}

    def open_path(self, path, reveal=False):
        path = os.path.abspath(os.path.expanduser(path))
        normalized = os.path.normcase(path)
        known = self.known_paths()
        allowed = normalized in known or any(
            normalized == os.path.normcase(os.path.dirname(p)) for p in known)
        if not allowed:
            raise PermissionError('Этот путь не относится к загрузкам')
        if not os.path.exists(path):
            raise FileNotFoundError('Файл не найден — возможно, он был перемещён или удалён')
        if sys.platform == 'win32':
            if reveal and os.path.isfile(path):
                subprocess.Popen(['explorer', '/select,', path])
            else:
                os.startfile(path)  # noqa: S606 - opening a user's own download
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', path] if reveal else ['open', path])
        else:
            target = os.path.dirname(path) if reveal and os.path.isfile(path) else path
            subprocess.Popen(['xdg-open', target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def pick(self, kind, initial):
        """Native file/folder dialog via tkinter in a child process (keeps GUI toolkits off our threads)."""
        initial = os.path.expanduser(initial or '') or str(Path.home())
        if kind == 'file':
            call = 'fd.askopenfilename(initialdir=%r, title="Выберите файл")' % initial
        else:
            call = 'fd.askdirectory(initialdir=%r, title="Выберите папку", mustexist=True)' % initial
        code = ('import tkinter as tk, tkinter.filedialog as fd\n'
                'r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)\n'
                f'p = {call}\n'
                'import sys; sys.stdout.buffer.write((p or "").encode("utf-8"))')
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError('Системный диалог недоступен (нет tkinter). Введите путь вручную.')
        return result.stdout.decode('utf-8').strip()

    def run_update(self):
        self.update_state = {'running': True, 'output': '', 'ok': None}
        self.manager.touch()
        cmd = [sys.executable, '-m', 'pip', 'install', '-U', '--disable-pip-version-check', 'yt-dlp[default]']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            output = (result.stdout + '\n' + result.stderr).strip()
            ok = result.returncode == 0
        except Exception as e:
            output, ok = str(e), False
        self.update_state = {'running': False, 'output': output[-4000:], 'ok': ok}
        self.manager.touch()

    def state(self):
        settings = self.storage.load_settings()
        return {
            'version': yt_dlp.version.__version__,
            'python': sys.version.split()[0],
            'platform': sys.platform,
            'ffmpeg': find_ffmpeg(),
            'settings': settings,
            'defaults': DEFAULT_OPTIONS,
            'tasks': self.manager.snapshot(),
            'history': self.storage.load_history(),
            'update': self.update_state,
            'config_dir': str(self.storage.root),
        }

    # --- API ---------------------------------------------------------------

    def api(self, method, path, body):
        parts = [p for p in path.split('/') if p][1:]  # drop "api"
        route = '/'.join(parts)

        if method == 'GET' and route == 'state':
            return self.state()

        if method == 'POST' and route == 'settings':
            saved = self.storage.save_settings(body)
            self.manager.set_max_concurrent(saved['app']['max_concurrent'])
            self.manager.touch()
            return saved

        if method == 'POST' and route == 'settings/reset':
            saved = self.storage.save_settings({'options': DEFAULT_OPTIONS})
            return saved

        if method == 'POST' and route == 'command':
            options = self.options_from(body)
            args = opt.build_args(options, self.storage.archive_file)
            urls = [u for u in body.get('urls') or [] if u] or ['URL']
            error = None
            try:
                parse_args([*args, 'https://example.com'])
            except ValueError as e:
                error = str(e)
            return {'args': args, 'command': opt.to_command(args, urls), 'error': error}

        if method == 'POST' and route == 'info':
            url = (body.get('url') or '').strip()
            if not url:
                raise ValueError('Укажите ссылку')
            return extract_info(url, self.options_from(body))

        if method == 'POST' and route == 'download':
            options = self.options_from(body)
            items = body.get('items') or []
            if not items:
                raise ValueError('Нет ссылок для загрузки')
            created = []
            for item in items:
                url = (item.get('url') or '').strip()
                if not url:
                    continue
                args = self.item_args(options, item)
                parse_args([*args, url])  # fail fast on bad extra args
                meta = dict(item.get('meta') or {})
                meta.setdefault('kind', 'audio' if options.get('mode') == 'audio' else 'video')
                created.append(self.manager.add(url, args, meta).id)
            return {'created': created}

        if len(parts) == 3 and parts[0] == 'tasks' and method == 'POST':
            task_id, action = parts[1], parts[2]
            ok = {
                'cancel': lambda: self.manager.cancel(task_id, 'cancel'),
                'pause': lambda: self.manager.cancel(task_id, 'pause'),
                'resume': lambda: self.manager.restart(task_id),
                'retry': lambda: self.manager.restart(task_id),
                'remove': lambda: self.manager.remove(task_id),
            }.get(action, lambda: False)()
            return {'ok': ok}

        if method == 'GET' and len(parts) == 3 and parts[0] == 'tasks' and parts[2] == 'log':
            task = self.manager.get(parts[1])
            if not task:
                raise LookupError('Задача не найдена')
            return task.to_dict(with_log=True)

        if method == 'POST' and route == 'queue/clear':
            self.manager.clear_finished()
            return {'ok': True}
        if method == 'POST' and route == 'queue/pause':
            self.manager.pause_all()
            return {'ok': True}
        if method == 'POST' and route == 'queue/resume':
            self.manager.resume_all()
            return {'ok': True}

        if method == 'POST' and route == 'history/clear':
            self.storage.clear_history()
            self.manager.touch()
            return {'ok': True}
        if method == 'POST' and route == 'history/remove':
            self.storage.remove_history(body.get('id'))
            self.manager.touch()
            return {'ok': True}

        if method == 'POST' and route == 'open':
            self.open_path(body.get('path') or '', reveal=bool(body.get('reveal')))
            return {'ok': True}

        if method == 'POST' and route == 'pick':
            return {'path': self.pick(body.get('kind'), body.get('initial'))}

        if method == 'POST' and route == 'update':
            if not self.update_state['running']:
                threading.Thread(target=self.run_update, daemon=True).start()
            return {'ok': True}

        if method == 'POST' and route == 'restart':
            if self.manager.running():
                raise ValueError('Дождитесь окончания активных загрузок')
            self.restart_requested.set()
            return {'ok': True}

        raise LookupError('Неизвестный запрос')


def make_handler(app: App, port: int):
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}

    class Handler(BaseHTTPRequestHandler):
        server_version = 'yt-dlp-gui'
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, payload, content_type='application/json; charset=utf-8', extra=None):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            # Blocks DNS-rebinding: only our own loopback origin may talk to us.
            return self.headers.get('Host', '') in allowed_hosts

        def _token_ok(self, query):
            token = self.headers.get('X-Token') or (query.get('token') or [''])[0]
            return secrets.compare_digest(token, app.token)

        def do_GET(self):
            self._handle('GET')

        def do_POST(self):
            self._handle('POST')

        def _handle(self, method):
            if not self._host_ok():
                return self._send(403, {'error': 'forbidden host'})
            url = urlparse(self.path)
            query = parse_qs(url.query)

            if not url.path.startswith('/api/'):
                if method != 'GET':
                    return self._send(405, {'error': 'method not allowed'})
                return self._static(url.path)

            if not self._token_ok(query):
                return self._send(403, {'error': 'bad token'})

            if url.path == '/api/events':
                return self._events()

            body = {}
            if method == 'POST':
                length = int(self.headers.get('Content-Length') or 0)
                if length:
                    try:
                        body = json.loads(self.rfile.read(length) or b'{}')
                    except ValueError:
                        return self._send(400, {'error': 'bad json'})
            try:
                return self._send(200, app.api(method, url.path, body))
            except LookupError as e:
                return self._send(404, {'error': str(e)})
            except PermissionError as e:
                return self._send(403, {'error': str(e)})
            except Exception as e:
                message = str(e).replace('ERROR: ', '', 1) or e.__class__.__name__
                return self._send(400, {'error': message})

        def _static(self, path):
            if path in ('', '/'):
                path = '/index.html'
            file = (WEB_DIR / path.lstrip('/')).resolve()
            if WEB_DIR.resolve() not in file.parents or not file.is_file():
                return self._send(404, b'not found', 'text/plain')
            data = file.read_bytes()
            if file.name == 'index.html':
                data = data.replace(b'__TOKEN__', app.token.encode())
            ctype = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype in ('application/javascript', 'image/svg+xml'):
                ctype += '; charset=utf-8'
            self._send(200, data, ctype, {
                'Content-Security-Policy': "default-src 'self'; img-src * data: blob:; "
                                           "style-src 'self' 'unsafe-inline'; connect-src 'self'",
                'Referrer-Policy': 'no-referrer',
            })

        def _events(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            self.close_connection = True
            version = -1
            try:
                while not app.restart_requested.is_set():
                    new_version = app.manager.wait_for_change(version, 15)
                    if new_version == version:
                        self.wfile.write(b': ping\n\n')
                    else:
                        version = new_version
                        payload = {
                            'tasks': app.manager.snapshot(),
                            'update': app.update_state,
                            'history_count': len(app.storage.load_history()),
                        }
                        self.wfile.write(b'data: ' + json.dumps(payload, ensure_ascii=False).encode() + b'\n\n')
                    self.wfile.flush()
                    time.sleep(0.15)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass

    return Handler


def serve(app: App, host='127.0.0.1', port=0):
    server = ThreadingHTTPServer((host, port), None)
    server.daemon_threads = True
    server.RequestHandlerClass = make_handler(app, server.server_address[1])
    return server
