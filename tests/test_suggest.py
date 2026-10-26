from fastapi.testclient import TestClient

from app import suggest
from app.main import app

EDITAL = """
EDITAL Nº 01/2026 DE ABERTURA DO CONCURSO PÚBLICO.
Período de inscrições: das 10h do dia 02/03/2026 até as 23h59 do dia 31/03/2026.
Cargo: Engenheiro Civil, vencimento R$ 8.250,00 mensais.
A prova objetiva será aplicada em 10/05/2026 nas capitais.
Outro cargo: Auxiliar administrativo, vencimento R$ 2.100,00.
"""


def test_dates_are_labelled_by_nearby_words():
    found = suggest.dates(EDITAL)
    assert found['registration_start'][0][0] == '2026-03-02'
    assert found['registration_end'][0][0] == '2026-03-31'
    assert found['exam_date'][0][0] == '2026-05-10'


def test_salary_needs_the_role_nearby():
    values = [v for v, _ in suggest.salaries(EDITAL, 'Engenheiro Civil')]
    assert 8250.0 in values
    assert 2100.0 not in values


def test_suggest_returns_snippets_and_skips_ambiguous_dates():
    found = suggest.suggest(EDITAL, 'Engenheiro Civil')
    assert found['registration_end'][0] == '2026-03-31'
    assert 'até' in found['registration_end'][1] or 'inscri' in found['registration_end'][1]
    assert found['salary_min'][0] == 8250.0
    ambiguous = EDITAL + 'Inscrições até 15/04/2026.\n'
    assert 'registration_end' not in suggest.suggest(ambiguous, 'Engenheiro Civil')


def test_invalid_calendar_dates_are_ignored():
    assert suggest.dates('inscrições até 31/02/2026') == {}


def test_suggest_endpoint_requires_admin_and_official_link(monkeypatch):
    monkeypatch.setenv('RADAR_PUBLIC', '1')
    with TestClient(app) as cli:
        # visitors cannot trigger the read (POST is admin-only)
        assert cli.post('/api/opportunities/999999/suggest', json={}).status_code in (401, 403)
