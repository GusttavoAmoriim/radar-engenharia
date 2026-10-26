"""No 403/429 retry loops, persistent backoff, and independent-source queue."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from app import collectors, database, evidence, polite
from app import repository as repo


class Response:
    def __init__(self, status, retry=None):
        self.status_code = status
        self.headers = {'Content-Type': 'text/html'}
        if retry is not None:
            self.headers['Retry-After'] = retry
        self.url = 'https://www.vunesp.com.br/cabertas.html'
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError('HTTP error')

    def iter_content(self, chunk_size):
        yield b'<html><body>Edital oficial</body></html>'


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self.response


def test_403_is_persisted_and_followup_does_not_make_http_request(monkeypatch):
    monkeypatch.setattr(polite.time, 'sleep', lambda seconds: None)
    bad = Session(Response(403))
    with pytest.raises(polite.DomainCoolingDown, match='HTTP 403'):
        evidence.fetch_official('https://www.vunesp.com.br/cabertas.html', session=bad, pace=True)
    assert bad.calls == 1
    assert bad.response.closed
    next_client = Session(Response(200))
    with pytest.raises(polite.DomainCoolingDown):
        evidence.fetch_official('https://www.vunesp.com.br/cabertas.html', session=next_client, pace=True)
    assert next_client.calls == 0  # no evasion, no pointless repeat
    assert polite.snapshot()['www.vunesp.com.br']['blocked'] is True


def test_429_retry_after_and_default_wait():
    now = time.time()
    with pytest.raises(polite.DomainCoolingDown):
        raise polite.reject('www.vunesp.com.br', 429, '7200', now=now)
    with database.connection() as db:
        row = db.execute('SELECT blocked_until FROM host_pacing WHERE host=?', ('www.vunesp.com.br',)).fetchone()
    assert row['blocked_until'] - now == pytest.approx(7200, abs=1)
    assert (
        polite.retry_after_seconds(
            'Thu, 17 Oct 2030 12:00:00 GMT', now=datetime(2030, 10, 17, 11, 0, tzinfo=UTC).timestamp()
        )
        == 3600
    )
    polite.reject('www.fgv.br', 429, None, now=now)
    with database.connection() as db:
        row2 = db.execute('SELECT blocked_until FROM host_pacing WHERE host=?', ('www.fgv.br',)).fetchone()
    assert row2['blocked_until'] - now == pytest.approx(3 * 3600, abs=1)


def test_no_concurrent_requests_same_hostname(monkeypatch):
    monkeypatch.setattr(polite, 'interval_seconds', lambda: 0)
    guard = threading.Lock()
    state = {'active': 0, 'peak': 0}

    def perform():
        with polite.request_lane('www.vunesp.com.br'):
            with guard:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            time.sleep(0.02)
            with guard:
                state['active'] -= 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: perform(), range(4)))
    assert state['peak'] == 1


def test_different_official_sources_use_parallel_queue(monkeypatch):
    sources = (
        collectors.Source('Org 1', 'https://www.vunesp.com.br/cabertas.html'),
        collectors.Source('Org 2', 'https://conhecimento.fgv.br/concursos'),
        collectors.Source('Org 3', 'https://www.cebraspe.org.br/concursos/'),
    )
    barrier = threading.Barrier(3)
    monkeypatch.setattr(collectors, 'SOURCES', sources)
    monkeypatch.setenv('RADAR_SOURCE_WORKERS', '3')

    def scan(source, session=None):
        barrier.wait(timeout=2)
        return 1, 1, True

    monkeypatch.setattr(collectors, 'scan_source', scan)
    report = collectors.run_all()
    assert report['state'] == 'ok'
    assert report['sources'] == 3 and report['new'] == 3


def test_source_blocked_is_not_reported_as_success(monkeypatch):
    def blocked(*args, **kwargs):
        raise polite.DomainCoolingDown('www.vunesp.com.br', 403, time.time() + 12 * 3600)

    monkeypatch.setattr(evidence, 'fetch_official', blocked)
    assert collectors.scan_source(collectors.SOURCES[0]) == (0, 0, False)
    assert repo.source_health()[0]['state'] == 'blocked'
