"""Turns the GUI options into yt-dlp command-line arguments.

The GUI never builds a params dict by hand: it produces the same argv a user
would type in the console, and yt-dlp's own parser turns it into params. That
keeps behaviour identical to the CLI and lets us show the exact command.
"""

import os
import shlex
import subprocess
import sys

QUALITY_HEIGHTS = {'2160', '1440', '1080', '720', '480', '360', '240', '144'}
CONTAINERS = {'mp4', 'mkv', 'webm', 'mov'}
AUDIO_FORMATS = {'mp3', 'm4a', 'opus', 'flac', 'wav', 'aac', 'vorbis', 'alac'}
SPONSORBLOCK_CATEGORIES = {
    'sponsor', 'intro', 'outro', 'selfpromo', 'preview', 'filler',
    'interaction', 'music_offtopic', 'hook', 'poi_highlight', 'chapter',
}


def _str(opts, key):
    value = opts.get(key)
    return str(value).strip() if value is not None else ''


def format_args(opts):
    """-f / -S / -x arguments for the chosen download mode."""
    args = []
    mode = opts.get('mode', 'video')

    if mode == 'audio':
        args += ['-f', 'ba/b', '-x']
        audio_format = _str(opts, 'audio_format')
        if audio_format in AUDIO_FORMATS:
            args += ['--audio-format', audio_format]
        quality = _str(opts, 'audio_quality')
        if quality and quality != '0' and audio_format not in {'flac', 'wav', 'alac'}:
            args += ['--audio-quality', quality]
        elif audio_format in {'mp3', 'm4a', 'aac', 'vorbis', 'opus'}:
            args += ['--audio-quality', '0']
        if opts.get('keep_video'):
            args.append('-k')
        return args

    if mode == 'custom':
        fmt = _str(opts, 'custom_format')
        if fmt:
            args += ['-f', fmt]
        sort = _str(opts, 'format_sort')
        if sort:
            args += ['-S', sort]
    else:
        quality = _str(opts, 'quality')
        if quality == 'worst':
            args += ['-f', 'wv*+wa/w']
        else:
            args += ['-f', 'bv*+ba/b']
        sort = []
        vcodec = _str(opts, 'vcodec')
        if vcodec in {'h264', 'vp9', 'av01', 'h265'}:
            sort.append(f'vcodec:{vcodec}')
        if quality in QUALITY_HEIGHTS:
            sort.append(f'res:{quality}')
        if opts.get('fps60'):
            sort.append('fps')
        container = _str(opts, 'container')
        if container == 'mp4':
            sort.append('ext:mp4:m4a')
        elif container == 'webm':
            sort.append('ext:webm:webm')
        if sort:
            args += ['-S', ','.join(sort)]

    container = _str(opts, 'container')
    if container in CONTAINERS:
        args += ['--merge-output-format', container, '--remux-video', container]
    return args


def output_args(opts):
    args = []
    output_dir = _str(opts, 'output_dir')
    if output_dir:
        args += ['-P', os.path.expanduser(output_dir)]

    template = _str(opts, 'filename_template') or '%(title)s [%(id)s].%(ext)s'
    if opts.get('playlist_numbering') and not opts.get('no_playlist'):
        template = '%(playlist_index&{} - |)s' + template
    if opts.get('playlist_subfolder') and not opts.get('no_playlist'):
        template = '%(playlist_title&{}/|)s' + template
    args += ['-o', template]

    if opts.get('restrict_filenames'):
        args.append('--restrict-filenames')
    if opts.get('overwrite') == 'force':
        args.append('--force-overwrites')
    return args


def subtitle_args(opts):
    if not opts.get('subtitles'):
        return []
    args = ['--write-subs']
    if opts.get('auto_subs'):
        args.append('--write-auto-subs')
    langs = _str(opts, 'sub_langs') or 'all'
    args += ['--sub-langs', langs]
    sub_format = _str(opts, 'sub_format')
    if sub_format in {'srt', 'vtt', 'ass'}:
        args += ['--convert-subs', sub_format]
    if opts.get('embed_subs') and opts.get('mode') != 'audio':
        args.append('--embed-subs')
    return args


