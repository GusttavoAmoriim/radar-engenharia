from fastapi.testclient import TestClient

from app import auth
from app.main import app

PASSWORD = 'Very-Strong-Password-TEST-1234'
NEW_PASSWORD = 'Another-Strong-Password-5678'


def sign_in(client, **extra):
    r = client.post('/api/auth/login', json={'password': PASSWORD, **extra}, headers={'User-Agent': 'pytest-device'})
    assert r.status_code == 200, r.text
    return {'X-CSRF-Token': r.json()['csrf']}


def test_password_hash_roundtrip():
    stored = auth.hash_password('uma-senha-longa-123')
    assert stored.startswith('scrypt$')
    assert auth.verify_password('uma-senha-longa-123', stored)
    assert not auth.verify_password('outra-senha-123', stored)
    assert auth.hash_password('uma-senha-longa-123') != stored  # random salt


def test_change_password_rules():
    for bad in ('curta', PASSWORD):
        try:
            auth.change_password(PASSWORD, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'accepted {bad!r}')
    try:
        auth.change_password('senha-errada-123456', NEW_PASSWORD)
    except ValueError:
        pass
    else:
        raise AssertionError('accepted wrong current password')


def test_change_password_via_api_revokes_other_sessions(monkeypatch):
    other = TestClient(app)
    with TestClient(app) as cli, other:
        h = sign_in(cli)
        sign_in(other)
        assert other.get('/api/auth/sessions').status_code == 200
        ok = cli.post('/api/auth/password', json={'current': PASSWORD, 'new': NEW_PASSWORD}, headers=h)
        assert ok.status_code == 200, ok.text
        assert other.get('/api/auth/sessions').status_code == 401
        assert cli.get('/api/auth/sessions').status_code == 200
        # restore for the other tests (the database is shared inside the test run)
        back = cli.post('/api/auth/password', json={'current': NEW_PASSWORD, 'new': PASSWORD + '!'}, headers=h)
        assert back.status_code == 200, back.text
        auth.change_password(PASSWORD + '!', PASSWORD + '?')
        auth.bootstrap_password()


def test_sessions_list_and_revoke():
    first, second = TestClient(app), TestClient(app)
    with first, second:
        h1 = sign_in(first)
        sign_in(second)
        data = first.get('/api/auth/sessions').json()
        assert len(data['sessions']) >= 2
        mine = [s for s in data['sessions'] if s['current']]
        assert len(mine) == 1
        refuse = first.post('/api/auth/sessions/revoke', json={'id': mine[0]['id']}, headers=h1)
        assert refuse.status_code == 422
        target = next(s for s in data['sessions'] if not s['current'])
        assert first.post('/api/auth/sessions/revoke', json={'id': target['id']}, headers=h1).status_code == 200
        assert first.get('/api/auth/sessions').status_code == 200


def test_revoke_other_sessions_keeps_current():
    first, second = TestClient(app), TestClient(app)
    with first, second:
        h1 = sign_in(first)
        sign_in(second)
        done = first.post('/api/auth/sessions/revoke-others', json={}, headers=h1)
        assert done.status_code == 200
        assert done.json()['revoked'] >= 1
        assert second.get('/api/auth/sessions').status_code == 401
        assert first.get('/api/auth/sessions').status_code == 200
        kinds = [e['type'] for e in first.get('/api/auth/sessions').json()['events']]
        assert 'other_sessions_revoked' in kinds


def test_sessions_require_admin():
    with TestClient(app) as cli:
        assert cli.get('/api/auth/sessions').status_code == 401
        assert cli.post('/api/auth/sessions/revoke-others', json={}).status_code in (401, 403)


def test_logout_keeps_trusted_device_until_revoked():
    with TestClient(app) as cli:
        h = sign_in(cli)
        setup = cli.post('/api/auth/mfa/setup', json={'password': PASSWORD}, headers=h)
        secret = setup.json()['secret']
        assert cli.post('/api/auth/mfa/confirm', json={'code': auth.totp(secret)}, headers=h).status_code == 200
        cli.post('/api/auth/logout', json={}, headers=h)

        # first sign-in with the code and “remember”: device becomes trusted
        remember = cli.post('/api/auth/login', json={'password': PASSWORD, 'code': auth.totp(secret), 'remember': True})
        assert remember.status_code == 200
        assert cli.cookies.get(auth.TRUSTED_COOKIE)
        assert auth.trusted_device_count() == 1
        h = {'X-CSRF-Token': remember.json()['csrf']}
        cli.post('/api/auth/logout', json={}, headers=h)

        # trusted: no code needed
        again = cli.post('/api/auth/login', json={'password': PASSWORD})
        assert again.status_code == 200
        assert 'mfa_required' not in again.json()
        h = {'X-CSRF-Token': again.json()['csrf']}

        revoked = cli.post('/api/auth/trusted-devices/revoke', json={}, headers=h)
        assert revoked.json()['revoked'] == 1
        cli.post('/api/auth/logout', json={}, headers=h)
        assert cli.post('/api/auth/login', json={'password': PASSWORD}).json()['mfa_required']

        # clean up so later tests start without MFA
        final = cli.post('/api/auth/login', json={'password': PASSWORD, 'code': auth.totp(secret)})
        h = {'X-CSRF-Token': final.json()['csrf']}
        gone = cli.post('/api/auth/mfa/disable', json={'password': PASSWORD, 'code': auth.totp(secret)}, headers=h)
        assert gone.status_code == 200


def test_client_ip_only_trusts_configured_proxies(monkeypatch):
    monkeypatch.delenv('RADAR_TRUSTED_PROXIES', raising=False)
    assert auth.client_ip('203.0.113.9', '198.51.100.7') == '203.0.113.9'
    monkeypatch.setenv('RADAR_TRUSTED_PROXIES', '172.18.0.1')
    assert auth.client_ip('172.18.0.1', '198.51.100.7, 172.18.0.1') == '198.51.100.7'
    assert auth.client_ip('203.0.113.9', '198.51.100.7') == '203.0.113.9'


def test_events_are_capped_and_recorded():
    for i in range(520):
        auth.event('local', 'probe', str(i))
    assert len(auth.recent_events(1000)) <= 500
