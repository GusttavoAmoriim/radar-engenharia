import hashlib

from app import collectors, evidence, robots
from app import repository as repo

FCC = collectors.Source('Fundação Carlos Chagas', 'https://www.concursosfcc.com.br/', 'catalog')
HOME = 'https://www.concursosfcc.com.br/'
TRT = 'https://www.concursosfcc.com.br/concursos/trt8r126/'
SEF = 'https://www.concursosfcc.com.br/concursos/sefsc126/index.html'
LOCAL = 'https://www.concursosfcc.com.br/concursos/jsp/localDeExame/index.jsp'
TRT_PDF = 'https://www.concursosfcc.com.br/concursos/trt8r126/trt8r126_edital_de_abertura.pdf'
SEF_PDF = 'https://www.concursosfcc.com.br/concursos/sefsc126/sefsc126_edital_de_abertura.pdf'


def site(monkeypatch, pages, blocked=()):
    def fetch(url, session=None, **kw):
        if url in blocked:
            raise robots.RobotsBlocked('robots.txt de www.concursosfcc.com.br proíbe esta página para o radar')
        if url not in pages:
            raise ValueError('HTTP 404')
        return url, pages[url].encode(), 'text/html'

    monkeypatch.setattr(evidence, 'fetch_official', fetch)


def proofs(monkeypatch, outcomes):
    def proof(url, session=None, position=''):
        outcome = outcomes[url]
        if isinstance(outcome, Exception):
            raise outcome
        return evidence.Proof(url, hashlib.sha256(url.encode()).hexdigest(), 'x', 'pdf', 'engenheiro civil')

    monkeypatch.setattr(evidence, 'notice_proof', proof)


HOME_HTML = f'<a href="{TRT}">TRT 8ª Região</a><a href="{SEF}">SEF SC</a><a href="{LOCAL}">Local de prova</a>'


def test_fcc_detail_pages_only():
    assert collectors.looks_detail(FCC, 'TRT', TRT)
    assert collectors.looks_detail(FCC, 'SEF', SEF)
    assert not collectors.looks_detail(FCC, 'Clique aqui para consultar o seu local de prova', LOCAL)


def test_one_broken_page_does_not_hide_the_others(monkeypatch):
    site(monkeypatch, {HOME: HOME_HTML, SEF: f'<a href="{SEF_PDF}">Edital de Abertura</a>'})
    proofs(monkeypatch, {SEF_PDF: None})
    found, added, ok = collectors.scan_source(FCC)
    assert (found, added) == (1, 1) and not ok
    assert '1 página(s) de concurso não abriram' in repo.source_health()[0]['error']


def test_robots_skipped_page_is_not_a_failure(monkeypatch):
    html = HOME_HTML.replace(TRT, 'https://www.concursosfcc.com.br/concursos/abcde126/')
    site(
        monkeypatch,
        {HOME: html, SEF: f'<a href="{SEF_PDF}">Edital de Abertura</a>'},
        blocked={'https://www.concursosfcc.com.br/concursos/abcde126/'},
    )
    proofs(monkeypatch, {SEF_PDF: None})
    assert collectors.scan_source(FCC) == (1, 1, True)
    assert not [c for c in repo.candidates() if c['state'] == 'fetch_failed']


def test_read_editais_without_it_role_are_ok_and_not_triage(monkeypatch):
    site(
        monkeypatch,
        {
            HOME: HOME_HTML,
            TRT: f'<a href="{TRT_PDF}">Edital de Abertura</a>',
            SEF: f'<a href="{SEF_PDF}">Edital de Abertura</a>',
        },
    )
    proofs(
        monkeypatch,
        {
            TRT_PDF: ValueError('Edital sem cargo de engenharia civil ou mecânica identificável'),
            SEF_PDF: ValueError('Edital sem cargo de engenharia civil ou mecânica identificável'),
        },
    )
    assert collectors.scan_source(FCC) == (0, 0, True)
    assert repo.candidates() == []


def test_unreadable_edital_is_partial_and_listed(monkeypatch):
    site(
        monkeypatch, {HOME: HOME_HTML, TRT: f'<a href="{TRT_PDF}">Edital de Abertura</a>', SEF: '<p>sem documentos</p>'}
    )
    proofs(monkeypatch, {TRT_PDF: ValueError('Edital sem texto legível; revisão manual obrigatória')})
    assert collectors.scan_source(FCC) == (0, 0, False)
    assert 'sem leitura automática' in repo.source_health()[0]['error']
    assert [c['state'] for c in repo.candidates()] == ['needs_review']


def test_javascript_listing_is_explained(monkeypatch):
    site(monkeypatch, {HOME: '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'})
    assert collectors.scan_source(FCC)[2] is False
    assert 'JavaScript' in repo.source_health()[0]['error']


def test_ifsp_communiques_are_not_opening_editais():
    base = 'https://concursopublico.ifsp.edu.br/arquivos/'
    assert collectors.notice_anchor('Edital 183/2026 – docentes', base + 'edital-1832026-docentes.pdf')
    assert not collectors.notice_anchor('Comunicado 3/2026', base + 'comunicado-32026-resultado.pdf')
    assert not collectors.notice_anchor('Edital 188/2026 – retificação', base + 'edital-1882026-retifica-o.pdf')
    assert not collectors.notice_anchor('Orientações', base + 'orientacoes-para-candidatos-edital.pdf')


def test_prune_obsolete_triage_rows():
    repo.upsert_candidate(
        'https://www.concursosfcc.com.br/rybena/web/index.html?file=x.pdf',
        'FCC',
        'Pol�cia',
        state='needs_review',
        detail='x',
    )
    repo.upsert_candidate(
        'https://a.gov.br/1.pdf',
        'X',
        'A',
        state='needs_review',
        detail='O arquivo não demonstra ser edital de concurso público',
    )
    repo.upsert_candidate(
        LOCAL, 'FCC', 'Local', state='fetch_failed', detail='robots.txt de www.concursosfcc.com.br proíbe esta página'
    )
    repo.upsert_candidate(
        'https://a.gov.br/2.pdf',
        'X',
        'B',
        state='needs_review',
        detail='Edital sem texto legível; revisão manual obrigatória',
    )
    assert repo.prune_candidates() == 3
    assert [c['title'] for c in repo.candidates()] == ['B']
