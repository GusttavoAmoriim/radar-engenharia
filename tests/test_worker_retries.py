from app import collectors, kv, worker


def test_worker_does_not_retry_official_sources_forever(monkeypatch):
    calls = []

    def partial():
        calls.append(1)
        return {'state': 'partial'}

    monkeypatch.setattr(collectors, 'run_all', partial)
    assert worker.tick() == 'partial'
    assert worker.tick() == 'partial'
    assert worker.tick() == 'cooldown'
    assert len(calls) == 2
    assert not kv.get('last_complete_slot')


def test_worker_success_only_marks_complete(monkeypatch):
    monkeypatch.setattr(collectors, 'run_all', lambda: {'state': 'ok'})
    assert worker.tick() == 'complete'
    assert worker.tick() == 'already'
