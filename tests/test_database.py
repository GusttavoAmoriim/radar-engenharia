import sqlite3

from app import database, manage
from app import repository as repo
from app.migrations import MIGRATIONS, V2_SCHEMA


def test_fresh_database_records_every_migration():
    assert database.schema_version() == MIGRATIONS[-1][0]
    with database.connection() as db:
        rows = db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall()
    assert [r['version'] for r in rows] == [m[0] for m in MIGRATIONS]


def test_migrate_is_idempotent():
    before = database.schema_version()
    assert database.migrate() == before
    assert database.schema_version() == before


def test_v2_database_is_adopted_without_losing_data(tmp_path, monkeypatch):
    legacy = tmp_path / 'legacy.sqlite3'
    con = sqlite3.connect(legacy)
    con.executescript(V2_SCHEMA)
    con.execute(
        'INSERT INTO opportunities(fingerprint,title,created_at,updated_at,last_seen,favorite,notes)'
        " VALUES ('fp','Concurso antigo','2026-01-01','2026-01-01','2026-01-01',1,'minha anotação')"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(database, 'DB_PATH', str(legacy))
    assert database.migrate() == MIGRATIONS[-1][0]
    item = repo.query_opportunities()[0]
    assert item['title'] == 'Concurso antigo' and item['favorite'] == 1 and item['notes'] == 'minha anotação'
    backups = list(tmp_path.glob('legacy.pre-migration-*.sqlite3'))
    assert len(backups) == 1, 'existing data must be backed up before migrating'


def test_connection_rolls_back_on_error():
    try:
        with database.connection() as db:
            db.execute("INSERT INTO app_settings(key,value) VALUES ('x','1')")
            raise RuntimeError('boom')
    except RuntimeError:
        pass
    with database.connection() as db:
        assert db.execute("SELECT 1 FROM app_settings WHERE key='x'").fetchone() is None


def test_manual_backup_command(tmp_path):
    target = tmp_path / 'copia.sqlite3'
    assert manage.main(['backup', str(target)]) == 0
    con = sqlite3.connect(target)
    assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='opportunities'").fetchone()[0] == 1
    con.close()
