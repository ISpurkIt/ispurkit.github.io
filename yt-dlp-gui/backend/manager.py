"""Download queue: runs yt-dlp jobs in worker threads and tracks their progress."""

import contextlib
import importlib.util
import io
import itertools
import optparse
import shutil
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import yt_dlp
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.utils import DownloadCancelled

from . import options as opt
from .sites import error_hint

APP_DIR = Path(__file__).resolve().parent.parent
_parse_lock = threading.Lock()

STAGES = {
    'Merger': 'Объединение видео и аудио',
    'ExtractAudio': 'Извлечение аудио',
    'EmbedThumbnail': 'Встраивание обложки',
    'FFmpegThumbnailsConvertor': 'Конвертация обложки',
    'FFmpegMetadata': 'Запись метаданных',
    'Metadata': 'Запись метаданных',
    'EmbedSubtitle': 'Встраивание субтитров',
    'FFmpegEmbedSubtitle': 'Встраивание субтитров',
    'FFmpegSubtitlesConvertor': 'Конвертация субтитров',
    'SubtitlesConvertor': 'Конвертация субтитров',
    'SponsorBlock': 'Поиск сегментов SponsorBlock',
    'ModifyChapters': 'Вырезание сегментов',
    'VideoRemuxer': 'Перепаковка контейнера',
    'VideoConvertor': 'Конвертация видео',
    'SplitChapters': 'Разделение по главам',
    'FFmpegSplitChapters': 'Разделение по главам',
    'FixupM3u8': 'Исправление контейнера',
    'FixupM4a': 'Исправление контейнера',
    'FixupStretched': 'Исправление пропорций',
    'FixupTimestamp': 'Исправление таймстемпов',
    'FixupDuration': 'Исправление длительности',
    'MoveFiles': 'Перемещение файлов',
}


def find_ffmpeg():
    """ffmpeg from ./bin next to the app wins over the one in PATH."""
    exe = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    local = APP_DIR / 'bin' / exe
    if local.is_file():
        return str(local)
    return shutil.which('ffmpeg')


def impersonate_status():
    """Whether yt-dlp can impersonate a browser (needs curl_cffi; TikTok and others rely on it)."""
    from yt_dlp import dependencies
    if not dependencies.curl_cffi:
        if importlib.util.find_spec('curl_cffi'):
            return {'state': 'restart', 'version': None, 'error': 'curl_cffi установлен — перезапустите приложение'}
        return {'state': 'missing', 'version': None, 'error': 'curl_cffi не установлен'}
    version = getattr(dependencies.curl_cffi, '__version__', None)
    try:
        from yt_dlp.networking import _curlcffi  # noqa: F401 - raises ImportError for unsupported versions
    except ImportError as e:
        return {'state': 'unsupported', 'version': version, 'error': str(e)}
    return {'state': 'ok', 'version': version, 'error': ''}


def find_deno():
    """deno is the JavaScript runtime yt-dlp needs to unlock all YouTube formats."""
    exe = 'deno.exe' if sys.platform == 'win32' else 'deno'
    local = APP_DIR / 'bin' / exe
    if local.is_file():
        return str(local)
    return shutil.which('deno')


def ffmpeg_args():
    path = find_ffmpeg()
    if path and Path(path).parent == APP_DIR / 'bin':
        return ['--ffmpeg-location', path]
    return []


def tool_args():
    """Points yt-dlp at the tools shipped in ./bin (the desktop build bundles ffmpeg and deno)."""
    args = ffmpeg_args()
    deno = find_deno()
    if deno and Path(deno).parent == APP_DIR / 'bin':
        args += ['--js-runtimes', f'deno:{deno}']
    return args


def parse_args(args):
    """Runs yt-dlp's own CLI parser. Returns ParsedOptions or raises ValueError."""
    stderr = io.StringIO()
    with _parse_lock, contextlib.redirect_stderr(stderr):
        try:
            return yt_dlp.parse_options(args)
        except optparse.OptParseError as e:
            message = str(e).strip().splitlines()
        except SystemExit:
            message = stderr.getvalue().strip().splitlines()
    text = message[-1] if message else 'Некорректные параметры yt-dlp'
    raise ValueError(text.split('error: ', 1)[-1])


