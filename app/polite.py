"""Respectful outbound request scheduler for official public sites.

One serialized lane per hostname inside a process, and a persistent SQLite
reservation/circuit breaker shared across the API and scan worker. HTTP 403/429
are never defeated by identity rotation, headless-browser tricks or proxies.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from . import clock, config, database

LOG = logging.getLogger(__name__)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class DomainCoolingDown(RuntimeError):
    def __init__(self, host: str, status: int, until: float):
        self.host = host
        self.status = status
        self.until = until
        stamp = datetime.fromtimestamp(until, clock.TZ).strftime('%d/%m/%Y %H:%M')
        super().__init__(
            f'HTTP {status}: acesso oficial recusado/limitado por {host}; suspenso até {stamp} (São Paulo). Sem contornar bloqueio.'
        )


def hostname(url: str) -> str:
    return (urlparse(url).hostname or '').lower()


def host_lock(host: str) -> threading.Lock:
    with _LOCKS_GUARD:
        if host not in _LOCKS:
            _LOCKS[host] = threading.Lock()
        return _LOCKS[host]


def interval_seconds() -> float:
    # One official domain never receives bursts, even if several jobs are queued.
    return config.domain_interval_seconds()


def reserve(host: str, now: float | None = None) -> float:
    now = time.time() if now is None else now
    with database.DB_LOCK, database.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute(
            'SELECT next_at,blocked_until,last_status FROM host_pacing WHERE host=?', (host,)
        ).fetchone()
        if current and current['blocked_until'] > now:
            db.rollback()
            raise DomainCoolingDown(host, current['last_status'] or 429, current['blocked_until'])
        start = max(now, current['next_at'] if current else now)
        # Reserve slots transactionally; separate worker processes respect them.
        db.execute(
            """INSERT INTO host_pacing(host,next_at,blocked_until,last_status,updated_at)
          VALUES (?,?,?,?,?) ON CONFLICT(host) DO UPDATE SET
          next_at=excluded.next_at,updated_at=excluded.updated_at""",
            (host, start + interval_seconds(), 0.0, 0, clock.now()),
        )
        db.commit()
    return max(0.0, start - now)


def retry_after_seconds(value: str | None, now: float | None = None) -> float | None:
    if not value:
        return None
    now = time.time() if now is None else now
    try:
        return max(0.0, float(int(value.strip())))
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            return max(0.0, stamp.timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return None


def reject(host: str, status: int, retry_after: str | None = None, now: float | None = None) -> DomainCoolingDown:
    now = time.time() if now is None else now
    retry = retry_after_seconds(retry_after, now)
    # 403: no repeat for twelve hours. 429: respect Retry-After if provided,
    # otherwise wait three hours. Cap locally at 7 days to avoid overflow.
    cooldown = 12 * 3600 if status == 403 else (retry if retry is not None else 3 * 3600)
    until = now + max(60.0, min(7 * 86400.0, cooldown))
    with database.DB_LOCK, database.connection() as db:
        db.execute(
            """INSERT INTO host_pacing(host,next_at,blocked_until,last_status,updated_at)
          VALUES (?,?,?,?,?) ON CONFLICT(host) DO UPDATE SET
          blocked_until=MAX(host_pacing.blocked_until,excluded.blocked_until),
          last_status=excluded.last_status,updated_at=excluded.updated_at""",
            (host, until, until, status, clock.now()),
        )
        db.commit()
    LOG.warning(
        'Official domain %s returned %d, suspended until %s', host, status, datetime.fromtimestamp(until, clock.TZ)
    )
    return DomainCoolingDown(host, status, until)


def snapshot() -> dict[str, dict]:
    with database.connection() as db:
        try:
            rows = db.execute('SELECT host,next_at,blocked_until,last_status FROM host_pacing').fetchall()
        except Exception:
            return {}
    now = time.time()
    return {
        r['host']: {
            'blocked': r['blocked_until'] > now,
            'until': datetime.fromtimestamp(r['blocked_until'], clock.TZ).isoformat(timespec='minutes')
            if r['blocked_until'] > now
            else None,
            'status': r['last_status'],
        }
        for r in rows
    }


@contextmanager
def request_lane(host: str):
    # Network operation is under the per-host lock; different hosts are concurrent.
    with host_lock(host):
        wait = reserve(host)
        if wait:
            time.sleep(wait)
        yield
