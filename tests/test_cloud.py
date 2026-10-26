from app import cloud, kv, staticsite, telegram
from app import repository as repo


def card(**extra):
    data = {
        'title': 'Prefeitura X',
        'agency': 'X/SP',
        'position': 'Engenheiro Civil',
        'source': 's',
        'fingerprint': extra.pop('fp', 'a'),
        'registration_start': '2026-10-01',
        'registration_end': '2099-01-01',
        'confidence': 'discovery',
        'notes': '<b>x</b>',
    }
    data.update(extra)
    return repo.upsert(data)[0]


def test_page_lists_open_cards_escaped_and_hides_dismissed():
    card(title='<script>alert(1)</script>', fp='a')
    hidden = card(title='Oculto', fp='b')
    repo.update_opportunity(hidden, {'dismissed': 1})
    page = staticsite.build()
    assert '&lt;script&gt;' in page and '<script>alert(1)' not in page
    assert 'Oculto' not in page and 'Engenheiro Civil' in page


def test_first_run_sends_one_summary_only(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram, 'configured', lambda: True)
    monkeypatch.setattr(telegram, 'send', lambda text: sent.append(text))
    card(fp='a')
    assert cloud.notify() == 1 and '1 concurso na lista' in sent[0]
    assert cloud.notify() == 0 and len(sent) == 1
    assert kv.get('telegram_started') == '1'


def test_alerts_of_discarded_cards_are_not_sent(monkeypatch):
    from app import config, notifications

    sent = []
    monkeypatch.setattr(config, 'telegram', lambda: {'token': 't', 'chat_id': 'c'})
    monkeypatch.setattr(notifications, '_telegram', lambda text: sent.append(text) or True)
    live, gone = card(fp='a'), card(title='Velho', fp='b')
    repo.add_alert('k1', 'new', 'Aviso útil', live)
    repo.add_alert('k2', 'new', 'Aviso descartado', gone)
    repo.update_opportunity(gone, {'dismissed': 1})
    assert notifications.dispatch()['sent'] == 1
    assert 'Aviso útil' in sent[0] and 'descartado' not in sent[0]
    assert notifications.dispatch()['sent'] == 0


def test_notify_does_nothing_without_telegram(monkeypatch):
    monkeypatch.setattr(telegram, 'configured', lambda: False)
    assert cloud.notify() == 0
