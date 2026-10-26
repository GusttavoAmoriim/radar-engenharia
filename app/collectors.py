"""Official-only adapters. No Google, news syndication, PCI or inferred publication dates.
Conservative: a notice must be fetched and contain a civil/mechanical engineering role before surfacing.
"""

import hashlib
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import clock, config, database, evidence, polite, robots, sources, textnorm
from . import repository as repo

LOG = logging.getLogger(__name__)
Source = sources.Source
LOCK = threading.Lock()


SOURCES = sources.active(sources.load())


def hrefs(html, base):
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.select('a[href]'):
        url = evidence.unwrap_viewer(urljoin(base, a.get('href', '')))
        if not evidence.official_url(url):
            continue
        text = ' '.join(a.stripped_strings).strip()[:300]
        if urlparse(url).fragment:
            url = url.split('#', 1)[0]
        yield text, url


def looks_detail(source, text, url):
    p = urlparse(url).path.lower()
    name = source.name
    if 'Vunesp' in name:
        return bool(re.fullmatch(r'/[a-z]{2,10}\d{4,8}/?', p))
    if 'FGV' in name:
        return p.startswith('/concursos/') and p.count('/') <= 3
    if 'Cebraspe' in name:
        return p.startswith('/concursos/') and p.count('/') <= 3
    if 'ABCP' in name:
        return 'concurso' in p or 'edital' in p or 'detalhe' in p
    if 'Carlos Chagas' in name:
        # Contest pages look like /concursos/trt8r126/ ; /concursos/jsp/... are services (exam place etc.).
        return bool(re.fullmatch(r'/concursos/[a-z][a-z0-9]{2,12}\d{3}/(index\.html?)?', p))
    return False


DEFINITIVE = (
    'O arquivo não demonstra ser edital',
    'Não foi comprovado que o documento seja o edital inicial',
    textnorm.NO_ROLE,
    'Página HTML não identifica documento edital',
    'Cargo/especialidade específicos não encontrados',
)


def textnorm_role(text):
    from . import gazettes

    return gazettes.role_of(text)


def is_definitive(reason):
    """The document was read and is not an opening civil/mechanical engineering edital (as opposed to unreadable or blocked)."""
    return reason.startswith(DEFINITIVE)


