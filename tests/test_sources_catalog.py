from fastapi.testclient import TestClient

from app.main import app

PASSWORD = 'Very-Strong-Password-TEST-1234'


def test_catalog_lists_disabled_sources_with_agency_and_uf(monkeypatch, tmp_path):
    file = tmp_path / 'sources.yaml'
    file.write_text(
        'sources:\n'
        '  - name: Fonte ligada\n'
        '    url: https://www.gov.br/concursos\n'
        '    agency: Órgão A\n'
        '    uf: sp\n'
        '  - name: Fonte desligada\n'
        '    url: https://www.gov.br/outra\n'
        '    enabled: false\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('RADAR_SOURCES_FILE', str(file))
    with TestClient(app) as cli:
        h = {'X-CSRF-Token': cli.post('/api/auth/login', json={'password': PASSWORD}).json()['csrf']}
        catalog = cli.get('/api/sources', headers=h).json()['catalog']
    by_name = {c['name']: c for c in catalog}
    assert by_name['Fonte ligada']['uf'] == 'SP'
    assert by_name['Fonte ligada']['agency'] == 'Órgão A'
    assert by_name['Fonte ligada']['enabled'] is True
    assert by_name['Fonte desligada']['enabled'] is False
