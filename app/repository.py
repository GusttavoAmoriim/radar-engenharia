"""Persistence of opportunities, proofs, scans, candidates and alerts."""

import hashlib
import json
import re
from datetime import date

from . import clock, database, kv, status_rules
from .textnorm import NO_ROLE, fold

FIELDS = (
    'title',
    'agency',
    'position',
    'salary_min',
    'salary_max',
    'registration_start',
    'registration_end',
    'exam_date',
    'exam_cities',
    'work_cities',
    'state',
    'official_url',
    'apply_url',
    'notice_url',
    'discovery_url',
    'source',
    'confidence',
    'reviewed',
    'notes',
    'exam_in_sp',
    'work_in_sp',
    'national',
    'favorite',
    'applied',
    'stage',
    'dismissed',
    'status_override',
    'type',
    'observed_at',
)
DATE_FIELDS = ('registration_start', 'registration_end', 'exam_date')
URL_FIELDS = ('official_url', 'apply_url', 'notice_url', 'discovery_url')


def fingerprint(title, agency='', position='', official_url=''):
    # Official notice URL wins when available, otherwise stable normalized title+agency.
    raw = '|'.join((agency, title, position, official_url.strip().split('#')[0]))
    return hashlib.sha256(fold(raw).encode()).hexdigest()[:32]


TYPES = ('concurso', 'pss')
STAGES = ('', 'interesse', 'inscrito', 'prova', 'resultado', 'desisti')


def validate(data, partial=False):
    if not partial and not (data.get('title') or '').strip():
        raise ValueError('Nome/título é obrigatório')
    for k in DATE_FIELDS:
        if data.get(k):
            try:
                date.fromisoformat(data[k])
            except (ValueError, TypeError):
                raise ValueError(f'{k} deve estar no formato YYYY-MM-DD') from None
    for k in URL_FIELDS:
        if data.get(k) and not str(data[k]).startswith(('https://', 'http://')):
            raise ValueError(f'{k} deve começar por https:// ou http://')
    for k in ('salary_min', 'salary_max'):
        if data.get(k) is not None and (not isinstance(data[k], (int, float)) or data[k] < 0):
            raise ValueError(f'{k} deve ser número não negativo')
    if data.get('confidence') is not None and data['confidence'] not in ('official', 'reported', 'discovery'):
        raise ValueError('Origem de confiança inválida')
    if data.get('type') is not None and data['type'] not in TYPES:
        raise ValueError('Tipo inválido')
    if data.get('stage') is not None and data['stage'] not in STAGES:
        raise ValueError('Etapa inválida')
    if data.get('status_override') and data['status_override'] not in ('announced', 'suspended', 'cancelled', 'open'):
        raise ValueError('Status manual inválido')


def upsert(data, *, enrich_only=True):
    """New discoveries never overwrite already reviewed details or verified dates."""
    validate(data)
    fp = data.get('fingerprint') or fingerprint(
        data['title'], data.get('agency', ''), data.get('position', ''), data.get('official_url', '')
    )
    stamp = clock.now()
    with database.DB_LOCK, database.connection() as db:
        previous = db.execute('SELECT * FROM opportunities WHERE fingerprint=?', (fp,)).fetchone()
        if previous:
            payload = {}
            if not enrich_only or not previous['reviewed']:
                for key in FIELDS:
                    if key in data and data[key] is not None and (not enrich_only or previous[key] in (None, '', 0)):
                        payload[key] = data[key]
            payload['last_seen'] = stamp
            if payload:
                payload['updated_at'] = stamp
            keys = list(payload)
            db.execute(
                f'UPDATE opportunities SET {", ".join(k + "=?" for k in keys)} WHERE fingerprint=?',
                [payload[k] for k in keys] + [fp],
            )
            db.commit()
            return previous['id'], False
        values = {k: data[k] for k in FIELDS if k in data}
        values.update(fingerprint=fp, created_at=stamp, updated_at=stamp, last_seen=stamp)
        keys = list(values)
        cur = db.execute(
            f'INSERT INTO opportunities ({", ".join(keys)}) VALUES ({", ".join("?" for _ in keys)})',
            list(values.values()),
        )
        db.commit()
        return cur.lastrowid, True


def fetch_one(oid):
    with database.connection() as db:
        row = db.execute('SELECT * FROM opportunities WHERE id=?', (oid,)).fetchone()
    return status_rules.present(attach_proof(dict(row))) if row else None


