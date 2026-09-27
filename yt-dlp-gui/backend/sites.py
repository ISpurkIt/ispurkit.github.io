"""Site-specific tweaks: URL clean-up, per-site defaults and human-readable error hints."""

import re
from urllib.parse import urlsplit

_TIKTOK_HOST = re.compile(r'^(?:www\.|m\.)?tiktok\.com$', re.I)
_TIKTOK_POST = re.compile(r'^/@(?P<user>[\w.-]*)/(?:video|photo)/(?P<id>\d+)')
_TIKTOK_MOBILE = re.compile(r'^/v/(?P<id>\d+)(?:\.html)?')


def site_of(url):
    host = (urlsplit(url).hostname or '').lower()
    if host == 'tiktok.com' or host.endswith('.tiktok.com') or host.endswith('.tiktokv.com'):
        return 'tiktok'
    return None


def normalize_url(url):
    """Rewrites URL forms that yt-dlp's extractors don't recognise into ones they do."""
    url = (url or '').strip()
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()

    if _TIKTOK_HOST.match(host):
        # tiktok.com / m.tiktok.com / photo posts only match the generic extractor otherwise
        post = _TIKTOK_POST.match(parts.path)
        if post:
            return f'https://www.tiktok.com/@{post["user"]}/video/{post["id"]}'
        mobile = _TIKTOK_MOBILE.match(parts.path)
        if mobile:
            return f'https://www.tiktok.com/@/video/{mobile["id"]}'
        if host != 'www.tiktok.com' and parts.path.startswith('/@'):
            return f'https://www.tiktok.com{parts.path}'
    return url


def site_options(url, options):
    """Per-site adjustments of the GUI options for one URL."""
    if site_of(url) == 'tiktok':
        options = dict(options)
        # TikTok's best streams are often HEVC, which the stock Windows player can't open
        if options.get('tiktok_h264') and options.get('mode') == 'video' and options.get('vcodec') == 'any':
            options['vcodec'] = 'h264'
    return options


# (pattern, hint) — the first match wins
_HINTS = [
    (r'impersonat|Unable to extract universal data|Unable to extract challenge|Unexpected response from webpage',
     'Сайт блокирует запросы без имитации браузера. Установите поддержку TikTok/имитации браузера '
     'в Настройках (кнопка «Установить curl_cffi») и перезапустите приложение.'),
    (r'IP address is blocked',
     'Сайт заблокировал ваш IP-адрес. Попробуйте прокси или VPN (Сеть и авторизация → Прокси).'),
    (r'requiring login|Log into an account|log in for access|You do not have permission|private',
     'Нужен вход в аккаунт. Выберите браузер, в котором вы авторизованы: Сеть и авторизация → Cookies из браузера.'),
    (r'Sign in to confirm|not a bot',
     'Сайт просит подтвердить, что вы не робот. Подключите cookies из браузера (Сеть и авторизация).'),
    (r'Could not copy .*cookie database|Failed to decrypt|cookies database',
     'Не удалось прочитать cookies браузера. Закройте браузер полностью или используйте файл cookies.txt.'),
    (r'File name too long|Errno 36|Errno 22|Invalid argument',
     'Слишком длинное имя файла. Уменьшите «Макс. длину названия» в разделе Сохранение.'),
    (r'ffmpeg (?:is )?not (?:found|installed)|ffprobe',
     'Для этой операции нужен ffmpeg — инструкция в Настройках.'),
    (r'Requested format is not available',
     'Такого формата нет у этого видео. Выберите «Видео» → «Лучшее» или нажмите «Анализ» и выберите формат из таблицы.'),
    (r'Unsupported URL',
     'yt-dlp не умеет работать с этой ссылкой. Проверьте, что это ссылка на видео, а не на страницу поиска.'),
    (r'HTTP Error 429|Too Many Requests',
     'Слишком много запросов — сайт временно ограничил доступ. Подождите или используйте cookies/прокси.'),
]


def error_hint(message):
    for pattern, hint in _HINTS:
        if re.search(pattern, message or '', re.I):
            return hint
    return ''
