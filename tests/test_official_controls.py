"""Regressions for fail-closed source handling and IBAM shared catalog URL."""

import hashlib

from app import collectors, evidence
from app import repository as repo


def test_retifications_never_chosen_as_initial_notice():
    assert not collectors.notice_anchor(
        'Retificação do Edital', 'https://www.ibam-concursos.org.br/retificacao-edital.pdf'
    )
    assert not collectors.notice_anchor('Suspensão do Edital 01', 'https://www.gov.br/suspensao.pdf')
    assert collectors.notice_anchor('Edital de Abertura', 'https://www.gov.br/edital.pdf')


def test_two_ibam_edital_documents_are_separate(monkeypatch):
    html = """<html><main>
      <h4>Prefeitura A — Concurso Público</h4>
      <p>Vaga de Engenheiro Civil</p><a href="/documento-A.pdf">Edital de Abertura</a>
      <h4>Prefeitura B — Concurso Público</h4>
      <p>Vaga de Engenheiro Mecânico</p><a href="/documento-B.pdf">Edital de Abertura</a>
    </main></html>"""

    def fetch(url, session=None):
        return url, html.encode(), 'text/html'

    def proof(url, session=None, position=''):
        return evidence.Proof(
            url,
            hashlib.sha256(url.encode()).hexdigest(),
            'EDITAL DE ABERTURA CONCURSO PÚBLICO ENGENHEIRO CIVIL',
            'pdf',
            'engenheiro civil',
        )

    monkeypatch.setattr(evidence, 'fetch_official', fetch)
    monkeypatch.setattr(evidence, 'notice_proof', proof)
    s = collectors.Source('IBAM — editais', 'https://www.ibam-concursos.org.br/', 'notice_index')
    found, added, ok = collectors.scan_source(s)
    assert (found, added, ok) == (2, 2, True)
    items = repo.query_opportunities()
    assert len(items) == 2
    assert len({i['fingerprint'] for i in items}) == 2
    assert all(i['status'] == 'verify' and not i['document_verified'] for i in items)


def test_list_without_readable_opening_notice_is_not_ok(monkeypatch):
    html = """<html><a href="/CMIH2601">Detalhes</a></html>"""
    monkeypatch.setattr(evidence, 'fetch_official', lambda url, session=None: (url, html.encode(), 'text/html'))
    s = collectors.Source('Vunesp — próximos', 'https://www.vunesp.com.br/busca/concurso/proximo')
    found, added, ok = collectors.scan_source(s)
    assert not ok and found == 0 and added == 0
    assert 'PARCIAL' in repo.source_health()[0]['error']
