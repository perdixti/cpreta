"""Single local instance, explicit shutdown and recoverable diagnostics."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import signal
import threading
import time
import urllib.request
import webbrowser
from werkzeug.serving import make_server

URL = 'http://127.0.0.1:3847'


def already_running():
    try:
        with urllib.request.urlopen(URL + '/health', timeout=1) as response:
            return json.load(response).get('application') == 'CPreta'
    except (OSError, ValueError):
        return False


def run():
    from app import create_app
    parser = argparse.ArgumentParser(description='CPreta: painel local e assistente de atividades')
    parser.add_argument('--web-only', action='store_true', help='Executar o painel, sem popup nativo')
    parser.add_argument('--open-browser', action='store_true', help='Abrir o painel após a inicialização')
    args = parser.parse_args()
    if already_running():
        print('O CPreta já está em execução em ' + URL, flush=True)
        if args.open_browser:
            webbrowser.open(URL + '/relatorios')
        return
    app = create_app()
    store = app.extensions['activities']
    config_store = app.extensions['config_store']
    runtime = app.extensions['desktop_runtime']
    log_dir = config_store.data_dir / 'logs'
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(log_dir / 'cpreta.log', maxBytes=500000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    # Bind before touching unfinished intervals. A duplicate must not close them.
    try:
        server = make_server('127.0.0.1', 3847, app, threaded=True)
    except (OSError, SystemExit) as error:
        raise RuntimeError('A porta 3847 está ocupada ou indisponível. Confira se o CPreta já está aberto.') from error
    root = controller = None
    try:
        heartbeat = config_store.data_dir / 'last_seen.json'
        last_seen = None
        try:
            last_seen = float(json.loads(heartbeat.read_text(encoding='utf-8'))['at'])
        except (ValueError, KeyError, TypeError, OSError):
            pass
        store.recover(last_seen)
        if not args.web_only:
            try:
                import tkinter as tk
                from desktop import DesktopController
                root = tk.Tk()
                root.withdraw()
                controller = DesktopController(root, store, config_store, runtime)
            except Exception:
                logging.exception('Popup nativo indisponível')
                if root:
                    root.destroy()
                root = None
                runtime.desktop = False
                runtime.description = 'Modo web: use o registro pelo painel. No Linux, confira python3-tk e a sessão gráfica.'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print('CPreta disponível em ' + URL + '/relatorios', flush=True)
        print('Encerre pelo painel. Se iniciado diretamente no terminal, Ctrl+C tambem encerra.', flush=True)
        stop = runtime.shutdown_requested
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        if args.open_browser:
            webbrowser.open(URL + '/relatorios')
        if root:
            def check_stop():
                if stop.is_set():
                    root.quit()
                else:
                    root.after(250, check_stop)
            root.after(250, check_stop)
            root.mainloop()
        else:
            while not stop.wait(5):
                temp = heartbeat.with_suffix('.tmp')
                temp.write_text(json.dumps({'at': time.time()}), encoding='utf-8')
                temp.replace(heartbeat)
    finally:
        if controller:
            controller.shutdown()
        else:
            store.finish()
        if 'thread' in locals() and thread.is_alive():
            server.shutdown()
        server.server_close()
        logging.getLogger().removeHandler(handler)
        handler.close()
