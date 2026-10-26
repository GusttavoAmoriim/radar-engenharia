"""Run the radar without Docker: the web site and the collector together, reading .env.

    python run_local.py        (Windows: double-click iniciar.bat)

Stop with Ctrl+C. The database is kept in the ./dados folder.
"""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from app import envfile

ROOT = Path(__file__).resolve().parent


def environment():
    """Defaults < .env file < variables already set in the terminal."""
    defaults = {'RADAR_DB': str(ROOT / 'dados' / 'radar.sqlite3')}
    return {**defaults, **envfile.load(ROOT / '.env'), **os.environ}


def wait_for_site(web, port, seconds=90):
    """The collector starts only after the site has created/migrated the database."""
    url = f'http://127.0.0.1:{port}/healthz'
    for _ in range(seconds):
        if web.poll() is not None:
            return False
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except OSError:
            time.sleep(1)
    return False


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    env = environment()
    port = env.get('RADAR_PORT', '8765')
    password = env.get('RADAR_PASSWORD', '')
    if len(password) < 7 or 'SUBSTITUA' in password.upper():
        print('Defina RADAR_PASSWORD no arquivo .env (pelo menos 7 caracteres, sem o texto de exemplo).')
        return 1
    if env.get('RADAR_COOKIE_SECURE', '1') == '1':
        print(
            'Aviso: para usar em http://127.0.0.1 coloque RADAR_COOKIE_SECURE=0 no .env; senão o login pode não funcionar.'
        )
    (ROOT / 'dados').mkdir(exist_ok=True)
    web = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port, '--workers', '1'],
        cwd=ROOT,
        env=env,
    )
    worker = None
    try:
        if not wait_for_site(web, port):
            print('O site não iniciou. Veja a mensagem de erro acima.')
            return 1
        worker = subprocess.Popen([sys.executable, '-m', 'app.worker'], cwd=ROOT, env=env)
        print(
            f'\nRadar no ar: abra http://127.0.0.1:{port} no navegador. Para encerrar, feche esta janela ou aperte Ctrl+C.\n'
        )
        while web.poll() is None and worker.poll() is None:
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if worker:
            stop(worker)
        stop(web)


if __name__ == '__main__':
    sys.exit(main())
