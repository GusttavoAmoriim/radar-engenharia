"""Civil and mechanical engineering contests found in official municipal gazettes through the Querido Diário public API.

Many contests organised by banks that refuse automated access (Vunesp, for example)
are published as an edital or an extract in the municipality's Diário Oficial.
Querido Diário (Open Knowledge Brasil) indexes those gazettes and offers a public
search API meant for this kind of use. Results are discoveries for review: the
gazette is not the edital, so nothing found here is marked as confirmed.
"""

import hashlib
import html
import json
import logging
import re
from datetime import timedelta
from urllib.parse import urlencode

from . import clock, evidence, polite, portals, textnorm
from . import repository as repo

LOG = logging.getLogger('radar.gazettes')
# One simple query per term. A single query with operators made the public API
# answer HTTP 500, and narrow queries keep each search light for their servers.
TERMS = (
    'engenheiro civil',
    'engenheiro mecânico',
    'engenharia civil',
    'engenharia mecânica',
)
# Teaching and temporary selections are announced as "processo seletivo", not "concurso público".
KINDS = ('concurso público', 'processo seletivo')
LOOKBACK_DAYS = 21
PAGE_SIZE = 20
MAX_NEW_PER_RUN = 25
# Publications about contests that are already over (or that are not openings).
SKIP = (
    'resultado',
    'homologacao',
    'homologa',
    'convocacao',
    'convoca ',
    'gabarito',
    'nomeacao',
    'nomear',
    'nomeia',
    'classificacao final',
    'posse',
    'exoneracao',
    # Appointment acts: someone already approved in an earlier contest being hired. Not an opening.
    'aprovacao e classificacao',
    'tendo em vista a aprovacao',
    'para exercer o cargo',
    # In procurement law a "concurso" is also a design competition, and gazettes are full of
    # engineering services being tendered: none of that is a job opening.
    # Ranking lists of a contest that already had its exam.
    'classificados em ordem',
    'ordem decrescente',
    'lista de classificados',
    'relacao de classificados',
    'classificacao preliminar',
    'concurso de projeto',
    'concurso de ideias',
    'licitacao',
    'pregao',
    'tomada de precos',
)
ROLE = re.compile(
    r'\b(engenh(?:eiros?|eiras?|aria)(?:\((?:a|o)\))?'
    r'(?:[\s\-–—/:()]+[^\W\d_]+){0,3}?'
    r'[\s\-–—/:()]+(?:civil|civis|mec[âa]nic[oa]s?)\b(?:\((?:a|o)\))?)',
    re.I,
)
# A CPF number means the excerpt is about a person (an appointment, a dismissal...), never an opening.
CPF = re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b')
LINK = re.compile(r'(?:https?://|www\.)[^\s<>"\')\],;]+', re.I)


def clean(text):
    text = re.sub(r'<[^>]+>', ' ', html.unescape(str(text or '')))
    return re.sub(r'\s+', ' ', text).strip()


def blocked(excerpt):
    """True when the text is about something other than an opening: a person (CPF), a result, a ranking...

    Safe on a shortened excerpt: a word that is present in the cut text is present in the whole one.
    """
    t = textnorm.fold(excerpt)
    return bool(CPF.search(excerpt)) or any(word in t for word in SKIP)


def relevant(excerpt):
    """An excerpt about an engineering contest that is open or about to open."""
    t = textnorm.fold(excerpt)
    if blocked(excerpt):
        return False
    if 'concurso' not in t and 'processo seletivo' not in t:
        return False
    if not textnorm.is_target(excerpt):
        return False
    return any(word in t for word in ('edital', 'abertura', 'inscri'))


def dismiss_stale_discoveries():
    """Hide cards found by an older, looser filter whose saved excerpt the current filter blocks.

    Only untouched discoveries are hidden: a card you starred, marked or reviewed is never dismissed.
    """
    hidden = 0
    for item in repo.query_opportunities():
        notes = item.get('notes') or ''
        untouched = not (item.get('reviewed') or item.get('favorite') or item.get('applied') or item.get('stage'))
        if item.get('dismissed') or not untouched or not item.get('source', '').startswith('Querido Diário'):
            continue
        if 'Trecho:' in notes and blocked(notes):
            note = notes + '\nOcultado automaticamente: o trecho do diário não é a abertura de um concurso.'
            repo.update_opportunity(item['id'], {'dismissed': 1, 'notes': note})
            hidden += 1
    return hidden


def role_of(text):
    for match in ROLE.finditer(text):
        role = match.group(1).strip(' -–')
        if role.count('(') > role.count(')'):
            # "Engenharia (graduação civil)": keep the closing parenthesis the pattern stopped before.
            close = text.find(')', match.end(), match.end() + 20)
            role = role + text[match.end() : close + 1] if close != -1 else role.rsplit('(', 1)[0].strip(' -–')
        # Same rule as everywhere else: "Engenheiro ... Polícia Civil" is not a civil engineer.
        if textnorm.is_target(role):
            role = role[:1].upper() + role[1:]
            # "Professor de Engenharia Civil" / "Professor ... graduação em Engenharia Civil": keep the teaching post.
            if textnorm.is_teaching(text[max(0, match.start() - 80) : match.start()]):
                return f'Professor – {role}'
            return role
    return ''


