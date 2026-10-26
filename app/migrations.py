"""Ordered, append-only schema migrations.

Never edit a released migration: add a new one at the end. Each runs once and is recorded in
`schema_migrations`. Migration 1 is the v2.x schema, written with IF NOT EXISTS so databases
created by v2.x (which had no migration table) are adopted without changes.
"""

V2_SCHEMA = """
                    CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL, agency TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '',
            salary_min REAL, salary_max REAL, registration_start TEXT, registration_end TEXT,
            exam_date TEXT, exam_cities TEXT NOT NULL DEFAULT '', work_cities TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '', official_url TEXT NOT NULL DEFAULT '',
            apply_url TEXT NOT NULL DEFAULT '', notice_url TEXT NOT NULL DEFAULT '',
            discovery_url TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'discovery', reviewed INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '', exam_in_sp INTEGER NOT NULL DEFAULT 0,
            work_in_sp INTEGER NOT NULL DEFAULT 0, national INTEGER NOT NULL DEFAULT 0,
            favorite INTEGER NOT NULL DEFAULT 0, applied INTEGER NOT NULL DEFAULT 0,
            dismissed INTEGER NOT NULL DEFAULT 0, status_override TEXT,
            type TEXT NOT NULL DEFAULT 'concurso', observed_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_seen TEXT NOT NULL
          );
          CREATE INDEX IF NOT EXISTS idx_end ON opportunities(registration_end);
          CREATE INDEX IF NOT EXISTS idx_confidence ON opportunities(confidence);
          CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS host_pacing (
            host TEXT PRIMARY KEY, next_at REAL NOT NULL DEFAULT 0,
            blocked_until REAL NOT NULL DEFAULT 0, last_status INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
          );
          CREATE TABLE IF NOT EXISTS notice_evidence (
            opportunity_id INTEGER PRIMARY KEY REFERENCES opportunities(id) ON DELETE CASCADE,
            notice_url TEXT NOT NULL, sha256 TEXT NOT NULL, checked_at TEXT NOT NULL,
            role_excerpt TEXT NOT NULL, validated_dates TEXT NOT NULL DEFAULT '',
            validated_salary INTEGER NOT NULL DEFAULT 0
          );
          CREATE TABLE IF NOT EXISTS notice_watches (
            page_url TEXT PRIMARY KEY, document_links TEXT NOT NULL DEFAULT '',
            checked_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS scan_candidates (
            id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
            title TEXT NOT NULL, notice_url TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL,last_seen TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL, expires_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS login_failures (
            ip TEXT PRIMARY KEY, attempts INTEGER NOT NULL, blocked_until TEXT, updated_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
            source TEXT NOT NULL, state TEXT NOT NULL, found INTEGER NOT NULL DEFAULT 0,
            added INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT ''
          );
          CREATE TABLE IF NOT EXISTS watched_pages (
            url TEXT PRIMARY KEY, label TEXT NOT NULL, digest TEXT NOT NULL DEFAULT '',
            checked_at TEXT, changed_at TEXT, error TEXT NOT NULL DEFAULT ''
          );
          CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, unique_key TEXT UNIQUE NOT NULL,
            opportunity_id INTEGER, kind TEXT NOT NULL, text TEXT NOT NULL,
            created_at TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
          );
        """

ACCOUNT_SECURITY = """
CREATE TABLE IF NOT EXISTS admin_sessions (
  id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, csrf_hash TEXT NOT NULL,
  ip TEXT NOT NULL DEFAULT '', user_agent TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS trusted_devices (
  id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, ip TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS security_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, ip TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_security_events_at ON security_events(at);
DROP TABLE IF EXISTS auth_sessions;
"""

STAGE_SQL = "ALTER TABLE opportunities ADD COLUMN stage TEXT NOT NULL DEFAULT '';"

MIGRATIONS = [
    (1, 'v2 schema', V2_SCHEMA),
    (2, 'account security: sessions with devices, trusted devices, security events', ACCOUNT_SECURITY),
    (3, 'acompanhamento: etapa pessoal do concurso', STAGE_SQL),
]
