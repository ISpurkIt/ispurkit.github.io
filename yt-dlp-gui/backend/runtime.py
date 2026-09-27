"""Updating yt-dlp inside the packaged desktop app, where pip is not available.

yt-dlp is pure Python, so a newer release can simply be unpacked from its wheel into the user's
config folder and put first on sys.path. The build ships yt_dlp as plain .py files (not inside
the frozen archive) exactly so that a folder on sys.path can take precedence over it.

Layout:  <config>/runtime/current.txt          name of the active folder
         <config>/runtime/yt-dlp-2026.9.1/     yt_dlp/ and yt_dlp_ejs/ from the wheels
"""

import hashlib
import io
import json
import logging
import re
import shutil
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

PYPI = 'https://pypi.org/pypi/{name}/json'
PYPI_VERSION = 'https://pypi.org/pypi/{name}/{version}/json'
_MODULES = ('yt_dlp', 'yt_dlp_ejs')


def runtime_dir(config_root):
    return Path(config_root) / 'runtime'


def _active_folder(config_root):
    root = runtime_dir(config_root)
    try:
        name = (root / 'current.txt').read_text('utf-8').strip()
    except OSError:
        return None
    folder = root / name
    return folder if name and (folder / 'yt_dlp' / '__init__.py').is_file() else None


def _purge_modules():
    for name in list(sys.modules):
        if name.split('.')[0] in _MODULES:
            del sys.modules[name]


def activate(config_root):
    """Call before anything imports yt_dlp. Returns the version loaded from the runtime folder, or None."""
    folder = _active_folder(config_root)
    if not folder:
        return None
    sys.path.insert(0, str(folder))
    try:
        import yt_dlp
        version = yt_dlp.version.__version__
        log.info('using updated yt-dlp %s from %s', version, folder)
        return version
    except Exception:
        # a broken update must never stop the app from starting: drop it and use the bundled copy
        log.exception('updated yt-dlp in %s failed to load, falling back to the bundled one', folder)
        sys.path.remove(str(folder))
        _purge_modules()
        try:
            (runtime_dir(config_root) / 'current.txt').unlink()
        except OSError:
            pass
        return None


def _ssl_context():
    context = ssl.create_default_context()  # the OS certificate store (works behind corporate proxies)
    try:
        import certifi
        context.load_verify_locations(certifi.where())
    except (ImportError, OSError):
        pass
    return context


def _get(url, timeout=60):
    request = urllib.request.Request(url, headers={'User-Agent': 'YT-DLP-Studio'})
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return response.read()


def _wheel(release):
    """(url, sha256) of the universal wheel in a PyPI JSON release description."""
    for file in release['urls']:
        if file['packagetype'] == 'bdist_wheel' and file['filename'].endswith('-py3-none-any.whl'):
            return file['url'], file['digests']['sha256']
    raise RuntimeError('На PyPI нет подходящего пакета')


def _download_wheel(url, sha256, say):
    say(f'Загрузка {url.rsplit("/", 1)[-1]}')
    data = _get(url, timeout=300)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise RuntimeError('Контрольная сумма не совпала — загрузка повреждена')
    return zipfile.ZipFile(io.BytesIO(data))


def _extract(wheel, package, target):
    prefix = package + '/'
    for member in wheel.namelist():
        if member.startswith(prefix) and not member.endswith('/'):
            destination = target / member
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(wheel.read(member))


def _ejs_pin(wheel):
    """yt-dlp[default] pins an exact yt-dlp-ejs version; the pair must match."""
    metadata = next((n for n in wheel.namelist() if n.endswith('.dist-info/METADATA')), None)
    if not metadata:
        return None
    match = re.search(r'^Requires-Dist: yt-dlp-ejs==([\w.]+)', wheel.read(metadata).decode('utf-8'), re.M)
    return match.group(1) if match else None


def update(config_root, current_version, say=print):
    """Downloads the latest yt-dlp (+ the matching yt-dlp-ejs). Returns (changed, version)."""
    release = json.loads(_get(PYPI.format(name='yt-dlp')))
    latest = release['info']['version']
    say(f'Установлена версия {current_version}, последняя на PyPI — {latest}')
    if _normalize(latest) == _normalize(current_version):
        say('Обновление не требуется.')
        return False, latest

    root = runtime_dir(config_root)
    folder = root / f'yt-dlp-{latest}'
    staging = root / f'.staging-{latest}'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        wheel = _download_wheel(*_wheel(release), say)
        _extract(wheel, 'yt_dlp', staging)
        ejs = _ejs_pin(wheel)
        if ejs:
            ejs_release = json.loads(_get(PYPI_VERSION.format(name='yt-dlp-ejs', version=ejs)))
            _extract(_download_wheel(*_wheel(ejs_release), say), 'yt_dlp_ejs', staging)
        if not (staging / 'yt_dlp' / '__init__.py').is_file():
            raise RuntimeError('В пакете нет yt_dlp')
        shutil.rmtree(folder, ignore_errors=True)
        staging.rename(folder)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    previous = _active_folder(config_root)
    (root / 'current.txt').write_text(folder.name, 'utf-8')
    # keep the new folder and the one currently loaded (it is in use until the restart)
    for old in root.glob('yt-dlp-*'):
        if old not in (folder, previous):
            shutil.rmtree(old, ignore_errors=True)
    say(f'yt-dlp {latest} готов. Перезапустите приложение, чтобы начать его использовать.')
    return True, latest


def reset(config_root):
    """Go back to the yt-dlp bundled with the app (takes effect after a restart)."""
    try:
        (runtime_dir(config_root) / 'current.txt').unlink()
    except FileNotFoundError:
        pass


def _normalize(version):
    return tuple(int(p) for p in re.findall(r'\d+', version or ''))