def official_links(text):
    links = []
    for raw in LINK.findall(text):
        url = raw.rstrip('.')
        if url.lower().startswith('www.'):
            url = 'https://' + url
        url = 'https://' + url.split('://', 1)[1]
        if evidence.official_url(url) and url not in links:
            links.append(url)
    return links


def search_urls(source):
    since = (clock.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    base = source.url.split('?', 1)[0]
    for kind in KINDS:
        for term in TERMS:
            yield base + '?' + urlencode(search_params(kind, term, since))


def search_params(kind, term, since):
    return {
        'querystring': f'"{kind}" "{term}"',
        'published_since': since,
        'excerpt_size': 500,
        'number_of_excerpts': 2,
        'size': PAGE_SIZE,
    }


def fetch_gazettes(source, session):
    """Run every term; a failing search does not lose the others. Returns (gazettes, errors)."""
    found, errors, seen = [], [], set()
    for url in search_urls(source):
        try:
            _, raw, _ = evidence.fetch_official(url, session, data_api=True)
            data = json.loads(raw.decode('utf-8'))
        except polite.DomainCoolingDown:
            raise
        except json.JSONDecodeError:
            errors.append('resposta não é JSON')
            continue
        except Exception as err:
            # requests puts the whole (long) URL in the message; the term is enough.
            errors.append(str(err).split(' for url:')[0])
            continue
        for gazette in data.get('gazettes') or []:
            key = gazette.get('url') or gazette.get('txt_url')
            if key and key not in seen:
                seen.add(key)
                found.append(gazette)
    return found, errors


def scan_source(source, session=None):
    sid = repo.scan_start(source.name)
    found = added = 0
    try:
        results, errors = fetch_gazettes(source, session)
        if errors and len(errors) == len(TERMS) * len(KINDS):
            raise ValueError(f'API do Querido Diário falhou em todas as buscas: {errors[0]}')
        for gazette in results:
            uf = str(gazette.get('state_code') or '').upper()
            if source.uf and uf != source.uf:
                continue
            gazette_url = str(gazette.get('url') or gazette.get('txt_url') or '')
            if not gazette_url.startswith('https://'):
                continue
            excerpts = [clean(e) for e in gazette.get('excerpts') or []]
            hits = [e for e in excerpts if relevant(e)]
            if not hits:
                continue
            found += 1
            town = clean(gazette.get('territory_name')) or 'Município'
            date = str(gazette.get('date') or '')[:10]
            when = '/'.join(reversed(date.split('-'))) if date else ''
            text = ' '.join(hits)
            role = role_of(text)
            links = official_links(text)
            temporary = textnorm.is_temporary(text)
            kind = 'seleção temporária' if temporary else 'concurso'
            title = f'{town}/{uf} — {kind} com vaga de engenharia (Diário Oficial de {when})'
            repo.upsert_candidate(gazette_url, source.name, title, '', state='gazette_eng', detail=hits[0][:300])
            if added >= MAX_NEW_PER_RUN:
                continue
            item = {
                'title': title,
                'agency': f'{town}/{uf}',
                'position': role,
                'type': 'pss' if temporary else 'concurso',
                'state': uf if re.fullmatch(r'[A-Z]{2}', uf) else '',
                'source': source.name,
                'official_url': links[0]
                if links
                else (portals.for_territory(gazette.get('territory_id')) or gazette_url),
                'notice_url': next((u for u in links if u.lower().endswith('.pdf')), ''),
                'confidence': 'discovery',
                'reviewed': 0,
                'notes': (
                    f'Encontrado no Diário Oficial de {town}/{uf} de {when}, via Querido Diário. '
                    f'Trecho: “{hits[0][:400]}”. Diário: {gazette_url}. '
                    'Confira o edital oficial antes de se inscrever.'
                ),
                'fingerprint': hashlib.sha256(('gazette|' + gazette_url).encode()).hexdigest()[:32],
            }
            oid, created = repo.upsert(item)
            if not created and temporary:
                repo.update_opportunity(oid, {'type': 'pss'})
            if created:
                added += 1
                repo.add_alert(
                    'new-gazette:' + item['fingerprint'],
                    'new',
                    f'Possível {"seleção temporária" if temporary else "concurso"} de engenharia no Diário Oficial de {town}/{uf}: {role or "cargo a conferir"}.',
                    oid,
                )
        if errors:
            repo.scan_finish(
                sid,
                found,
                added,
                error=f'Cobertura PARCIAL: {len(errors)} de {len(TERMS) * len(KINDS)} buscas falharam ({errors[0]})',
            )
            return found, added, False
        repo.scan_finish(sid, found, added)
        return found, added, True
    except polite.DomainCoolingDown as ex:
        repo.scan_finish(sid, found, added, error=str(ex), state='blocked')
        return found, added, False
    except Exception as ex:
        LOG.warning('Querido Diário: %s', ex)
        repo.scan_finish(sid, found, added, error=str(ex))
        return found, added, False
