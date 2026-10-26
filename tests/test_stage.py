import pytest
from fastapi.testclient import TestClient

from app import database, repository
from app.main import app

PASSWORD = 'Very-Strong-Password-TEST-1234'


def test_stage_values_are_validated():
    repository.validate({'title': 'x', 'stage': 'inscrito'})
    repository.validate({'title': 'x', 'stage': None})
    with pytest.raises(ValueError):
        repository.validate({'title': 'x', 'stage': 'sorteado'})


def test_migration_three_is_recorded():
    assert database.schema_version() >= 3


def test_stage_is_private_and_saved_for_admin(monkeypatch):
    monkeypatch.setenv('RADAR_PUBLIC', '1')
    with TestClient(app) as cli:
        login = cli.post('/api/auth/login', json={'password': PASSWORD})
        assert login.status_code == 200
        h = {'X-CSRF-Token': login.json()['csrf']}
        created = cli.post(
            '/api/opportunities',
            json={
                'title': 'Concurso de teste',
                'stage': 'interesse',
                'official_url': 'https://portal.trt15.jus.br/concurso',
                'notice_url': 'https://portal.trt15.jus.br/edital.pdf',
            },
            headers=h,
        )
        assert created.status_code == 201, created.text
        oid = created.json()['id']
        patched = cli.patch(f'/api/opportunities/{oid}', json={'stage': 'prova'}, headers=h)
        assert patched.status_code == 200, patched.text
        assert cli.get(f'/api/opportunities/{oid}').json()['stage'] == 'prova'
        assert cli.patch(f'/api/opportunities/{oid}', json={'stage': 'xyz'}, headers=h).status_code == 422
    with TestClient(app) as visitor:
        shown = visitor.get(f'/api/opportunities/{oid}').json()
        assert 'stage' not in shown
        assert 'stage' not in visitor.get('/api/export.csv').text.splitlines()[0]