class QuietLogger:
    def debug(self, msg):
        pass

    info = warning = debug

    def error(self, msg):
        pass


class TaskLogger:
    def __init__(self, task):
        self.task = task

    def debug(self, msg):
        if msg.startswith('[debug] '):
            return
        self.task.add_log(msg)

    def info(self, msg):
        self.task.add_log(msg)

    def warning(self, msg):
        self.task.add_log(f'WARNING: {msg}', level='warning')

    def error(self, msg):
        self.task.add_log(msg, level='error')
        self.task.last_error = msg.replace('ERROR: ', '', 1)


class InfoGrabber(PostProcessor):
    """Runs right after extraction, so the card gets title and thumbnail early."""

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self, info):
        self.task.on_info(info)
        return [], info


class Task:
    LOG_LIMIT = 2000

    def __init__(self, manager, url, args, meta=None):
        self.manager = manager
        self.id = uuid.uuid4().hex[:12]
        self.url = url
        self.args = args
        meta = meta or {}
        self.title = meta.get('title') or url
        self.thumbnail = meta.get('thumbnail') or ''
        self.uploader = meta.get('uploader') or ''
        self.duration = meta.get('duration')
        self.kind = meta.get('kind') or 'video'
        self.status = 'queued'
        self.stage = 'В очереди'
        self.progress = 0.0
        self.downloaded = 0
        self.total = 0
        self.speed = 0
        self.eta = None
        self.stream = ''
        self.playlist_index = None
        self.playlist_count = None
        self.files = []
        self.last_error = ''
        self.hint = ''
        self.created = time.time()
        self.started = None
        self.finished = None
        self.log = []
        self.cancel_reason = None
        self._last_emit = 0

    # --- state -----------------------------------------------------------

    def add_log(self, msg, level='info'):
        for line in str(msg).splitlines() or ['']:
            self.log.append({'t': time.time(), 'level': level, 'msg': line})
        if len(self.log) > self.LOG_LIMIT:
            del self.log[:len(self.log) - self.LOG_LIMIT]
        self.manager.touch(throttle=True)

    def on_info(self, info):
        if info.get('title'):
            self.title = info['title']
        thumb = info.get('thumbnail')
        if not thumb and info.get('thumbnails'):
            thumb = info['thumbnails'][-1].get('url')
        if thumb:
            self.thumbnail = thumb
        self.uploader = info.get('uploader') or info.get('channel') or self.uploader
        self.duration = info.get('duration') or self.duration
        if info.get('playlist_index'):
            self.playlist_index = info.get('playlist_index')
            self.playlist_count = info.get('n_entries') or info.get('playlist_count')
        self.stage = 'Подготовка'
        self.manager.touch()

    def progress_hook(self, d):
        if self.cancel_reason:
            raise DownloadCancelled('Остановлено пользователем')
        status = d.get('status')
        info = d.get('info_dict') or {}
        if status == 'downloading':
            self.status = 'downloading'
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            done = d.get('downloaded_bytes') or 0
            self.downloaded, self.total = done, total
            if total:
                self.progress = min(100.0, done * 100 / total)
            elif d.get('fragment_count'):
                self.progress = min(100.0, (d.get('fragment_index') or 0) * 100 / d['fragment_count'])
            self.speed = d.get('speed') or 0
            self.eta = d.get('eta')
            vcodec, acodec = info.get('vcodec'), info.get('acodec')
            if vcodec == 'none':
                self.stream = 'аудио'
            elif acodec == 'none':
                self.stream = 'видео'
            else:
                self.stream = ''
            self.stage = 'Загрузка' + (f' · {self.stream}' if self.stream else '')
            now = time.time()
            if now - self._last_emit > 0.25:
                self._last_emit = now
                self.manager.touch()
        elif status == 'finished':
            self.progress = 100.0
            self.speed = 0
            self.eta = None
            self.stage = 'Загружено, обработка…'
            self.manager.touch()

    def pp_hook(self, d):
        if self.cancel_reason:
            raise DownloadCancelled('Остановлено пользователем')
        name = d.get('postprocessor') or ''
        if d.get('status') == 'started' and name not in {'InfoGrabber'}:
            self.status = 'processing'
            self.stage = STAGES.get(name, f'Обработка: {name}')
            self.speed = 0
            self.manager.touch()

    def post_hook(self, filepath):
        if filepath and filepath not in self.files:
            self.files.append(filepath)
        self.manager.touch()

    # --- running ---------------------------------------------------------

    def run(self):
        self.status = 'starting'
        self.stage = 'Получение информации'
        self.started = time.time()
        self.finished = None
        self.last_error = ''
        self.cancel_reason = None
        self.progress = 0.0
        self.add_log(f'$ {opt.to_command(self.args, [self.url])}', level='cmd')
        try:
            parsed = parse_args([*self.args, *tool_args(), self.url])
            params = dict(parsed.ydl_opts)
            params.update({
                'logger': TaskLogger(self),
                'progress_hooks': [self.progress_hook],
                'postprocessor_hooks': [self.pp_hook],
                'noprogress': True,
                'color': {'stdout': 'no_color', 'stderr': 'no_color'},
            })
            with yt_dlp.YoutubeDL(params) as ydl:
                ydl.add_post_processor(InfoGrabber(self), when='pre_process')
                ydl.add_post_hook(self.post_hook)
                retcode = ydl.download(parsed.urls)
            if retcode and not self.files:
                self.status = 'error'
                self.stage = 'Ошибка'
            else:
                self.status = 'done'
                self.stage = 'Готово' + (' (с ошибками)' if retcode else '')
                self.progress = 100.0
        except DownloadCancelled:
            self.status = 'paused' if self.cancel_reason == 'pause' else 'cancelled'
            self.stage = 'Пауза' if self.status == 'paused' else 'Отменено'
        except ValueError as e:
            self.status = 'error'
            self.stage = 'Ошибка параметров'
            self.last_error = str(e)
            self.add_log(str(e), level='error')
        except Exception as e:  # yt-dlp can raise almost anything
            if self.cancel_reason:
                self.status = 'paused' if self.cancel_reason == 'pause' else 'cancelled'
                self.stage = 'Пауза' if self.status == 'paused' else 'Отменено'
            else:
                self.status = 'error'
                self.stage = 'Ошибка'
                self.last_error = self.last_error or str(e)
                self.add_log(traceback.format_exc(), level='error')
        self.speed = 0
        self.eta = None
        self.hint = ''
        if self.status == 'error':
            errors = ' '.join(l['msg'] for l in self.log if l['level'] == 'error')
            self.hint = error_hint(f'{self.last_error} {errors}')
        self.finished = time.time()
        self.manager.on_task_finished(self)

    def to_dict(self, with_log=False):
        data = {
            'id': self.id,
            'url': self.url,
            'title': self.title,
            'thumbnail': self.thumbnail,
            'uploader': self.uploader,
            'duration': self.duration,
            'kind': self.kind,
            'status': self.status,
            'stage': self.stage,
            'progress': round(self.progress, 1),
            'downloaded': self.downloaded,
            'total': self.total,
            'speed': self.speed,
            'eta': self.eta,
            'playlist_index': self.playlist_index,
            'playlist_count': self.playlist_count,
            'files': self.files,
            'error': self.last_error,
            'hint': self.hint,
            'created': self.created,
            'started': self.started,
            'finished': self.finished,
            'command': opt.to_command(self.args, [self.url]),
        }
        if with_log:
            data['log'] = self.log
        return data


