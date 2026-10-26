from datetime import datetime

from app import collectors, evidence
from app import repository as repo
from app.worker import slot


def test_catalog_has_only_official_sources():
    assert len(collectors.SOURCES) >= 7
    assert all(
        evidence.data_api_url(s.url) if s.mode == 'gazette_search' else evidence.official_url(s.url)
        for s in collectors.SOURCES
    )
    assert not any('google' in s.url or 'pciconcursos' in s.url for s in collectors.SOURCES)


def test_detail_selectors():
    s = collectors.SOURCES[0]
    assert collectors.looks_detail(s, 'Saiba Mais', 'https://www.vunesp.com.br/CMIH2601')
    assert not collectors.looks_detail(s, 'Sobre nós', 'https://www.vunesp.com.br/institucional')


def test_official_notice_selector():
    assert collectors.notice_anchor('Edital de Abertura', 'https://www.gov.br/a.pdf')
    assert not collectors.notice_anchor('Resultado final', 'https://www.gov.br/b.pdf')
    assert not collectors.notice_anchor('Faixa salarial', 'https://www.gov.br/salary.pdf')


def test_html_has_only_allowed_links():
    html = '<a href="https://evil.com/edital.pdf">ED</a><a href="/CMIH2601">IT</a>'
    assert list(collectors.hrefs(html, 'https://www.vunesp.com.br')) == [('IT', 'https://www.vunesp.com.br/CMIH2601')]


def test_worker_slot_time():
    assert slot(datetime(2026, 10, 16, 0, 0)) == '2026-10-16:0'
    assert slot(datetime(2026, 10, 16, 2, 59)) == '2026-10-16:0'
    assert slot(datetime(2026, 10, 16, 3, 0)) == '2026-10-16:1'
    assert slot(datetime(2026, 10, 16, 21, 0)) == '2026-10-16:7'


def test_scan_lease_exclusive():
    assert collectors.claim_lease() is True
    assert collectors.claim_lease() is False
    collectors.release_lease()
    assert collectors.claim_lease() is True
    collectors.release_lease()


def test_source_failure_clearly_reported(monkeypatch):
    def bad(*a, **kw):
        raise ValueError('Fonte indisponível')

    monkeypatch.setattr(evidence, 'fetch_official', bad)
    f, a, ok = collectors.scan_source(collectors.SOURCES[0])
    assert (f, a, ok) == (0, 0, False)
    assert repo.source_health()[0]['state'] == 'failed'


def test_watched_page_change():
    collectors.watch_page(
        'Orgão', 'https://www.gov.br/orgao', '<html><main>' + 'texto oficial ' * 30 + '</main></html>'
    )
    collectors.watch_page(
        'Orgão', 'https://www.gov.br/orgao', '<html><main>' + 'texto modificado ' * 30 + '</main></html>'
    )
    assert any(a['kind'] == 'site_changed' for a in repo.get_alerts())


def test_deadline_only_proven():
    repo.upsert(
        {
            'title': 'Incompleto',
            'position': 'Engenheiro Civil',
            'official_url': 'https://www.gov.br/a',
            'registration_start': '2026-10-01',
            'registration_end': '2026-10-16',
            'confidence': 'official',
            'reviewed': 1,
        }
    )
    collectors.deadline_alerts(reference=repo.date(2026, 10, 16))
    assert not any(x['kind'] == 'deadline' for x in repo.get_alerts())


def test_fcc_viewer_link_becomes_the_pdf_address():
    pdf = 'https://www.concursosfcc.com.br/concursos/trt8r126/trt8r126_edital_de_abertura.pdf'
    html = f'<a href="/rybena/web/index.html?file={pdf}">Edital de Abertura</a>'
    assert list(collectors.hrefs(html, 'https://www.concursosfcc.com.br/')) == [('Edital de Abertura', pdf)]
    assert collectors.notice_anchor('Edital de Abertura', pdf)
    foreign = '<a href="/rybena/web/index.html?file=https://evil.com/a.pdf">Edital</a>'
    links = [u for _, u in collectors.hrefs(foreign, 'https://www.concursosfcc.com.br/')]
    assert links == ['https://www.concursosfcc.com.br/rybena/web/index.html?file=https://evil.com/a.pdf']


def test_viewer_wrapped_summons_stay_excluded():
    pdf = 'https://www.concursosfcc.com.br/concursos/x/x_edital_n0_2_convocacao_prova_objetiva.pdf'
    assert not collectors.notice_anchor('Edital', pdf)


def test_latin1_page_titles_keep_accents():
    raw = '<html><head><meta charset="iso-8859-1"></head>Polícia São Paulo</html>'.encode('latin-1')
    assert 'São Paulo' in evidence.decode_html(raw)
    assert 'São Paulo' in evidence.decode_html('São Paulo'.encode())


def test_interrupted_runs_are_closed():
    run = repo.scan_start('Fonte interrompida')
    assert repo.close_interrupted_runs() >= 1
    row = next(r for r in repo.source_health() if r['source'] == 'Fonte interrompida')
    assert row['id'] == run and row['state'] == 'failed' and row['error'].startswith('Interrompida')
