"""YT-DLP Studio — graphical interface for yt-dlp.

    python main.py              open in a native window (pywebview) or the browser
    python main.py --browser    always open in the default browser
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


def restart():
    args = [sys.executable, os.path.abspath(__file__), *sys.argv[1:]]
    if sys.platform == 'win32':
        subprocess.Popen(args)
        os._exit(0)
    os.execv(sys.executable, args)


def main():
    parser = argparse.ArgumentParser(description='YT-DLP Studio')
    parser.add_argument('--port', type=int, default=int(os.environ.get('YTDLP_GUI_PORT', 0)),
                        help='порт (по умолчанию — любой свободный)')
    parser.add_argument('--browser', action='store_true', help='открыть в браузере, а не в отдельном окне')
    parser.add_argument('--no-open', action='store_true', help='ничего не открывать')
    args = parser.parse_args()

    # after an in-app restart the browser tab reconnects by itself; a native window must be reopened
    reopened = os.environ.get('YTDLP_GUI_RESTARTED') == 'browser'
    app = App(token=os.environ.get('YTDLP_GUI_TOKEN'))
    server = serve(app, port=args.port)
    port = server.server_address[1]
    url = f'http://127.0.0.1:{port}/'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'YT-DLP Studio запущен: {url}')
    print('Закройте это окно (или Ctrl+C), чтобы остановить приложение.')

    ui = {'mode': 'browser'}

    def watch_restart():
        app.restart_requested.wait()
        os.environ.update(YTDLP_GUI_TOKEN=app.token, YTDLP_GUI_PORT=str(port), YTDLP_GUI_RESTARTED=ui['mode'])
        server.shutdown()
        server.server_close()
        restart()

    threading.Thread(target=watch_restart, daemon=True).start()

    if not args.no_open and not args.browser and not reopened:
        try:
            import webview  # pywebview, optional
        except ImportError:
            webview = None
        if webview:
            try:
                ui['mode'] = 'window'
                webview.create_window('YT-DLP Studio', url, width=1360, height=880, min_size=(980, 640),
                                      background_color='#0b0b14')
                webview.start()
                return
            except Exception as e:  # no GUI backend available — fall back to the browser
                ui['mode'] = 'browser'
                print(f'Окно недоступно ({e}), открываю браузер…')

    if not args.no_open and not reopened:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print('\nОстановлено.')


if __name__ == '__main__':
    main()
