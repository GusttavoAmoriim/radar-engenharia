from fastapi.testclient import TestClient

from app import config
from app.main import app


def test_app_name_defaults_and_is_escaped(monkeypatch):
    monkeypatch.delenv('RADAR_APP_NAME', raising=False)
    assert config.app_name() == 'Radar Engenharia'
    monkeypatch.setenv('RADAR_APP_NAME', 'Meu <b>Radar</b> & Co')
    with TestClient(app) as cli:
        html = cli.get('/').text
    assert 'Meu &lt;b&gt;Radar&lt;/b&gt; &amp; Co' in html
    assert '<b>Radar</b>' not in html
    assert '__APP_NAME__' not in html


def test_default_uf_accepts_only_two_letters(monkeypatch):
    monkeypatch.setenv('RADAR_DEFAULT_UF', 'sp')
    assert config.default_uf() == 'SP'
    monkeypatch.setenv('RADAR_DEFAULT_UF', 'São Paulo')
    assert config.default_uf() == ''
    monkeypatch.delenv('RADAR_DEFAULT_UF')
    assert config.default_uf() == ''
