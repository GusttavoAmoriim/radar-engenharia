from datetime import date

import pytest

from app import clock, database


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', str(tmp_path / 'radar.sqlite3'))
    monkeypatch.setenv('RADAR_PASSWORD', 'Very-Strong-Password-TEST-1234')
    monkeypatch.setenv('RADAR_COOKIE_SECURE', '0')
    monkeypatch.setenv('RADAR_PUBLIC', '1')
    monkeypatch.setenv('RADAR_MFA_ENCRYPTION_KEY', 'pjkUsvLXBbFH15KG_tAgBbB8x9MDE5c7qVmU2_XgEuI=')
    # Freeze the calendar: fixtures use October/2026 dates and must not expire with time.
    monkeypatch.setattr(clock, 'today', lambda: date(2026, 10, 15))
    database.init_db()