class Manager:
    def __init__(self, storage):
        self.storage = storage
        self.tasks: dict[str, Task] = {}
        self.lock = threading.RLock()
        self.changed = threading.Condition()
        self.version = itertools.count(1)
        self.current_version = 0
        self._last_throttled = 0
        self.max_concurrent = storage.load_settings()['app']['max_concurrent']
        threading.Thread(target=self._scheduler, daemon=True, name='scheduler').start()

    # --- change notification --------------------------------------------

    def touch(self, throttle=False):
        if throttle:
            now = time.time()
            if now - self._last_throttled < 0.3:
                return
            self._last_throttled = now
        with self.changed:
            self.current_version = next(self.version)
            self.changed.notify_all()

    def wait_for_change(self, version, timeout):
        with self.changed:
            self.changed.wait_for(lambda: self.current_version != version, timeout)
            return self.current_version

    # --- queue -------------------------------------------------------------

    def add(self, url, args, meta=None):
        task = Task(self, url, args, meta)
        with self.lock:
            self.tasks[task.id] = task
        self.touch()
        return task

    def snapshot(self):
        with self.lock:
            tasks = sorted(self.tasks.values(), key=lambda t: t.created)
        return [t.to_dict() for t in tasks]

    def get(self, task_id):
        with self.lock:
            return self.tasks.get(task_id)

    def running(self):
        return [t for t in self.tasks.values() if t.status in {'starting', 'downloading', 'processing'}]

    def _scheduler(self):
        while True:
            time.sleep(0.3)
            if self._start_queued():
                self.touch()

    def _start_queued(self):
        with self.lock:
            running = self.running()
            free = int(self.max_concurrent) - len(running)
            # Two tasks for the same URL (say, the video and its MP3) would write the same
            # intermediate files at the same time and break each other, so they run one after another.
            busy = {t.url for t in running}
            started = []
            for task in sorted((t for t in self.tasks.values() if t.status == 'queued'), key=lambda t: t.created):
                if len(started) >= free:
                    break
                if task.url in busy:
                    continue
                busy.add(task.url)
                task.status = 'starting'
                threading.Thread(target=task.run, daemon=True, name=f'task-{task.id}').start()
                started.append(task)
            return started

    def on_task_finished(self, task):
        if task.status in {'done', 'error'}:
            try:
                self.storage.add_history({
                    'id': task.id,
                    'url': task.url,
                    'title': task.title,
                    'thumbnail': task.thumbnail,
                    'uploader': task.uploader,
                    'duration': task.duration,
                    'kind': task.kind,
                    'status': task.status,
                    'files': task.files,
                    'error': task.last_error,
                    'finished': task.finished,
                    'args': task.args,
                })
            except OSError:
                pass
        self.touch()

    # --- actions -----------------------------------------------------------

    def cancel(self, task_id, reason='cancel'):
        task = self.get(task_id)
        if not task:
            return False
        if task.status == 'queued' and reason == 'pause':
            task.status, task.stage = 'paused', 'Пауза'
        elif task.status == 'queued' or (task.status == 'paused' and reason == 'cancel'):
            task.status, task.stage = 'cancelled', 'Отменено'
        elif task.status in {'starting', 'downloading', 'processing'}:
            task.cancel_reason = reason
            task.stage = 'Останавливается…'
        self.touch()
        return True

    def restart(self, task_id):
        task = self.get(task_id)
        if not task or task.status in {'starting', 'downloading', 'processing'}:
            return False
        task.status = 'queued'
        task.stage = 'В очереди'
        task.cancel_reason = None
        task.last_error = ''
        task.created = time.time()
        self.touch()
        return True

    def remove(self, task_id):
        task = self.get(task_id)
        if not task:
            return False
        if task.status in {'starting', 'downloading', 'processing'}:
            task.cancel_reason = 'cancel'
        with self.lock:
            self.tasks.pop(task_id, None)
        self.touch()
        return True

    def clear_finished(self):
        with self.lock:
            for task_id in [k for k, t in self.tasks.items()
                            if t.status in {'done', 'error', 'cancelled'}]:
                del self.tasks[task_id]
        self.touch()

    def pause_all(self):
        for task in list(self.tasks.values()):
            if task.status == 'queued':
                task.status, task.stage = 'paused', 'Пауза'
            elif task.status in {'starting', 'downloading', 'processing'}:
                task.cancel_reason, task.stage = 'pause', 'Останавливается…'
        self.touch()

    def resume_all(self):
        for task in list(self.tasks.values()):
            if task.status == 'paused':
                self.restart(task.id)

    def set_max_concurrent(self, value):
        self.max_concurrent = max(1, min(int(value), 10))


