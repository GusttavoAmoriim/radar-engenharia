"""Find the opening edital by itself and validate a contest without manual clicks.

Starts from the contest's official links (edital, official page, inscription page).
When a link is a page instead of the PDF, it looks for opening-edital links on it.
Facts the edital does not support are removed (and kept in the notes) instead of
blocking the whole validation.
"""

import json
import logging
from datetime import datetime, timedelta

from . import clock, evidence, kv, polite, textnorm
from . import repository as repo

LOG = logging.getLogger('radar.verification')
MAX_LINKS_PER_PAGE = 8
RETRY_AFTER = timedelta(hours=20)
LABELS = {
    'registration_start': 'início das inscrições',
    'registration_end': 'fim das inscrições',
    'exam_date': 'data da prova',
    'exam_in_sp': 'prova em SP',
    'work_in_sp': 'trabalho em SP',
    'salary_min': 'salário mínimo',
    'salary_max': 'salário máximo',
}


def start_urls(item):
    urls = []
    for key in ('notice_url', 'official_url', 'apply_url'):
        url = evidence.unwrap_viewer(item.get(key) or '')
        if url and evidence.official_url(url) and url not in urls:
            urls.append(url)
    return urls


def locate_proof(item, session=None):
    """Return the Proof of the first official opening edital that names the engineering role."""
    from . import collectors  # local import: collectors imports this module's neighbours

    position = item.get('position') or ''
    errors, seen = [], set()

    def attempt(url):
        seen.add(url)
        resolved, raw, mime = evidence.fetch_official(url, session)
        try:
            return evidence.prove_document(resolved, raw, mime, position), resolved, raw
        except ValueError as err:
            errors.append(str(err))
            return None, resolved, raw

    for url in start_urls(item):
        try:
            proof, resolved, raw = attempt(url)
        except polite.DomainCoolingDown:
            raise
        except Exception as err:
            errors.append(str(err))
            continue
        if proof:
            return proof
        if raw.startswith(b'%PDF'):
            continue
        html = evidence.decode_html(raw)
        links = [u for t, u in collectors.hrefs(html, resolved) if collectors.notice_anchor(t, u) and u not in seen]
        for link in list(dict.fromkeys(links))[:MAX_LINKS_PER_PAGE]:
            try:
                proof, _, _ = attempt(link)
            except polite.DomainCoolingDown:
                raise
            except Exception as err:
                errors.append(str(err))
                continue
            if proof:
                return proof
    if not errors:
        raise ValueError('Informe link direto do edital oficial primeiro')
    # The most specific reason is usually the last document actually read.
    raise ValueError(errors[-1] if len(errors) == 1 else f'Nenhum edital de abertura validado ({errors[-1]})')


def verify(oid, session=None):
    """Validate one contest. Returns (item, warnings). Raises ValueError when no edital proves it."""
    item = repo.fetch_one(oid)
    if not item:
        raise LookupError(oid)
    if not item.get('position') or not textnorm.is_target(item['position']):
        raise ValueError('Informe o cargo específico de engenharia civil ou mecânica')
    try:
        proof = locate_proof(item, session)
        item = fill_from_edital(item, proof)
        failures = evidence.assertion_failures(proof, item)
        warnings = []
        if failures:
            cleared = {}
            removed = []
            for field, _message in failures:
                cleared[field] = 0 if field in ('exam_in_sp', 'work_in_sp') else None
                removed.append(f'{LABELS.get(field, field)} ({item.get(field)})')
                warnings.append(LABELS.get(field, field))
            stamp = clock.now()[:10]
            note = f'Validação {stamp}: não encontrado no edital e removido: ' + ', '.join(removed) + '.'
            cleared['notes'] = ((item.get('notes') or '') + '\n' + note).strip()
            repo.update_opportunity(oid, cleared)
            item = repo.fetch_one(oid)
        repo.record_proof(oid, proof, item)
    except ValueError as err:
        remember(oid, False, str(err))
        raise
    remember(oid, True, 'Edital validado' + (' (sem: ' + ', '.join(warnings) + ')' if warnings else ''))
    return repo.fetch_one(oid), warnings


FILL_FIELDS = ('registration_start', 'registration_end', 'exam_date', 'salary_min', 'salary_max')


