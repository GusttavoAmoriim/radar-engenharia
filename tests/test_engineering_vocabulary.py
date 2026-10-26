"""What counts as a civil or mechanical engineering role, and what must never count."""

import pytest

from app import gazettes, textnorm


@pytest.mark.parametrize(
    'text',
    [
        'Engenheiro Civil',
        'ENGENHEIRO(A) CIVIL',
        'Engenheira Mecânica',
        'Engenheiro (a) Mecânico',
        'Engenharia Civil',
        'Analista de Infraestrutura – Engenharia Mecânica',
        'Engenheiro de Equipamentos Júnior – Mecânica',
        'Engenheiro - Área: Civil',
        'Engenheiros Civis',
        'Engenheiro de Construção Civil',
    ],
)
def test_engineering_roles_are_recognised(text):
    assert textnorm.is_target(text)


@pytest.mark.parametrize(
    'text',
    [
        'Analista de Sistemas',
        'Técnico em Mecânica',
        'Mecânico de Manutenção',
        'Técnico em Edificações',
        'Escrivão da Polícia Civil',
        'Engenheiro Eletricista, Escrivão da Polícia Civil',
        'Engenheiro Eletricista – Polícia Civil',
        'Engenheiro Agrônomo e Procurador de Direito Civil',
        'Engenheiro da Defesa Civil',
        'Analista Judiciário – Direito Civil',
        'Engenheiro Eletricista',
        'Engenheiro de Segurança do Trabalho',
        'Professor de Engenharia',
        '',
    ],
)
def test_other_roles_are_not(text):
    assert not textnorm.is_target(text)


def test_find_target_works_on_folded_text_with_positions():
    norm = textnorm.fold('Vagas para Engenheiro(a) Civil e Engenheira Mecânica.')
    spans = [norm[m.start() : m.end()] for m in textnorm.find_target(norm)]
    assert spans == ['engenheiro(a) civil', 'engenheira mecanica']


def test_gazette_role_extraction_skips_false_friends():
    text = 'Vagas: Engenheiro Eletricista, Escrivão da Polícia Civil e Engenheiro(a) Civil (nível superior).'
    assert gazettes.role_of(text) == 'Engenheiro(a) Civil'
    assert gazettes.role_of('Escrivão da Polícia Civil') == ''


def test_design_competitions_and_tenders_are_not_openings():
    tender = 'Aviso de licitação: concurso de projetos de Engenharia Civil. Edital de abertura publicado.'
    assert not gazettes.relevant(tender)
    opening = 'Edital de abertura do concurso público para Engenheiro Civil. Inscrições abertas.'
    assert gazettes.relevant(opening)
