"""Where the app keeps its settings and history, and how it reads/writes them."""

import copy
import json
import os
import sys
import threading
from pathlib import Path


def config_dir() -> Path:
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    path = base / 'yt-dlp-gui'
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_download_dir() -> str:
    downloads = Path.home() / 'Downloads'
    return str(downloads if downloads.is_dir() else Path.home())


DEFAULT_OPTIONS = {
    # What to download
    'mode': 'video',              # video | audio | custom
    'quality': 'best',            # best | 2160 | 1440 | 1080 | 720 | 480 | 360 | worst
    'container': 'auto',          # auto | mp4 | mkv | webm
    'vcodec': 'any',              # any | h264 | vp9 | av01
    'fps60': False,               # prefer high frame rate
    'audio_format': 'mp3',        # best | mp3 | m4a | opus | flac | wav | aac | vorbis
    'audio_quality': '0',         # 0 (best VBR) | 320K | 256K | 192K | 128K | 96K
    'custom_format': '',
    'format_sort': '',

    # Output
    'output_dir': default_download_dir(),
    'filename_template': '%(title)s [%(id)s].%(ext)s',
    'title_limit': '100',         # max characters of the title in file names, '' = no limit
    'playlist_subfolder': True,
    'playlist_numbering': True,
    'restrict_filenames': False,
    'overwrite': 'skip',          # skip | force

    # Subtitles
    'subtitles': False,
    'sub_langs': 'ru,en',
    'auto_subs': False,
    'embed_subs': True,
    'sub_format': 'srt',          # original | srt | vtt | ass

    # Post-processing / metadata
    'embed_thumbnail': True,
    'write_thumbnail': False,
    'embed_metadata': True,
    'embed_chapters': True,
    'split_chapters': False,
    'write_description': False,
    'write_info_json': False,

    # SponsorBlock
    'sponsorblock': 'off',        # off | mark | remove
    'sponsorblock_categories': ['sponsor', 'selfpromo', 'interaction'],

    # Playlist
    'no_playlist': False,
    'playlist_items': '',
    'playlist_reverse': False,
    'playlist_random': False,

    # Section of the video
    'section_start': '',
    'section_end': '',

    # Network & auth
    'cookies_browser': '',
    'cookies_file': '',
    'proxy': '',
    'rate_limit': '',
    'retries': '10',
    'concurrent_fragments': '4',
    'geo_bypass_country': '',
    'impersonate': '',

    # Site-specific
    'tiktok_h264': True,          # prefer H.264 over HEVC on TikTok

    # Misc
    'use_archive': False,
    'use_config': False,
    'keep_video': False,
    'extra_args': '',
}

DEFAULT_APP = {
    'max_concurrent': 2,
    'theme': 'dark',
    'accent': 'sunset',
    'notify': True,
    'clipboard_watch': False,
    'ui_mode': 'auto',            # auto | window | browser — how main.py opens the interface
    'window_geometry': None,      # desktop app: last window size/position {width, height, x, y}
}


class JsonStore:
    def __init__(self, path: Path, default):
        self.path = path
        self.default = default
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            try:
                return json.loads(self.path.read_text('utf-8'))
            except (OSError, ValueError):
                return copy.deepcopy(self.default)

    def save(self, data):
        with self.lock:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
            os.replace(tmp, self.path)


class Storage:
    HISTORY_LIMIT = 300

    def __init__(self, root: Path | None = None):
        root = root or config_dir()
        self.root = root
        self._settings = JsonStore(root / 'settings.json', {})
        self._history = JsonStore(root / 'history.json', [])
        self.archive_file = str(root / 'archive.txt')

    def load_settings(self):
        raw = self._settings.load()
        options = {**copy.deepcopy(DEFAULT_OPTIONS), **raw.get('options', {})}
        app = {**DEFAULT_APP, **raw.get('app', {})}
        return {'options': options, 'app': app}

    def save_settings(self, settings):
        current = self.load_settings()
        options = {k: v for k, v in settings.get('options', {}).items() if k in DEFAULT_OPTIONS}
        app = {k: v for k, v in settings.get('app', {}).items() if k in DEFAULT_APP}
        current['options'].update(options)
        current['app'].update(app)
        self._settings.save(current)
        return current

    def load_history(self):
        data = self._history.load()
        return data if isinstance(data, list) else []

    def add_history(self, entry):
        history = [h for h in self.load_history() if h.get('id') != entry.get('id')]
        history.insert(0, entry)
        self._history.save(history[:self.HISTORY_LIMIT])

    def remove_history(self, entry_id):
        self._history.save([h for h in self.load_history() if h.get('id') != entry_id])

    def clear_history(self):
        self._history.save([])
