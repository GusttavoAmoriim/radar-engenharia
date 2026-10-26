from fastapi.testclient import TestClient

from app import database, notifications, repository
from app.main import app

PASSWORD = 'Very-Strong-Password-TEST-1234'


class Recorder:
    def __init__(self):
        self.sent = []

    def __call__(self, url, json=None, timeout=None):
        self.sent.append(json['text'])

        class Ok:
            def raise_for_status(self):
                return None

        return Ok()


def clear_channels(monkeypatch):
    for name in ('SMTP_HOST', 'ALERT_EMAIL_TO', 'ALERT_EMAIL_FROM', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
        monkeypatch.delenv(name, raising=False)


def test_test_message_without_channels_reports_it(monkeypatch):
    clear_channels(monkeypatch)
    result = notifications.send_test()
    assert result == {'channels': [], 'configured': False}


def test_test_message_goes_to_telegram_and_leaves_alerts_alone(monkeypatch):
    clear_channels(monkeypatch)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '123:TEST')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '42')
    recorder = Recorder()
    monkeypatch.setattr(notifications.requests, 'post', recorder)
    with database.connection() as db:
        before = db.execute('SELECT COUNT(*) FROM alerts WHERE notified=0').fetchone()[0]
    result = notifications.send_test()
    assert result['channels'] == ['telegram']
    assert 'teste de aviso' in recorder.sent[0]
    with database.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM alerts WHERE notified=0').fetchone()[0] == before


def test_dispatch_keeps_alerts_pending_when_no_channel_accepts(monkeypatch):
    clear_channels(monkeypatch)
    repository.add_alert('test-pending-key', 'info', 'Aviso pendente de teste')
    result = notifications.dispatch()
    assert result['sent'] == 0
    with database.connection() as db:
        assert db.execute("SELECT notified FROM alerts WHERE unique_key='test-pending-key'").fetchone()[0] == 0


def test_api_refuses_test_without_channels(monkeypatch):
    clear_channels(monkeypatch)
    with TestClient(app) as cli:
        h = {'X-CSRF-Token': cli.post('/api/auth/login', json={'password': PASSWORD}).json()['csrf']}
        r = cli.post('/api/notifications/test', json={}, headers=h)
        assert r.status_code == 422
        assert 'Nenhum canal' in r.json()['detail']
