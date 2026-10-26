"""Regression: a valid seven-character password must boot and authenticate."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app


def test_seven_character_password_accepted(monkeypatch):
    monkeypatch.setenv('RADAR_PASSWORD', 'ab12345')
    assert auth.password_configured()
    assert auth.password_ok('ab12345')
    assert not auth.password_ok('ab1234')
    with TestClient(app) as client:
        assert client.get('/healthz').status_code == 200
        assert client.post('/api/auth/login', json={'password': 'ab12345'}).status_code == 200


@pytest.mark.parametrize('password', ['', '123456', 'SUBSTITUA'])
def test_invalid_password_setting_refuses_startup(monkeypatch, password):
    monkeypatch.setenv('RADAR_PASSWORD', password)
    assert not auth.password_configured()
    with pytest.raises(RuntimeError, match=r'pelo menos 7 caracteres|sem valor de exemplo'):
        with TestClient(app):
            pass


def test_form_minlength_matches_backend():
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / 'static' / 'index.html').read_text()
    assert 'minlength="7"' in html
    assert 'minlength="12"' not in html
