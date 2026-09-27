# PyInstaller spec for the YT-DLP Studio desktop app.
#   pyinstaller desktop/yt-dlp-studio.spec --noconfirm --distpath dist --workpath build
# Produces dist/YT-DLP Studio/YT-DLP Studio.exe (a folder build: starts faster and trips
# antivirus heuristics far less often than a single-file exe).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent          # yt-dlp-gui/
sys.path.insert(0, str(ROOT))
from backend.version import APP_VERSION  # noqa: E402

APP_NAME = 'YT-DLP Studio'
WINDOWS = sys.platform == 'win32'
BIN = Path(SPECPATH) / 'bin'          # ffmpeg + deno, downloaded by fetch-tools.ps1

datas = [(str(ROOT / 'web'), 'web')]
if BIN.is_dir():
    # plain data: these are standalone programs, PyInstaller must not analyse or relocate their DLLs
    datas += [(str(f), 'bin') for f in BIN.iterdir() if f.is_file() and f.name != 'README.txt']

hiddenimports = collect_submodules('backend')
if WINDOWS:
    hiddenimports += ['webview.platforms.winforms', 'webview.platforms.edgechromium', 'clr']
else:
    hiddenimports += ['webview.platforms.qt']

a = Analysis(
    [str(ROOT / 'desktop.py')],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['tkinter'],
    # yt-dlp ships as plain .py files next to the exe instead of inside the frozen archive, so an
    # updated copy downloaded into the user's folder (backend/runtime.py) can take precedence
    module_collection_mode={'yt_dlp': 'py', 'yt_dlp_ejs': 'py'},
    noarchive=False,
)
pyz = PYZ(a.pure)

version_info = None
if WINDOWS:
    from PyInstaller.utils.win32 import versioninfo as vi
    numbers = tuple(int(p) for p in (APP_VERSION.split('.') + ['0'] * 4)[:4])
    version_info = vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            vi.StringFileInfo([vi.StringTable('041904B0', [
                vi.StringStruct('FileDescription', APP_NAME),
                vi.StringStruct('ProductName', APP_NAME),
                vi.StringStruct('FileVersion', APP_VERSION),
                vi.StringStruct('ProductVersion', APP_VERSION),
                vi.StringStruct('OriginalFilename', f'{APP_NAME}.exe'),
                vi.StringStruct('InternalName', APP_NAME),
                vi.StringStruct('LegalCopyright', 'YT-DLP Studio; yt-dlp is released under the Unlicense'),
            ])]),
            vi.VarFileInfo([vi.VarStruct('Translation', [0x0419, 1200])]),
        ],
    )

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,                    # a real GUI app: no console window
    icon=str(Path(SPECPATH) / 'icon.ico'),
    version=version_info,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)
