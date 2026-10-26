import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

STATIC = Path(__file__).resolve().parents[1] / 'static'


def test_index_is_versioned_and_csp_friendly():
    html = (STATIC / 'index.html').read_text()
    assert '__VERSION__' in html
    assert 'style="' not in html, 'inline styles are blocked by the CSP'
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', html), 'inline scripts are blocked by the CSP'
    assert 'minlength="7"' in html


def test_every_referenced_module_exists():
    js = STATIC / 'js'
    for file in [*js.glob('*.js'), *js.glob('views/*.js')]:
        for target in re.findall(r"from '(\.{1,2}/[^']+)'", file.read_text()):
            assert (file.parent / target).resolve().is_file(), f'{file.name} imports missing {target}'
        assert 'style="' not in file.read_text(), f'inline style attribute in {file.name}'


def test_two_themes_and_auto_mode():
    css = (STATIC / 'css' / 'app.css').read_text()
    assert ":root[data-theme='dark']" in css
    assert 'prefers-color-scheme: dark' in css
    boot = (STATIC / 'js' / 'theme-boot.js').read_text()
    assert 'speedlora.colorScheme.v2' in boot, 'old theme preference is migrated'


def test_static_serving_is_safe_and_fresh():
    with TestClient(app) as cli:
        page = cli.get('/')
        assert page.status_code == 200 and f'v={__version__}' in page.text and '__VERSION__' not in page.text
        assert page.headers['cache-control'] == 'no-store'
        css = cli.get('/static/css/app.css')
        assert css.status_code == 200 and css.headers['content-type'].startswith('text/css')
        assert css.headers['cache-control'] == 'no-cache'
        js = cli.get('/static/js/main.js')
        assert js.status_code == 200 and 'javascript' in js.headers['content-type']
        assert cli.get('/static/index.html').status_code == 404
        assert cli.get('/static/package.json').status_code == 404
        assert cli.get('/static/../app/auth.py').status_code in (404, 401)
        assert cli.get('/static/%2e%2e/app/auth.py').status_code == 404
        assert cli.get('/favicon.ico').status_code == 200