def empty_listing_reason(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    markers = ('id="root"', 'id="app"', '__next_data__', 'ng-version', 'data-reactroot', 'nuxt')
    if len(soup.get_text(' ', strip=True)) < 400 or any(m in html.lower() for m in markers):
        return (
            'Site carregado por JavaScript: a lista de concursos não vem no HTML e o radar não executa scripts. '
            'Concursos dessa banca aparecem pela busca nos diários oficiais.'
        )
    return 'Nenhum detalhe de concurso extraído: o formato da página mudou'


def notice_anchor(text, url):
    q = textnorm.fold(text)
    path = textnorm.fold(urlparse(url).path)
    # Do not treat random communiqués, results, summons or news as opening notice.
    if any(
        w in q or w in path
        for w in (
            'resultado final',
            'gabarito',
            'convocacao',
            'prova objetiva',
            'homologacao',
            'recurso',
            'retificacao',
            'suspensao',
            'prorrogacao',
            'errata',
            'cancelamento',
            'aditamento',
            'comunicado',
            'retifica',
            'resultado',
            'orientac',
            'formulario',
            'convoca',
            'homolog',
            'local de prova',
            'localdeexame',
        )
    ):
        return False
    if 'edital' in q and any(w in q for w in ('abertura', '01/', '1/', 'nº 1', 'n. 1', 'edital')):
        return True
    # Cebraspe publishes PDFs with hashed names; the link text says "ED 1 ... ABERTURA".
    return path.endswith('.pdf') and bool('edital' in path or re.search(r'\bed\.?\s*0?1\b', q) or 'abertura' in q)


def scan_source(source, session=None):
    if source.mode == 'gazette_search':
        from . import gazettes

        return gazettes.scan_source(source, session)
    sid = repo.scan_start(source.name)
    detected = registered = 0
    try:
        base, raw, _mime = evidence.fetch_official(source.url, session)
        html = evidence.decode_html(raw)
        if not html.strip():
            raise ValueError('Fonte oficial vazia')
        if source.mode == 'watch':
            watch_page(source.name, base, html)
            repo.scan_finish(sid, 1, 0)
            return (1, 0, True)
        seeds = [(source.name, base, html)] if source.mode == 'details' else []
        if source.mode == 'notice_index':
            soup = BeautifulSoup(html, 'html.parser')
            blocks = soup.find_all('h4')
            for block in blocks:
                title = block.get_text(' ', strip=True)[:220]
                if not title:
                    continue
                fragments = []
                for node in block.next_elements:
                    if getattr(node, 'name', None) == 'h4':
                        break
                    if getattr(node, 'name', None) in ('a', 'p', 'table', 'div', 'h5'):
                        fragments.append(str(node))
                    if len(fragments) > 300:
                        break
                fragment = ''.join(fragments)
                if fragment and (
                    textnorm.is_target(BeautifulSoup(fragment, 'html.parser').get_text(' ', strip=True))
                    or 'diversos cargos' in textnorm.fold(fragment)
                ):
                    seeds.append((title, base, fragment))
            if not blocks:
                raise ValueError('IBAM: não foi possível separar os concursos publicados')
        detail_links = []
        incomplete = []
        if source.mode == 'catalog':
            detail_links = list(
                {url: (txt, url) for txt, url in hrefs(html, base) if looks_detail(source, txt, url)}.values()
            )
            if not detail_links:
                raise ValueError(empty_listing_reason(html))
            limit = config.detail_limit()
            if len(detail_links) > limit:
                incomplete.append(f'{len(detail_links)} concursos, limite por rodada {limit}')
                detail_links = detail_links[:limit]
            if 'vunesp' in source.url and 'mostrar mais opcoes' in textnorm.fold(html):
                incomplete.append('Vunesp possui paginação dinâmica não percorrida')
            page_errors = robots_skipped = 0
            for title, url in detail_links:
                try:
                    _, htmlbytes, _ = evidence.fetch_official(url, session)
                    seeds.append((title or url, url, evidence.decode_html(htmlbytes)))
                except polite.DomainCoolingDown:
                    raise
                except robots.RobotsBlocked:
                    # A page the site asks robots not to open is skipped, not a source failure.
                    robots_skipped += 1
                except Exception as err:
                    # One broken contest page must not hide all the others.
                    page_errors += 1
                    repo.upsert_candidate(url, source.name, title or url, state='fetch_failed', detail=str(err))
            if page_errors:
                incomplete.append(f'{page_errors} página(s) de concurso não abriram; veja a triagem')
            if robots_skipped and not seeds:
                incomplete.append('robots.txt do site não permite abrir as páginas dos concursos')
        if source.mode == 'notice_index':
            # An IBAM listing carries multiple contests at the SAME URL. Aggregate
            # all change links once: never overwrite the watch per individual block.
            related = []
            for _, _, fragment in seeds:
                related.extend(
                    (t, u)
                    for t, u in hrefs(fragment, base)
                    if any(
                        w in textnorm.fold(t)
                        for w in ('retificacao', 'suspensao', 'prorrogacao', 'cancelamento', 'alteracao do edital')
                    )
                )
            monitor_changes(base, related)
        examined = unreadable = 0
        for title, page, html in seeds:
            allanchors = list(hrefs(html, page))
            notice_links = [(t, u) for t, u in allanchors if notice_anchor(t, u)]
            if source.mode != 'notice_index':
                monitor_changes(
                    page,
                    [
                        (t, u)
                        for t, u in allanchors
                        if any(
                            w in textnorm.fold(t)
                            for w in ('retificacao', 'suspensao', 'prorrogacao', 'cancelamento', 'alteracao do edital')
                        )
                    ],
                )
            if not notice_links:
                # No edital => no promoted opportunity and no claim of validity.
                if 'Vunesp' in source.name and 'Editais e Documentos' in html:
                    incomplete.append('Vunesp: seção documental depende de carregamento dinâmico')
                elif source.mode == 'details' and empty_listing_reason(html).startswith(
                    'Site carregado por JavaScript'
                ):
                    incomplete.append('A lista de documentos desta página é carregada por JavaScript')
                continue
            # Scan multiple opening editais per contest: the first document is not
            # necessarily the engineering one. Limit and expose partial coverage explicitly.
            unique_notice = list({u: (t, u) for t, u in notice_links}.values())
            if len(unique_notice) > 10:
                incomplete.append('Mais de dez editais na mesma página; exige paginação/conferência')
            for _notice_t, notice_url in unique_notice[:10]:
                try:
                    proof = evidence.notice_proof(notice_url, session=session)
                except polite.DomainCoolingDown:
                    raise
                except Exception as err:
                    if is_definitive(str(err)):
                        # Read it: it is simply not an opening civil/mechanical engineering edital. Not a coverage gap, not triage noise.
                        examined += 1
                        continue
                    unreadable += 1
                    repo.upsert_candidate(
                        notice_url, source.name, title, notice_url, state='needs_review', detail=str(err)
                    )
                    continue
                # We have a real readable official edital and an engineering role. Still no dates or salary guessed.
                detected += 1
                repo.upsert_candidate(
                    proof.url,
                    source.name,
                    title,
                    proof.url,
                    state='edital_eng',
                    detail='Edital oficial de engenharia identificado; datas, cargo, remuneração e geografia exigem conferência por cargo.',
                )
                role = textnorm_role(proof.text)
                item = {
                    'title': title or source.name,
                    'agency': '',
                    'position': role,
                    'source': source.name,
                    'official_url': page,
                    'notice_url': proof.url,
                    'confidence': 'discovery',
                    'reviewed': 0,
                    'notes': (
                        'Edital oficial de engenharia identificado'
                        + (f' (cargo encontrado: {role})' if role else '')
                        + '. Confirme cargo, salários e datas no documento antes de classificar inscrições. '
                        + f'Trecho do edital: “{proof.role_excerpt}”'
                    ),
                    'fingerprint': hashlib.sha256(('official-document|' + proof.url).encode()).hexdigest()[:32],
                }
                oid, created = repo.upsert(item)
                if not created:
                    with database.connection() as db:
                        saved = db.execute(
                            'SELECT sha256 FROM notice_evidence WHERE opportunity_id=?', (oid,)
                        ).fetchone()
                    if saved and saved['sha256'] != proof.sha256:
                        with database.DB_LOCK, database.connection() as db:
                            db.execute('DELETE FROM notice_evidence WHERE opportunity_id=?', (oid,))
                            db.execute("UPDATE opportunities SET reviewed=0,confidence='discovery' WHERE id=?", (oid,))
                            db.commit()
                        repo.add_alert(
                            'notice-changed:' + str(oid) + ':' + proof.sha256,
                            'site_changed',
                            f'Edital alterado para {title}; aprovação anterior revogada. Conferir documentos: {proof.url}',
                            oid,
                        )
                if created:
                    registered += 1
                    repo.add_alert(
                        'new-official:' + str(oid),
                        'new',
                        f'Edital oficial com cargo de engenharia encontrado: {title}. Conferência do cargo pendente. {proof.url}',
                        oid,
                    )
        if unreadable:
            incomplete.append(
                f'{unreadable} documento(s) sem leitura automática (PDF digitalizado ou bloqueado); veja a triagem'
            )
        nothing_listed = source.mode == 'notice_index' and not seeds
        if not detected and not examined and not unreadable and not nothing_listed:
            incomplete.append('Nenhum edital de abertura acessível; cobertura documental não comprovada')
        if incomplete:
            msg = '; '.join(dict.fromkeys(incomplete))
            repo.scan_finish(sid, detected, registered, error='Cobertura PARCIAL: ' + msg)
            return detected, registered, False
        repo.scan_finish(sid, detected, registered)
        return detected, registered, True
    except polite.DomainCoolingDown as ex:
        LOG.warning('Domínio oficial em pausa %s: %s', source.name, ex)
        repo.scan_finish(sid, detected, registered, error=str(ex), state='blocked')
        return detected, registered, False
    except Exception as ex:
        LOG.warning('Fonte oficial %s: %s', source.name, ex)
        repo.scan_finish(sid, detected, registered, error=str(ex))
        return detected, registered, False


def monitor_changes(page, changes):
    # Track retification URLs on EACH OFFICIAL detail page.
    import json

    links = json.dumps(sorted({url for _, url in changes}), ensure_ascii=False)
    with database.DB_LOCK, database.connection() as db:
        old = db.execute('SELECT document_links FROM notice_watches WHERE page_url=?', (page,)).fetchone()
        previous = set(json.loads(old[0])) if old else set()
        current = set(json.loads(links))
        fresh = current - previous if old else set()
        db.execute(
            """INSERT INTO notice_watches(page_url,document_links,checked_at) VALUES(?,?,?)
             ON CONFLICT(page_url) DO UPDATE SET document_links=excluded.document_links,checked_at=excluded.checked_at""",
            (page, links, clock.now()),
        )
        if fresh:
            records = db.execute(
                """SELECT o.id FROM opportunities o JOIN notice_evidence p ON p.opportunity_id=o.id
                                     WHERE o.official_url=?""",
                (page,),
            ).fetchall()
            for rec in records:
                db.execute('DELETE FROM notice_evidence WHERE opportunity_id=?', (rec['id'],))
                db.execute("UPDATE opportunities SET reviewed=0,confidence='discovery' WHERE id=?", (rec['id'],))
        db.commit()
    if fresh:
        repo.add_alert(
            'retification:' + hashlib.sha256((page + links).encode()).hexdigest(),
            'site_changed',
            f'Novo documento de retificação/suspensão encontrado em {page}. Conferir edital.',
        )
    return len(fresh)


def watch_page(label, url, html):
    soup = BeautifulSoup(html, 'html.parser')
    for t in soup(['script', 'style', 'nav', 'footer', 'header']):
        t.decompose()
    normalized = re.sub(r'\s+', ' ', soup.get_text(' ', strip=True))[:150000]
    if len(normalized) < 50:
        raise ValueError('Página sem conteúdo verificável')
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    with database.DB_LOCK, database.connection() as db:
        old = db.execute('SELECT digest FROM watched_pages WHERE url=?', (url,)).fetchone()
        changed = bool(old and old['digest'] and old['digest'] != digest)
        db.execute(
            """INSERT INTO watched_pages(url,label,digest,checked_at,changed_at,error)
          VALUES(?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET digest=excluded.digest,checked_at=excluded.checked_at,
          changed_at=CASE WHEN watched_pages.digest<>excluded.digest THEN excluded.changed_at ELSE watched_pages.changed_at END,error='' """,
            (url, label, digest, clock.now(), clock.now() if changed else None, ''),
        )
        db.commit()
    if changed:
        repo.add_alert(
            'changed:' + url + ':' + digest,
            'site_changed',
            f'Página oficial alterada: {label}. Verificar edital/retificação: {url}',
        )


def deadline_alerts(reference=None):
    reference = reference or clock.today()
    for item in repo.query_opportunities():
        if item['status'] != 'open' or item['dismissed'] or not item['registration_end']:
            continue
        days = (date.fromisoformat(item['registration_end']) - reference).days
        if days in (7, 3, 1, 0):
            repo.add_alert(
                f'deadline:{item["id"]}:{item["registration_end"]}:{days}',
                'deadline',
                f'Prazo: {days} dia(s) — {item["title"]}. Inscrição em {item["apply_url"] or item["official_url"]}',
                item['id'],
            )


def claim_lease():
    # SQLite serialized across API and worker, with expiration in case process dies.
    from datetime import timedelta

    with database.DB_LOCK, database.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM app_settings WHERE key='scan_lease_until'").fetchone()
        if row and row[0] > clock.now():
            db.rollback()
            return False
        until = (datetime.now(clock.TZ) + timedelta(minutes=75)).isoformat(timespec='seconds')
        db.execute(
            "INSERT INTO app_settings(key,value) VALUES ('scan_lease_until',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (until,),
        )
        db.commit()
        return True


def release_lease():
    with database.DB_LOCK, database.connection() as db:
        db.execute("DELETE FROM app_settings WHERE key='scan_lease_until'")
        db.commit()


def run_all(session=None):
    if not LOCK.acquire(False):
        return {'state': 'busy'}
    if not claim_lease():
        LOCK.release()
        return {'state': 'busy'}
    try:
        found = added = failed = 0
        # Queue different official domains in parallel; no concurrent burst
        # against a single host (polite.request_lane serializes per domain).
        # Fake injected sessions are intentionally sequential for test safety.
        workers = 1 if session is not None else min(len(SOURCES), config.source_workers())
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='official-source') as executor:
            tasks = {executor.submit(scan_source, source, session): source for source in SOURCES}
            for future in as_completed(tasks):
                source = tasks[future]
                try:
                    f, a, ok = future.result()
                except Exception as ex:
                    LOG.exception('Erro inesperado no job %s', source.name)
                    f, a, ok = 0, 0, False
                    repo.add_alert(
                        'collector-exception:' + source.name + ':' + clock.now()[:13],
                        'coverage',
                        f'Job oficial {source.name} falhou: {ex}',
                    )
                found += f
                added += a
                failed += int(not ok)
        if failed:
            repo.add_alert(
                'source-fail:' + clock.now()[:13],
                'coverage',
                f'{failed}/{len(SOURCES)} fontes oficiais falharam. Cobertura incompleta; veja Fontes.',
            )
        if session is None:
            # Real runs only: validate pending contests by finding their opening edital.
            from .verification import auto_verify

            try:
                auto_verify()
            except Exception:
                LOG.exception('Validação automática falhou')
        deadline_alerts()
        try:
            from .notifications import dispatch

            dispatch()
        except Exception as exc:
            LOG.warning('Alertas externos falharam: %s', exc)
        return {
            'state': 'ok' if failed == 0 else 'partial',
            'sources': len(SOURCES),
            'failed': failed,
            'notice_candidates': found,
            'new': added,
        }
    finally:
        release_lease()
        LOCK.release()
