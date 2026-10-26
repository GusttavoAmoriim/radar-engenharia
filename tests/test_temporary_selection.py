"""Processo seletivo simplificado (PSS): temporary hiring, found inside municipal gazettes."""

import json
from io import BytesIO

import pytest
from reportlab.pdfgen import canvas

from app import evidence, gazettes, sources, textnorm
from app import repository as repo

URL = 'https://data.queridodiario.ok.org.br/4106902/2026-10-09/diario.pdf'
HEADER = 'DIÁRIO OFICIAL ELETRÔNICO - ATOS DO MUNICÍPIO DE CURITIBA - 9 DE OUTUBRO DE 2026'


def pdf(*pages):
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=(595, 842))
    for lines in pages:
        y = 810
        for line in [HEADER, *lines]:
            page.drawString(30, y, line)
            y -= 14
        page.showPage()
    page.save()
    return buffer.getvalue()


ENGINEER = [
    'EDITAL NORMATIVO DE PROCESSO SELETIVO SIMPLIFICADO Nº 09/2026',
    'Processo Seletivo Simplificado destinado a contratação temporária de agentes públicos para a',
    'Função Pública de ENGENHEIRO CIVIL, em Regime Especial de Contratação.',
    'ENGENHEIRO CIVIL 40h R$ 8.035,42',
    'Graduação em Engenharia Civil com registro regular no CREA-PR.',
    'Período para solicitação de inscrição: 9h do dia 19/10 até às 23h59 do dia 05/11/2026',
]
ACCOUNTANT = [
    'EDITAL NORMATIVO DE PROCESSO SELETIVO SIMPLIFICADO Nº 10/2026',
    'Processo Seletivo Simplificado destinado a contratação temporária para a função de CONTADOR.',
    'CONTADOR 40h R$ 7.100,00',
    'Período para solicitação de inscrição: 9h do dia 19/10 até às 23h59 do dia 12/11/2026',
]
RETIFICATION = [
    'RETIFICAÇÃO DO EDITAL NORMATIVO DE PROCESSO SELETIVO SIMPLIFICADO Nº 07/2026',
    'Engenheiro Mecânico R$ 4.000,00. Inscrições até 30/10/2026.',
]
AUCTION = ['AVISO DE LEILÃO. Lote de sucata. Edital de leilão público.']


def prove(raw, position):
    return evidence.prove_document(URL, raw, 'application/pdf', position)


def test_gazette_keeps_only_the_section_of_the_edital_that_names_the_role():
    raw = pdf(AUCTION, ENGINEER, ACCOUNTANT)
    proof = prove(raw, 'Engenheiro Civil')
    assert proof.temporary
    assert 'processo seletivo simplificado no 09/2026' in proof.text
    assert 'contador' not in proof.text and '12/11/2026' not in proof.text
    ok = {'position': 'Engenheiro Civil', 'salary_min': 8035.42, 'registration_end': '2026-11-05'}
    assert evidence.assertion_failures(proof, ok) == []


def test_facts_of_another_edital_in_the_same_gazette_do_not_count():
    proof = prove(pdf(ENGINEER, ACCOUNTANT), 'Engenheiro Civil')
    failures = dict(evidence.assertion_failures(proof, {'salary_min': 7100.0, 'registration_end': '2026-11-12'}))
    assert set(failures) == {'salary_min', 'registration_end'}


@pytest.mark.parametrize(
    'position, message',
    [
        ('Contador', 'Cargo pouco específico'),
        ('Engenheiro Mecânico', 'Cargo/especialidade específicos não encontrados'),
    ],
)
def test_roles_that_the_gazette_does_not_open_are_refused(position, message):
    with pytest.raises(ValueError, match=message):
        prove(pdf(ENGINEER, ACCOUNTANT), position)


def test_amendments_and_gazettes_without_editais_are_not_openings():
    filler = ['Portaria de nomeação e expediente administrativo da Secretaria Municipal de Administração.'] * 12
    with pytest.raises(ValueError, match='edital inicial'):
        prove(pdf(AUCTION + filler, RETIFICATION + filler), 'Engenheiro Mecânico')
    with pytest.raises(ValueError, match=r'não demonstra ser edital|edital inicial'):
        prove(pdf(AUCTION + filler), 'Engenheiro Civil')


def test_standalone_pss_edital_is_accepted_and_flagged_temporary():
    text = '\n'.join(['EDITAL NORMATIVO DE PROCESSO SELETIVO SIMPLIFICADO Nº 09/2026', *ENGINEER[1:]] * 6)
    raw = pdf(text.split('\n')[:48])
    proof = evidence.prove_document(
        'https://www.curitiba.pr.gov.br/edital.pdf', raw, 'application/pdf', 'Engenheiro Civil'
    )
    assert proof.temporary