def query_opportunities(include_dismissed=True):
    with database.connection() as db:
        rows = db.execute('SELECT * FROM opportunities').fetchall()
    result = [status_rules.present(attach_proof(dict(r))) for r in rows if include_dismissed or not r['dismissed']]
    return sorted(
        result,
        key=lambda r: (
            -int(r['favorite']),
            -r['priority'],
            r['days_left'] if r['days_left'] is not None else 9999,
            -int(r['salary_highlight']),
            -r['id'],
        ),
    )


def update_opportunity(oid, payload):
    # Any edits to evidence-bearing facts revoke the proof instead of keeping a false 'confirmed' badge.
    restricted = {
        'confidence',
        'reviewed',
        'status_override',
        'official_url',
        'notice_url',
        'apply_url',
        'registration_start',
        'registration_end',
        'exam_date',
        'position',
        'salary_min',
        'salary_max',
        'exam_cities',
        'work_cities',
        'exam_in_sp',
        'work_in_sp',
        'national',
    }
    filtered = {k: v for k, v in payload.items() if k in FIELDS and k not in ('confidence', 'reviewed')}
    if not filtered:
        raise ValueError('Nenhum campo válido')
    validate(filtered, partial=True)
    with database.DB_LOCK, database.connection() as db:
        existing = db.execute('SELECT * FROM opportunities WHERE id=?', (oid,)).fetchone()
        if not existing:
            return False
        revoke = any(k in restricted and filtered[k] != existing[k] for k in filtered)
        filtered['updated_at'] = clock.now()
        db.execute(
            f'UPDATE opportunities SET {", ".join(k + "=?" for k in filtered)} WHERE id=?',
            list(filtered.values()) + [oid],
        )
        if revoke:
            db.execute('DELETE FROM notice_evidence WHERE opportunity_id=?', (oid,))
            db.execute("UPDATE opportunities SET reviewed=0,confidence='discovery' WHERE id=?", (oid,))
        db.commit()
    return True


def scan_start(source):
    with database.DB_LOCK, database.connection() as db:
        cur = db.execute(
            'INSERT INTO scan_runs(started_at,source,state) VALUES (?, ?, ?)', (clock.now(), source, 'running')
        )
        db.commit()
        return cur.lastrowid


def scan_finish(run_id, found=0, added=0, error='', state=None):
    with database.DB_LOCK, database.connection() as db:
        db.execute(
            'UPDATE scan_runs SET finished_at=?, found=?, added=?, error=?, state=? WHERE id=?',
            (clock.now(), found, added, error[:1200], state or ('failed' if error else 'ok'), run_id),
        )
        db.commit()


def prune_candidates(days=30):
    """Drop triage rows that are obsolete: viewer-wrapped FCC links, documents already known
    not to be opening engineering editais, robots-skipped service pages and anything unseen for a month."""
    from datetime import datetime, timedelta

    cutoff = (datetime.now(clock.TZ) - timedelta(days=days)).isoformat(timespec='seconds')
    with database.DB_LOCK, database.connection() as db:
        cur = db.execute(
            """DELETE FROM scan_candidates WHERE url LIKE '%/rybena/%'
               OR (state='needs_review' AND (detail LIKE 'O arquivo não demonstra ser edital%'
                   OR detail LIKE 'Não foi comprovado que o documento seja o edital inicial%'
                   OR detail LIKE ?))
               OR (state='fetch_failed' AND detail LIKE 'robots.txt %')
               OR last_seen < ?""",
            (NO_ROLE + '%', cutoff),
        )
        db.commit()
        return cur.rowcount


CPF = re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b')
SCRUBBED = (
    'Removido automaticamente: o trecho do diário citava uma pessoa (ato de nomeação), não a abertura de um concurso.'
)


def scrub_personal_data():
    """Earlier gazette excerpts could name a person (CPF). Hide those cards and wipe the text. Returns how many."""
    changed = 0
    with database.DB_LOCK, database.connection() as db:
        for row in db.execute('SELECT id, notes FROM opportunities').fetchall():
            if CPF.search(row['notes'] or ''):
                db.execute('UPDATE opportunities SET notes=?, dismissed=1 WHERE id=?', (SCRUBBED, row['id']))
                changed += 1
        for row in db.execute('SELECT id, detail FROM scan_candidates').fetchall():
            if CPF.search(row['detail'] or ''):
                db.execute('UPDATE scan_candidates SET detail=? WHERE id=?', (SCRUBBED, row['id']))
                changed += 1
        db.commit()
    return changed


