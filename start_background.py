"""Start the local application without keeping a terminal attached."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

BASE = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:3847'
# A local health check must never go through an environment-configured proxy.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def healthy():
    try:
        with OPENER.open(URL + '/health', timeout=1) as response:
            return json.load(response).get('application') == 'CPreta'
    except (OSError, ValueError):
        return False


def start(open_browser=True):
    if healthy():
        if open_browser:
            webbrowser.open(URL + '/relatorios')
        print('O CPreta ja esta em execucao.')
        return 0
    logs = BASE / 'data' / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    output = logs / 'startup.log'
    if output.exists() and output.stat().st_size > 500_000:
        output.replace(logs / 'startup.previous.log')
    options = dict(cwd=BASE, stdin=subprocess.DEVNULL, close_fds=True,
                   env=dict(os.environ, PYTHONUTF8='1'))
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    with output.open('ab', buffering=0) as log:
        process = subprocess.Popen(
            [sys.executable, '-u', str(BASE / 'app.py')],
            stdout=log, stderr=log, **options)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if healthy():
            if open_browser:
                webbrowser.open(URL + '/relatorios')
            print('CPreta em segundo plano: ' + URL + '/relatorios')
            print('Encerre pelo painel, em Configuracao.')
            return 0
        if process.poll() is not None:
            print('O CPreta nao iniciou. Consulte: ' + str(output), file=sys.stderr)
            return 1
        time.sleep(.25)
    # Only stop the child created here; never terminate a pre-existing instance.
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    print('A inicializacao nao foi confirmada; a tentativa foi encerrada. Consulte: ' + str(output), file=sys.stderr)
    return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Iniciar CPreta em segundo plano')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        raise SystemExit(start(open_browser=not args.no_browser))
    except (OSError, subprocess.SubprocessError) as error:
        print('Nao foi possivel iniciar o CPreta: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