# --- metadata --------------------------------------------------------------

def _format_summary(f):
    if f.get('format_note') == 'storyboard' or f.get('ext') == 'mhtml':
        return None
    vcodec = f.get('vcodec') or 'none'
    acodec = f.get('acodec') or 'none'
    return {
        'id': f.get('format_id'),
        'ext': f.get('ext'),
        'width': f.get('width'),
        'height': f.get('height'),
        'fps': f.get('fps'),
        'vcodec': vcodec,
        'acodec': acodec,
        'has_video': vcodec != 'none',
        'has_audio': acodec != 'none',
        'filesize': f.get('filesize'),
        'filesize_approx': f.get('filesize_approx'),
        'tbr': f.get('tbr'),
        'abr': f.get('abr'),
        'vbr': f.get('vbr'),
        'asr': f.get('asr'),
        'channels': f.get('audio_channels'),
        'note': f.get('format_note') or '',
        'hdr': f.get('dynamic_range') if f.get('dynamic_range') not in (None, 'SDR') else '',
        'protocol': f.get('protocol'),
        'language': f.get('language'),
    }


def _thumb(info):
    if info.get('thumbnail'):
        return info['thumbnail']
    thumbs = info.get('thumbnails') or []
    return thumbs[-1].get('url') if thumbs else ''


