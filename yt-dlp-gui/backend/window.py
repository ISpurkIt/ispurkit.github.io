"""Optional native window (pywebview) instead of a browser tab."""

import importlib
import importlib.util
import sys

MODES = ('auto', 'window', 'browser')


def webview_available():
    importlib.invalidate_caches()
    return importlib.util.find_spec('webview') is not None


def webview_packages():
    # Windows uses the built-in Edge WebView2, macOS — WebKit; Linux needs a Qt web engine
    return ['pywebview[qt]'] if sys.platform.startswith('linux') else ['pywebview']


def resolve_mode(mode):
    if mode not in MODES:
        mode = 'auto'
    if mode == 'auto':
        return 'window' if webview_available() else 'browser'
    return mode


def open_window(url, storage_path):
    """Blocks until the window is closed. Raises if no GUI backend is usable."""
    import webview

    webview.create_window('YT-DLP Studio', url, width=1360, height=880, min_size=(980, 640),
                          background_color='#09090f', text_select=True)
    webview.start(
        # without this pywebview may fall back to the old IE engine on Windows, which can't run the UI
        gui='edgechromium' if sys.platform == 'win32' else None,
        # keep localStorage (open sections, last page) between launches
        private_mode=False,
        storage_path=storage_path,
    )