def test_a_regular_concurso_is_not_flagged_temporary():
    lines = ['EDITAL Nº 1 DE ABERTURA - CONCURSO PÚBLICO', 'Cargo Engenheiro Civil R$ 9.800,00'] + [
        'Inscrições de 01/10/2026 a 20/10/2026. Requisitos: Engenharia Civil com registro no CREA.'
    ] * 8
    proof = evidence.prove_document('https://www.gov.br/edital.pdf', pdf(lines), 'application/pdf', 'Engenheiro Civil')
    assert not proof.temporary


def test_a_standalone_amendment_is_not_an_opening():
    lines = [
        'RETIFICAÇÃO DO EDITAL NORMATIVO DE PROCESSO SELETIVO SIMPLIFICADO Nº 09/2026',
        'Engenheiro Civil. Processo seletivo simplificado. Inscrições até 05/11/2026.',
    ] * 12
    with pytest.raises(ValueError, match='edital inicial'):
        evidence.prove_document(
            'https://www.curitiba.pr.gov.br/x.pdf', pdf(lines), 'application/pdf', 'Engenheiro Civil'
        )


def test_temporary_hiring_detector():
    assert textnorm.is_temporary('Torna público o Edital Normativo do Processo Seletivo Simplificado')
    assert textnorm.is_temporary('em Regime Especial de Contratação, de acordo com as normas')
    assert textnorm.is_temporary('PSS - EDITAL NORMATIVO Nº 9')
    assert not textnorm.is_temporary('Edital de abertura do concurso público para Engenheiro Civil')


CURITIBA = (
    'função pública de Engenheiro Civil, na Administração Direta do Município de Curitiba, em Regime Especial de '
    'Contratação, de acordo com as normas instituídas, conforme anexo. Secretaria Municipal de Gestão de Pessoal, '
    '9 de outubro de 2026. SMGP Torna público o Edital Normativo do Processo Seletivo Simplificado.'
)
SOURCE = sources.Source(name='QD', url='https://api.queridodiario.org.br/gazettes', mode='gazette_search')


def test_gazette_discovery_labels_the_selection_as_temporary(monkeypatch):
    payload = {
        'gazettes': [
            {'territory_name': 'Curitiba', 'state_code': 'PR', 'date': '2026-10-09', 'url': URL, 'excerpts': [CURITIBA]}
        ]
    }
    monkeypatch.setattr(
        evidence,
        'fetch_official',
        lambda url, session=None, **k: (url, json.dumps(payload).encode(), 'application/json'),
    )
    assert gazettes.scan_source(SOURCE)[:2] == (1, 1)
    item = repo.query_opportunities()[0]
    assert item['type'] == 'pss' and 'seleção temporária' in item['title'] and item['position'] == 'Engenheiro Civil'


def test_an_old_card_found_before_the_label_existed_is_updated(monkeypatch):
    payload = {
        'gazettes': [
            {'territory_name': 'Curitiba', 'state_code': 'PR', 'date': '2026-10-09', 'url': URL, 'excerpts': [CURITIBA]}
        ]
    }
    monkeypatch.setattr(
        evidence,
        'fetch_official',
        lambda url, session=None, **k: (url, json.dumps(payload).encode(), 'application/json'),
    )
    gazettes.scan_source(SOURCE)
    oid = repo.query_opportunities()[0]['id']
    repo.update_opportunity(oid, {'type': 'concurso'})
    gazettes.scan_source(SOURCE)
    assert repo.fetch_one(oid)['type'] == 'pss'


def test_recording_a_proof_sets_the_type_from_the_document():
    oid, _ = repo.upsert(
        {'title': 'Prefeitura — Engenheiro Civil', 'position': 'Engenheiro Civil', 'fingerprint': 'x1'}
    )
    repo.record_proof(oid, evidence.Proof(URL, 'a' * 64, '', 'pdf', 'x', temporary=True), {})
    assert repo.fetch_one(oid)['type'] == 'pss'
    repo.record_proof(oid, evidence.Proof(URL, 'b' * 64, '', 'pdf', 'x', temporary=False), {})
    assert repo.fetch_one(oid)['type'] == 'concurso'


def test_unknown_type_is_refused():
    with pytest.raises(ValueError, match='Tipo inválido'):
        repo.upsert({'title': 'X', 'type': 'outro'})
