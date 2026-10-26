import pytest

from app import evidence


@pytest.mark.parametrize(
    'url,expected',
    [
        ('https://www.vunesp.com.br/CMIH2601', True),
        ('https://documento.vunesp.com.br/documento/stream/7', True),
        ('https://conhecimento.fgv.br/concursos/dataprev26', True),
        ('https://www.cebraspe.org.br/concursos/a', True),
        ('https://abcp.selecao.net.br/concursos/1', True),
        ('https://www.gov.br/cgu', True),
        ('https://sao-paulo.gov.br/edital', True),
        ('https://concursopublico.ifsp.edu.br/', True),
        ('https://www.vunesp.com.br.evil.com/a', False),
        ('https://vunesp.com.br@evil.org/a', False),
        ('http://www.vunesp.com.br/', False),
        ('https://evil.com/edital.pdf', False),
        ('https://127.0.0.1/admin', False),
        ('file:///etc/passwd', False),
        ('javascript:alert(1)', False),
    ],
)
def test_official_domain_rules(url, expected):
    assert evidence.official_url(url) is expected


def test_notice_requires_real_context():
    good = (
        'EDITAL Nº 1 DE ABERTURA - CONCURSO PÚBLICO. Vagas: Engenheiro Civil. '
        'Inscrições das 01/10/2026 até 20/10/2026. '
        'Prova objetiva em 13/12/2026. Cargo Engenheiro Civil R$ 9.800,00. '
    ) * 8

    class FakeResponse:
        url = 'https://www.gov.br/edital'
        status_code = 200
        headers = {'Content-Type': 'text/html'}

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield ('<html>' + good + '</html>').encode()

        def close(self):
            pass

    class FakeSession:
        def get(self, url, **kwargs):
            return FakeResponse()

    p = evidence.notice_proof('https://www.gov.br/edital', session=FakeSession(), position='Engenheiro Civil')
    assert p.role_excerpt and p.sha256
    assert evidence.date_supported(p.text, '2026-10-20')
    assert evidence.money_supported_near_role(p.text, 9800, 'Engenheiro Civil')
    evidence.check_assertions(p, {'position': 'Engenheiro Civil', 'salary_min': 9800, 'registration_end': '2026-10-20'})
    with pytest.raises(ValueError):
        evidence.check_assertions(p, {'position': 'Engenheiro Civil', 'registration_end': '2027-11-20'})
    with pytest.raises(ValueError):
        evidence.check_assertions(p, {'position': 'Engenheiro Civil', 'salary_min': 12000})


def test_salary_from_other_role_not_valid():
    txt = (
        'Concurso publico edital. Cargo Engenheiro Civil R$ 5.000,00. ' + 'x' * 900 + ' Cargo Procurador R$ 20.000,00.'
    )
    assert not evidence.money_supported_near_role(txt, 20000, 'Engenheiro Civil')
    assert evidence.money_supported_near_role(txt, 5000, 'Engenheiro Civil')


@pytest.mark.parametrize(
    'bad',
    [
        'Edital para concurso de professor de matemática. ' * 30,
        'Notícia sem edital: engenharia civil concurso e vagas ' * 30,
        'edital sem texto e engenharia',
    ],
)
def test_notice_gates(bad):
    class R:
        url = 'https://www.gov.br/edital'
        headers = {'Content-Type': 'text/html'}
        status_code = 200

        def raise_for_status(self):
            pass

        def iter_content(self, _):
            yield ('<html>' + bad + '</html>').encode()

        def close(self):
            pass

    class S:
        def get(self, *a, **k):
            return R()

    with pytest.raises(ValueError):
        evidence.notice_proof('https://www.gov.br/edital', session=S(), position='Engenheiro Civil')


def test_redirect_outside_official_blocked():
    class R:
        url = 'https://www.gov.br/edital'
        status_code = 302
        headers = {'location': 'https://evil.com/edital'}

        def close(self):
            pass

    class S:
        def get(self, *a, **k):
            return R()

    with pytest.raises(ValueError, match='Redirecionamento'):
        evidence.fetch_official('https://www.gov.br/edital', S())


def test_dates_written_in_words_are_recognized():
    text = 'Período de inscrições: das 16h do dia 20 de outubro de 2026 até às 16h do dia 18 de novembro de 2026.'
    assert evidence.date_supported(text, '2026-10-20', 'registration_start')
    assert evidence.date_supported(text, '2026-11-18', 'registration_end')
    assert not evidence.date_supported(text, '2026-11-19', 'registration_end')
    assert evidence.date_supported('A prova será no dia 1º de março de 2027.', '2027-03-01', 'exam_date')
    assert evidence.date_supported('Inscrições até 13/10/2026.', '2026-10-13')
    # still needs the right context
    assert not evidence.date_supported('Publicado em 20 de outubro de 2026.', '2026-10-20', 'registration_start')


ENG_TABLE = """CARGO: ANALISTA DE INFRAESTRUTURA – ÁREA: ENGENHARIA
REMUNERAÇÃO: R$ 12.450,33 *
ÁREA VAGAS AC PCD PN PI PQ
Engenharia Civil 10 6 1 3 0 0
Engenharia Mecânica 1 1 0 0 0 0
CARGO: ADVOGADO
REMUNERAÇÃO: R$ 9.100,00
Advogado 10 6 1 3 0 0"""


def test_salary_in_table_header_is_accepted():
    assert evidence.money_supported_near_role(ENG_TABLE, 12450.33, 'Engenharia Civil')
    assert evidence.money_supported_near_role(ENG_TABLE, 12450.33, 'Engenheiro Mecânico')
    # never borrow the amount of another header or a wrong value
    assert not evidence.money_supported_near_role(ENG_TABLE, 9100.00, 'Engenharia Civil')
    assert not evidence.money_supported_near_role(ENG_TABLE, 7000.00, 'Engenharia Mecânica')


def test_salary_of_another_discipline_is_not_borrowed():
    # Same line, two engineering roles: the amount belongs to the role right before it.
    line = 'Engenheiro Mecânico R$ 8.000,00 Engenheiro Civil R$ 9.500,00'
    assert evidence.money_supported_near_role(line, 8000.00, 'Engenheiro Mecânico')
    assert evidence.money_supported_near_role(line, 9500.00, 'Engenheiro Civil')
    assert not evidence.money_supported_near_role(line, 9500.00, 'Engenheiro Mecânico')
    assert not evidence.money_supported_near_role(line, 8000.00, 'Engenheiro Civil')


def test_position_gate_uses_the_discipline_word():
    text = (
        'EDITAL Nº 1 DE ABERTURA - CONCURSO PÚBLICO. Vagas: Engenheiro Eletricista e Engenheiro Mecânico. '
        'Requisitos gerais. ' * 20
    )
    html = '<html>' + text + '</html>'
    # the edital has engineering roles, but not the civil one asked for
    with pytest.raises(ValueError):
        evidence.prove_document('https://www.gov.br/edital-abertura', html.encode(), 'text/html', 'Engenheiro Civil')
    assert evidence.prove_document(
        'https://www.gov.br/edital-abertura', html.encode(), 'text/html', 'Engenharia Mecânica'
    )


def test_salary_without_label_is_not_borrowed_from_previous_row():
    rows = 'Engenheiro Mecânico R$ 5.000,00\nEngenheiro Civil 3 vagas'
    assert not evidence.money_supported_near_role(rows, 5000.00, 'Engenheiro Civil')
