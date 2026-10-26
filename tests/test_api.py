from fastapi.testclient import TestClient

from app import auth, evidence
from app.main import app


def login(client):
    r = client.post('/api/auth/login', json={'password': 'Very-Strong-Password-TEST-1234'})
    assert r.status_code == 200
    return r.json()['csrf']


def test_login_password_only_and_logout(monkeypatch):
    monkeypatch.setenv('RADAR_PUBLIC', '0')
    with TestClient(app) as cli:
        assert cli.get('/healthz').status_code == 200
        assert cli.get('/api/opportunities').status_code == 401
        assert cli.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
        csrf = login(cli)
        assert cli.get('/api/opportunities').status_code == 200
        assert cli.post('/api/auth/logout', headers={'X-CSRF-Token': csrf}, json={}).status_code == 200
        assert cli.get('/api/opportunities').status_code == 401


def test_csrf_origin_rejection():
    with TestClient(app) as cli:
        csrf = login(cli)
        assert cli.post('/api/scan', json={}).status_code == 403
        assert (
            cli.post('/api/scan', json={}, headers={'Origin': 'https://evil.example', 'X-CSRF-Token': csrf}).status_code
            == 403
        )


def test_edit_cannot_fake_verified(monkeypatch):
    with TestClient(app) as cli:
        csrf = login(cli)
        h = {'X-CSRF-Token': csrf}
        created = cli.post(
            '/api/opportunities',
            headers=h,
            json={
                'title': 'Concurso Engenharia',
                'position': 'Engenheiro Civil',
                'official_url': 'https://www.gov.br/c',
                'notice_url': 'https://www.gov.br/a.pdf',
                'confidence': 'official',
                'reviewed': 1,
                'registration_start': '2026-10-01',
                'registration_end': '2026-10-20',
            },
        )
        assert created.status_code == 201
        oid = created.json()['id']
        assert created.json()['status'] == 'verify'
        changed = cli.patch(
            f'/api/opportunities/{oid}', headers=h, json={'reviewed': 1, 'confidence': 'official', 'favorite': 1}
        )
        assert changed.status_code == 200 and changed.json()['status'] == 'verify'
        assert cli.get('/api/candidates').status_code == 200
        assert cli.get('/api/sources').status_code == 200
        assert 'title' in cli.get('/api/export.csv').text


def test_refuse_nonofficial_post():
    with TestClient(app) as cli:
        csrf = login(cli)
        h = {'X-CSRF-Token': csrf}
        payload = {
            'title': 'Fake',
            'position': 'Engenheiro Civil',
            'official_url': 'https://evil.com/edital',
            'notice_url': 'https://evil.com/edital',
        }
        assert cli.post('/api/opportunities', json=payload, headers=h).status_code == 422


def test_verify_mocked_proof(monkeypatch):
    proof = evidence.Proof(
        'https://www.gov.br/edital.pdf',
        'b' * 64,
        'Concurso Público Edital\nEngenheiro Civil R$ 9.000,00\nInscrições: 01/10/2026 a 20/10/2026.\nProva 13/12/2026.',
        'pdf',
        'engenheiro civil',
    )
    monkeypatch.setattr(evidence, 'fetch_official', lambda url, session=None: (url, b'%PDF-1.4', 'application/pdf'))
    monkeypatch.setattr(evidence, 'prove_document', lambda resolved, raw, mime, position='': proof)
    with TestClient(app) as cli:
        csrf = login(cli)
        h = {'X-CSRF-Token': csrf}
        r = cli.post(
            '/api/opportunities',
            json={
                'title': 'Concurso Engenharia',
                'position': 'Engenheiro Civil',
                'official_url': 'https://www.gov.br/edital.pdf',
                'notice_url': 'https://www.gov.br/edital.pdf',
                'salary_min': 9000,
                'registration_start': '2026-10-01',
                'registration_end': '2026-10-20',
            },
            headers=h,
        )
        assert r.status_code == 201
        verified = cli.post('/api/opportunities/' + str(r.json()['id']) + '/verify', headers=h, json={})
        assert verified.status_code == 200, verified.text
        assert verified.json()['document_verified'] is True
        assert verified.json()['salary_verified'] is True
        assert verified.json()['status'] == 'open'


def test_mfa_lifecycle_and_recovery(monkeypatch):
    with TestClient(app) as cli:
        csrf = login(cli)
        h = {'X-CSRF-Token': csrf}
        started = cli.post('/api/auth/mfa/setup', json={'password': 'Very-Strong-Password-TEST-1234'}, headers=h)
        assert started.status_code == 200, started.text
        secret = started.json()['secret']
        code = auth.totp(secret)
        completed = cli.post('/api/auth/mfa/confirm', json={'code': code}, headers=h)
        assert completed.status_code == 200
        recovery = completed.json()['recovery_codes']
        assert len(recovery) == 8
        cli.post('/api/auth/logout', json={}, headers=h)
        assert cli.post('/api/auth/login', json={'password': 'Very-Strong-Password-TEST-1234'}).json()['mfa_required']
        bad = cli.post('/api/auth/login', json={'password': 'Very-Strong-Password-TEST-1234', 'code': '123123'})
        assert bad.status_code == 401
        good = cli.post('/api/auth/login', json={'password': 'Very-Strong-Password-TEST-1234', 'code': recovery[0]})
        assert good.status_code == 200
        assert auth.mfa_check(recovery[0], consume_recovery=True) is False
        disable = cli.post(
            '/api/auth/mfa/disable',
            json={'password': 'Very-Strong-Password-TEST-1234', 'code': auth.totp(secret)},
            headers={'X-CSRF-Token': good.json()['csrf']},
        )
        assert disable.status_code == 200
        assert not auth.mfa_enabled()


def test_rate_limit():
    with TestClient(app) as cli:
        for _ in range(5):
            cli.post('/api/auth/login', json={'password': 'wrong'})
        assert cli.post('/api/auth/login', json={'password': 'Very-Strong-Password-TEST-1234'}).status_code == 429


def test_healthz_reports_version():
    from app import __version__

    with TestClient(app) as cli:
        body = cli.get('/healthz').json()
    assert body['service'] == 'ok'
    assert body['version'] == __version__
