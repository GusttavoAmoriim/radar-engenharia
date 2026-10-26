"""Small key/value store (table app_settings) for runtime state and admin settings."""

from . import database


def get(key, default=''):
    with database.connection() as db:
        row = db.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default


def put(key, value):
    with database.DB_LOCK, database.connection() as db:
        db.execute(
            'INSERT INTO app_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (key, value),
        )


def delete(key):
    with database.DB_LOCK, database.connection() as db:
        db.execute('DELETE FROM app_settings WHERE key=?', (key,))
