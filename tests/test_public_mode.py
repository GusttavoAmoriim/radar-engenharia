from fastapi.testclient import TestClient

from app import repository as repo
from app.main import app

PASSWORD = 'Very-Strong-Password-TEST-1234'


def _item(**extra):
    data = {
        'title': 'Concurso Engenharia',
        'agency': 'Órgão',
        'position': 'Engenheiro Civil',
        'official_url': 'https://www.gov.br/c',
        'notice_url': 'https://www.gov.br/e.pdf',
    }
    data.update(extra)
    return repo.upsert(data, enrich_only=False)[0]


def test_visitor_can_browse_but_not_change_anything(monkeypatch):
    monkeypatch.setenv('RADAR_PUBLIC', '1')
    oid = _item(notes='anotação pessoal', favorite=1, applied=1)
    hidden = _item(title='Oculto', notice_url='https://www.gov.br/x.pdf', dismissed=1)
    with TestClient(app) as cli:
        status = cli.get('/api/auth/status').json()
        assert status == {
            'authenticated': False,
            'public': True,
            'default_uf': '',
            'mfa_enabled': None,
            'csrf': None,
        }
        items = cli.get('/api/opportunities').json()['items']
        mine = next(i for i in items if i['id'] == oid)
        assert 'notes' not in mine and 'favorite' not in mine and 'applied' not in mine
        assert all(i['id'] != hidden for i in items), 'dismissed items are not public'
        assert cli.get(f'/api/opportunities/{hidden}').status_code == 404
        assert cli.get('/api/sources').status_code == 200
        assert cli.get('/api/alerts').status_code == 200
        csv = cli.get('/api/export.csv').text
        assert 'notes' not in csv.splitlines()[0] and 'anotação pessoal' not in csv
        # admin-only reads and every write stay closed
        assert cli.get('/api/candidates').status_code == 401
        assert cli.post('/api/scan', json={}).status_code == 401
        assert cli.patch(f'/api/opportunities/{oid}', json={'favorite': 0}).status_code == 401
        assert cli.post(f'/api/opportunities/{oid}/verify', json={}).status_code == 401
        assert cli.post('/api/auth/mfa/setup', json={'password': PASSWORD}).status_code == 401
        assert 'Allow: /' in cli.get('/robots.txt').text


def test_admin_sees_personal_fields(monkeypatch):
    monkeypatch.setenv('RADAR_PUBLIC', '1')
    oid = _item(notes='anotação pessoal', favorite=1)
    with TestClient(app) as cli:
        csrf = cli.post('/api/auth/login', json={'password': PASSWORD}).json()['csrf']
        mine = next(i for i in cli.get('/api/opportunities').json()['items'] if i['id'] == oid)
        assert mine['notes'] == 'anotação pessoal' and mine['favorite'] == 1
        assert cli.get('/api/candidates').status_code == 200
        assert cli.get('/api/auth/status').json()['mfa_enabled'] is False
        r = cli.patch(f'/api/opportunities/{oid}', json={'favorite': 0}, headers={'X-CSRF-Token': csrf})
        assert r.status_code == 200


def test_private_mode_requires_login_for_everything(monkeypatch):
    monkeypatch.setenv('RADAR_PUBLIC', '0')
    _item()
    with TestClient(app) as cli:
        assert cli.get('/api/auth/status').json()['public'] is False
        for path in ('/api/opportunities', '/api/sources', '/api/alerts', '/api/export.csv'):
            assert cli.get(path).status_code == 401, path
        assert 'Disallow: /' in cli.get('/robots.txt').text
        assert cli.get('/').status_code == 200 and cli.get('/healthz').status_code == 200
