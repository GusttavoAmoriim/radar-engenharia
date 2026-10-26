"""SQLite access: connections, the write lock, migrations and backups."""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import clock, config
from .migrations import MIGRATIONS

DB_PATH = config.db_path()
DB_LOCK = threading.RLock()
BACKUPS_KEPT = 3


@contextmanager
def connection():
    """Yield a connection; commit on success, roll back on error and always close."""
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=20000')
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def schema_version():
    with connection() as db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)'
        )
        row = db.execute('SELECT MAX(version) AS v FROM schema_migrations').fetchone()
    return row['v'] or 0


def _has_user_data(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return 'opportunities' in tables and db.execute('SELECT 1 FROM opportunities LIMIT 1').fetchone() is not None


def backup(destination=None, label='manual'):
    """Consistent online copy using SQLite's backup API. Returns the file path."""
    source = Path(DB_PATH)
    stamp = clock.now().replace(':', '').replace('-', '')[:15]
    target = Path(destination) if destination else source.with_name(f'{source.stem}.{label}-{stamp}.sqlite3')
    target.parent.mkdir(parents=True, exist_ok=True)
    with DB_LOCK:
        src = sqlite3.connect(str(source))
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    return target


def _prune_backups():
    source = Path(DB_PATH)
    old = sorted(source.parent.glob(f'{source.stem}.pre-migration-*.sqlite3'))
    for path in old[:-BACKUPS_KEPT]:
        path.unlink(missing_ok=True)


def migrate():
    """Apply pending migrations. Existing data is backed up first (last 3 backups kept)."""
    current = schema_version()
    pending = [m for m in MIGRATIONS if m[0] > current]
    if not pending:
        return current
    with connection() as db:
        needs_backup = _has_user_data(db)
    if needs_backup:
        backup(label=f'pre-migration-v{current}-to-v{pending[-1][0]}')
        _prune_backups()
    with DB_LOCK, connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        for version, name, script in pending:
            db.executescript(script)
            db.execute(
                'INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)',
                (version, name, clock.now()),
            )
    return pending[-1][0]


def init_db():
    return migrate()