def _sub_list(subs):
    out = []
    for lang, tracks in (subs or {}).items():
        if lang == 'live_chat':
            continue
        name = next((t.get('name') for t in tracks or [] if t.get('name')), '') or lang
        out.append({'lang': lang, 'name': name})
    return out


def summarize(info):
    is_playlist = info.get('_type') in {'playlist', 'multi_video'} or 'entries' in info
    data = {
        'id': info.get('id'),
        'title': info.get('title') or info.get('id'),
        'url': info.get('webpage_url') or info.get('original_url') or info.get('url'),
        'thumbnail': _thumb(info),
        'uploader': info.get('uploader') or info.get('channel') or info.get('playlist_uploader') or '',
        'uploader_url': info.get('uploader_url') or info.get('channel_url') or '',
        'extractor': info.get('extractor_key') or info.get('extractor') or '',
        'duration': info.get('duration'),
        'view_count': info.get('view_count'),
        'like_count': info.get('like_count'),
        'upload_date': info.get('upload_date'),
        'description': (info.get('description') or '')[:1500],
        'is_live': bool(info.get('is_live')),
        'is_playlist': is_playlist,
    }
    if is_playlist:
        entries = []
        for i, e in enumerate(info.get('entries') or [], 1):
            if not e:
                continue
            entries.append({
                'index': i,
                'id': e.get('id'),
                'title': e.get('title') or e.get('id') or f'#{i}',
                'url': e.get('webpage_url') or e.get('url'),
                'duration': e.get('duration'),
                'thumbnail': _thumb(e),
                'uploader': e.get('uploader') or e.get('channel') or '',
            })
        data['entries'] = entries
        data['count'] = info.get('playlist_count') or len(entries)
        if not data['thumbnail'] and entries:
            data['thumbnail'] = entries[0]['thumbnail']
    else:
        data['formats'] = [s for s in map(_format_summary, info.get('formats') or []) if s]
        data['subtitles'] = _sub_list(info.get('subtitles'))
        data['auto_subtitles'] = _sub_list(info.get('automatic_captions'))
        data['chapters'] = [
            {'title': c.get('title'), 'start': c.get('start_time'), 'end': c.get('end_time')}
            for c in info.get('chapters') or []
        ]
    return data


def extract_info(url, options):
    parsed = parse_args([*opt.info_args(options), *tool_args(), url])
    params = dict(parsed.ydl_opts)
    params.update({
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'noprogress': True,
        'logger': QuietLogger(),
    })
    with yt_dlp.YoutubeDL(params) as ydl:
        info = ydl.extract_info(url, download=False)
        info = ydl.sanitize_info(info)
    return summarize(info)
