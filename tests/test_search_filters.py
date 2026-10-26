from fastapi.testclient import TestClient

from app.main import app


def test_status_exposes_default_uf(monkeypatch):
    monkeypatch.setenv('RADAR_DEFAULT_UF', 'sp')
    with TestClient(app) as cli:
        assert cli.get('/api/auth/status').json()['default_uf'] == 'SP'
    monkeypatch.delenv('RADAR_DEFAULT_UF')
    with TestClient(app) as cli:
        assert cli.get('/api/auth/status').json()['default_uf'] == ''