def postprocess_args(opts):
    args = []
    if opts.get('embed_thumbnail'):
        args.append('--embed-thumbnail')
        if opts.get('mode') == 'audio' or opts.get('container') == 'mp4':
            args += ['--convert-thumbnails', 'jpg']
    if opts.get('write_thumbnail'):
        args.append('--write-thumbnail')
    if opts.get('embed_metadata'):
        args.append('--embed-metadata')
    if opts.get('embed_chapters') and opts.get('mode') != 'audio':
        args.append('--embed-chapters')
    if opts.get('split_chapters'):
        args.append('--split-chapters')
    if opts.get('write_description'):
        args.append('--write-description')
    if opts.get('write_info_json'):
        args.append('--write-info-json')

    sponsorblock = opts.get('sponsorblock')
    if sponsorblock in {'mark', 'remove'}:
        cats = [c for c in opts.get('sponsorblock_categories') or [] if c in SPONSORBLOCK_CATEGORIES]
        if cats:
            args += [f'--sponsorblock-{sponsorblock}', ','.join(cats)]
    return args


def playlist_args(opts):
    args = []
    if opts.get('no_playlist'):
        args.append('--no-playlist')
        return args
    items = _str(opts, 'playlist_items')
    if items:
        args += ['-I', items]
    if opts.get('playlist_reverse'):
        args.append('--playlist-reverse')
    if opts.get('playlist_random'):
        args.append('--playlist-random')
    return args


def section_args(opts):
    start, end = _str(opts, 'section_start'), _str(opts, 'section_end')
    if not start and not end:
        return []
    return ['--download-sections', f'*{start or "0"}-{end or "inf"}']


def network_args(opts):
    args = []
    if not opts.get('use_config'):
        args.append('--ignore-config')
    browser = _str(opts, 'cookies_browser')
    if browser:
        args += ['--cookies-from-browser', browser]
    cookies = _str(opts, 'cookies_file')
    if cookies:
        args += ['--cookies', os.path.expanduser(cookies)]
    proxy = _str(opts, 'proxy')
    if proxy:
        args += ['--proxy', proxy]
    country = _str(opts, 'geo_bypass_country')
    if country:
        args += ['--xff', country]
    impersonate = _str(opts, 'impersonate')
    if impersonate:
        args += ['--impersonate', impersonate]
    return args


def transfer_args(opts):
    args = []
    rate = _str(opts, 'rate_limit')
    if rate:
        args += ['-r', rate]
    retries = _str(opts, 'retries')
    if retries:
        args += ['-R', retries, '--fragment-retries', retries]
    fragments = _str(opts, 'concurrent_fragments')
    if fragments and fragments != '1':
        args += ['-N', fragments]
    return args


def extra_args(opts):
    raw = _str(opts, 'extra_args')
    if not raw:
        return []
    if sys.platform == 'win32':
        # keep Windows paths intact: posix mode would eat the backslashes
        raw = raw.replace('\\', '\\\\')
    return shlex.split(raw, posix=True)


def build_args(opts, archive_file=None):
    """Full yt-dlp argv (without the program name and the URLs)."""
    args = []
    args += network_args(opts)
    args += format_args(opts)
    args += output_args(opts)
    args += subtitle_args(opts)
    args += postprocess_args(opts)
    args += playlist_args(opts)
    args += section_args(opts)
    args += transfer_args(opts)
    if opts.get('use_archive') and archive_file:
        args += ['--download-archive', archive_file]
    args += extra_args(opts)
    return args


def info_args(opts):
    """Arguments that matter when only fetching metadata."""
    return network_args(opts) + (['--no-playlist'] if opts.get('no_playlist') else [])


def to_command(args, urls=()):
    parts = ['yt-dlp', *args, *urls]
    if sys.platform == 'win32':
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)