def close_interrupted_runs():
    """A restart can cut a collection in half; do not leave those sources showing 'running' forever."""
    with database.DB_LOCK, database.connection() as db:
        cur = db.execute(
            "UPDATE scan_runs SET finished_at=?, state='failed', error=? WHERE state='running' AND finished_at IS NULL",
            (clock.now(), 'Interrompida: o serviço foi reiniciado durante a coleta; será refeita na próxima rodada'),
        )
        db.commit()
        return cur.rowcount


def source_health():
    with database.connection() as db:
        rows = db.execute(
            'SELECT s.* FROM scan_runs s JOIN (SELECT source, MAX(id) AS id FROM scan_runs GROUP BY source) l ON s.id=l.id ORDER BY s.source'
        ).fetchall()
        return [dict(r) for r in rows]


def add_alert(key, kind, msg, oid=None):
    with database.DB_LOCK, database.connection() as db:
        cur = db.execute(
            'INSERT OR IGNORE INTO alerts (unique_key,kind,text,opportunity_id,created_at) VALUES (?,?,?,?,?)',
            (key, kind, msg, oid, clock.now()),
        )
        db.commit()
        return bool(cur.rowcount)


def get_alerts(limit=100):
    with database.connection() as db:
        return [dict(r) for r in db.execute('SELECT * FROM alerts ORDER BY id DESC LIMIT ?', (limit,))]


def attach_proof(item):
    with database.connection() as db:
        row = db.execute('SELECT * FROM notice_evidence WHERE opportunity_id=?', (item['id'],)).fetchone()
    item['document_verified'] = bool(row)
    item['salary_verified'] = bool(row and row['validated_salary'])
    item['proof'] = (
        {k: row[k] for k in ('notice_url', 'sha256', 'checked_at', 'role_excerpt', 'validated_dates')} if row else None
    )
    try:
        item['last_check'] = json.loads(kv.get(f'verify:{item["id"]}') or 'null')
    except ValueError:
        item['last_check'] = None
    return item


def record_proof(oid, proof, details):
    # Only the dedicated verification endpoint may establish confirmed status.
    with database.DB_LOCK, database.connection() as db:
        old = db.execute('SELECT id FROM opportunities WHERE id=?', (oid,)).fetchone()
        if old is None:
            raise ValueError('Concurso não encontrado')
        dates = ','.join(k for k in DATE_FIELDS if details.get(k))
        salary = int(any(details.get(k) is not None for k in ('salary_min', 'salary_max')))
        db.execute(
            """INSERT INTO notice_evidence(opportunity_id,notice_url,sha256,checked_at,role_excerpt,validated_dates,validated_salary)
                     VALUES(?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET
                     notice_url=excluded.notice_url,sha256=excluded.sha256,checked_at=excluded.checked_at,
                     role_excerpt=excluded.role_excerpt,validated_dates=excluded.validated_dates,validated_salary=excluded.validated_salary""",
            (oid, proof.url, proof.sha256, clock.now(), proof.role_excerpt, dates, salary),
        )
        db.execute(
            "UPDATE opportunities SET confidence='official',reviewed=1,notice_url=?,type=?,updated_at=?,status_override=CASE WHEN status_override='open' THEN NULL ELSE status_override END WHERE id=?",
            (proof.url, 'pss' if getattr(proof, 'temporary', False) else 'concurso', clock.now(), oid),
        )
        db.commit()


def upsert_candidate(url, source, title, notice_url='', state='pending', detail=''):
    with database.DB_LOCK, database.connection() as db:
        db.execute(
            """INSERT INTO scan_candidates(url,source,title,notice_url,state,detail,first_seen,last_seen)
           VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET notice_url=excluded.notice_url,
           state=excluded.state, detail=excluded.detail, last_seen=excluded.last_seen""",
            (url, source, title[:240], notice_url, state, detail[:500], clock.now(), clock.now()),
        )
        db.commit()


def candidates():
    with database.connection() as db:
        return [dict(r) for r in db.execute('SELECT * FROM scan_candidates ORDER BY last_seen DESC LIMIT 200')]