def fill_from_edital(item, proof):
    """Fill empty dates/salary that the edital states without ambiguity; never overwrite what is there."""
    facts = {
        k: v for k, v in evidence.extract_facts(proof, item.get('position') or '').items() if item.get(k) in (None, '')
    }
    if not facts:
        return hide_if_ended(item) if 'Preenchido a partir do edital' in (item.get('notes') or '') else item
    names = ', '.join(LABELS.get(k, k) for k in facts)
    stamp = clock.now()[:10]
    facts['notes'] = (
        (item.get('notes') or '') + f'\nPreenchido a partir do edital em {stamp}: {names}. Confira no documento.'
    ).strip()
    repo.update_opportunity(item['id'], facts)
    return hide_if_ended(repo.fetch_one(item['id']))


def hide_if_ended(item):
    ended = item.get('registration_end') and item['registration_end'] < clock.today().isoformat()
    untouched = not (item.get('favorite') or item.get('applied') or item.get('stage'))
    if ended and untouched:
        # An old contest the banca still lists (inscrições closed years ago) is not an opening.
        note = item['notes'] + '\nOcultado automaticamente: as inscrições deste edital já terminaram.'
        repo.update_opportunity(item['id'], {'dismissed': 1, 'notes': note})
        item = repo.fetch_one(item['id'])
    return item


def hide_old_autofilled():
    """Startup pass: hide cards whose dates came from the edital and show the registration already ended."""
    hidden = 0
    for item in repo.query_opportunities(include_dismissed=False):
        if 'Preenchido a partir do edital' in (item.get('notes') or '') and hide_if_ended(item).get('dismissed'):
            hidden += 1
    return hidden


def remember(oid, ok, message):
    kv.put(f'verify:{oid}', json.dumps({'ok': ok, 'message': message[:300], 'at': clock.now()}))


def last_result(oid):
    try:
        return json.loads(kv.get(f'verify:{oid}') or 'null')
    except ValueError:
        return None


def due(item, now=None):
    """Unverified engineering contests with official links, not retried within 20 hours after a failure."""
    if item.get('document_verified') or item.get('dismissed'):
        return False
    if not item.get('position') or not textnorm.is_target(item['position']) or not start_urls(item):
        return False
    end = item.get('registration_end')
    if end and end < clock.today().isoformat():
        return False
    last = last_result(item['id'])
    if last and not last.get('ok'):
        try:
            when = datetime.fromisoformat(last['at'])
        except (KeyError, ValueError):
            return True
        return (now or datetime.now(when.tzinfo)) - when >= RETRY_AFTER
    return True


def fill_missing_roles(session=None, limit=10):
    """Give the cargo to official-edital cards created without one, so they can be validated.

    Reads the card's own official links (never a gazette); the cargo comes from the edital text.
    Returns how many cards were filled.
    """
    from . import gazettes

    filled = tried = 0
    for item in repo.query_opportunities(include_dismissed=False):
        if tried >= limit:
            break
        cut = (item.get('position') or '').count('(') > (item.get('position') or '').count(')')
        if (item.get('position') and not cut) or item.get('document_verified') or not start_urls(item):
            continue
        if str(item.get('source', '')).startswith('Querido Diário'):
            continue
        tried += 1
        proof = None
        for url in start_urls(item):
            try:
                proof = evidence.notice_proof(url, session=session)
                break
            except polite.DomainCoolingDown:
                return filled
            except Exception as err:
                LOG.info('Cargo de %s: %s', item['title'], err)
        role = gazettes.role_of(proof.text) if proof else ''
        if role:
            note = (item.get('notes') or '') + f'\nCargo preenchido automaticamente a partir do edital: {role}.'
            repo.update_opportunity(item['id'], {'position': role, 'notes': note.strip()})
            filled += 1
    return filled


def auto_verify(session=None, limit=10):
    """Run by the collector: validate pending contests by itself. Returns (validated, failed)."""
    ok = failed = 0
    fill_missing_roles(session)
    for item in repo.query_opportunities(include_dismissed=False):
        if ok + failed >= limit:
            break
        if not due(item):
            continue
        try:
            verify(item['id'], session)
            ok += 1
        except polite.DomainCoolingDown as err:
            LOG.warning('Validação adiada (domínio em pausa): %s', err)
            remember(item['id'], False, str(err))
            failed += 1
        except Exception as err:
            LOG.info('Validação automática de %s: %s', item['title'], err)
            failed += 1
    return ok, failed
