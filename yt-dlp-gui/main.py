"""YT-DLP Studio — graphical interface for yt-dlp.

    python main.py              open the way chosen in the app's settings (window or browser)
    python main.py --window     open in a separate window (pywebview) and remember the choice
    python main.py --browser    open in the default browser and remember the choice
    python main.py --no-open    only start the server and print its address
"""

import argparse
import os
import subprocess
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import yt_dlp  # noqa: F401
except ImportError:
    sys.exit('yt-dlp не установлен. Выполните:  python -m pip install -r requirements.txt')

from backend.server import App, serve  # noqa: E402
from backend.window import open_window, resolve_mode  # noqa: E402

UI_FLAGS = ('--window', '--browser')


def restart():
    # --window/--browser were already saved to the settings; dropping them lets an in-app switch win
    args = [sys.executable, os.path.abspath(__file__), *(a for a in sys.argv[1:] if a not in UI_FLAGS)]
    if sys.platform == 'win32':
        subprocess.Popen(args)
        os._exit(0)
    os.execv(sys.executable, args)


def main():
    parser = argparse.ArgumentParser(description='YT-DLP Studio')
    parser.add_argument('--port', type=int, default=int(os.environ.get('YTDLP_GUI_PORT', 0)),
                        help='порт (по умолчанию — любой свободный)')
    ui = parser.add_mutually_exclusive_group()
    ui.add_argument('--window', action='store_true', help='открывать в отдельном окне (нужен pywebview)')
    ui.add_argument('--browser', action='store_true', help='открывать во вкладке браузера')
    parser.add_argument('--no-open', action='store_true', help='ничего не открывать')
    args = parser.parse_args()

    app = App(token=os.environ.get('YTDLP_GUI_TOKEN'))
    if args.window or args.browser:
        app.storage.save_settings({'app': {'ui_mode': 'window' if args.window else 'browser'}})
    mode = resolve_mode(app.storage.load_settings()['app'].get('ui_mode'))
    # How the previous process (before an in-app restart) was shown: a browser tab reconnects by itself
    previous = os.environ.pop('YTDLP_GUI_RESTARTED', '')

    server = serve(app, port=args.port)
    port = server.server_address[1]
    url = f'http://127.0.0.1:{port}/'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'YT-DLP Studio запущен: {url}')
    print('Закройте это окно (или Ctrl+C), чтобы остановить приложение.')

    def watch_restart():
        app.restart_requested.wait()
        os.environ.update(YTDLP_GUI_TOKEN=app.token, YTDLP_GUI_PORT=str(port), YTDLP_GUI_RESTARTED=app.ui_mode)
        server.shutdown()
        server.server_close()
        restart()

    threading.Thread(target=watch_restart, daemon=True).start()

    if not args.no_open and mode == 'window':
        app.ui_mode = 'window'
        try:
            open_window(url, str(app.storage.root / 'webview'))
            return  # the window was closed — quit
        except Exception as e:  # pywebview missing or no GUI backend — fall back to the browser
            app.ui_mode = 'browser'
            app.ui_error = f'{e.__class__.__name__}: {e}'
            print(f'Отдельное окно недоступно ({app.ui_error}), открываю браузер…')

    app.ui_mode = 'browser'
    if not args.no_open and previous != 'browser':
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print('\nОстановлено.')


if __name__ == '__main__':
    main()
