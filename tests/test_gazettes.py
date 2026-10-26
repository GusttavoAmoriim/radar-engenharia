import json

from app import evidence, gazettes, sources, textnorm
from app import repository as repo

SOURCE = sources.Source(
    name='Querido Diário — teste', url='https://api.queridodiario.org.br/gazettes', mode='gazette_search'
)


def gazette(town, uf, url, *excerpts):
    return {
        'territory_id': '3550308',
        'territory_name': town,
        'state_code': uf,
        'date': '2026-10-14',
        'url': url,
        'txt_url': url.replace('.pdf', '.txt'),
        'excerpts': list(excerpts),
    }


RESPONSE = {
    'total_gazettes': 3,
    'gazettes': [
        gazette(
            'Campinas',
            'SP',
            'https://data.queridodiario.ok.org.br/3509502/2026-10-14/a.pdf',
            'EXTRATO DO EDITAL DE ABERTURA DO <b>CONCURSO PÚBLICO</b> 01/2026. Cargo: Engenheiro Civil, '
            'vencimento R$ 6.500,00. Inscrições de 20/10/2026 a 18/11/2026 em www.vunesp.com.br/PCAM2601.',
        ),
        gazette(
            'Sorocaba',
            'SP',
            'https://data.queridodiario.ok.org.br/3552205/2026-10-13/b.pdf',
            'HOMOLOGAÇÃO do resultado final do concurso público para Engenheiro Civil.',
        ),
        gazette(
            'Natal',
            'RN',
            'https://data.queridodiario.ok.org.br/2408102/2026-10-12/c.pdf',
            'Edital de abertura de concurso público com vagas para Engenheiro(a) Mecânico(a). Inscrições abertas.',
        ),
    ],
}


def fake_api(monkeypatch, payload):
    calls = []

    def fetch(url, session=None, *, pace=None, data_api=False):
        calls.append((url, data_api))
        return url, json.dumps(payload).encode(), 'application/json'

    monkeypatch.setattr(evidence, 'fetch_official', fetch)
    return calls


def test_finds_engineering_contests_in_municipal_gazettes(monkeypatch):
    calls = fake_api(monkeypatch, RESPONSE)
    found, added, ok = gazettes.scan_source(SOURCE)
    assert (found, added, ok) == (2, 2, True)
    assert len(calls) == len(gazettes.TERMS) * len(gazettes.KINDS) and all(data_api for _, data_api in calls)
    assert 'querystring=%22concurso+p%C3%BAblico%22+%22engenheiro+civil' in calls[0][0]
    assert any('%22processo+seletivo%22+%22engenharia+civil' in url for url, _ in calls)
    assert 'published_since=2026-09-24' in calls[0][0] and '%7C' not in calls[0][0] and '%28' not in calls[0][0]
    items = {i['agency']: i for i in repo.query_opportunities()}
    campinas = items['Campinas/SP']
    assert campinas['position'] == 'Engenheiro Civil'
    assert campinas['official_url'] == 'https://www.vunesp.com.br/PCAM2601'
    assert campinas['status'] == 'verify' and campinas['confidence'] == 'discovery'
    assert 'Querido Diário' in campinas['notes']
    assert 'Sorocaba/SP' not in items  # results/homologations are not openings
    assert items['Natal/RN']['position'] == 'Engenheiro(a) Mecânico(a)'
    # second run: nothing new, no duplicates
    assert gazettes.scan_source(SOURCE)[:2] == (2, 0)


def test_uf_filter(monkeypatch):
    fake_api(monkeypatch, RESPONSE)
    only_sp = sources.Source(name='QD SP', url=SOURCE.url, mode='gazette_search', uf='SP')
    assert gazettes.scan_source(only_sp)[:2] == (1, 1)


def test_api_is_allowed_only_for_gazette_search():
    assert evidence.data_api_url('https://api.queridodiario.org.br/gazettes')
    assert not evidence.official_url('https://api.queridodiario.org.br/gazettes')
    ok = sources.parse({'sources': [{'name': 'QD', 'url': SOURCE.url, 'mode': 'gazette_search'}]})
    assert ok[0].mode == 'gazette_search'
    for bad in (
        {'name': 'QD', 'url': SOURCE.url, 'mode': 'catalog'},
        {'name': 'X', 'url': 'https://www.gov.br/x', 'mode': 'gazette_search'},
    ):
        try:
            sources.parse({'sources': [bad]})
        except sources.SourceError:
            continue
        raise AssertionError(bad)


def test_bad_json_is_reported(monkeypatch):
    monkeypatch.setattr(evidence, 'fetch_official', lambda url, session=None, **k: (url, b'<html>', 'text/html'))
    assert gazettes.scan_source(SOURCE)[2] is False
    assert 'JSON' in repo.source_health()[0]['error']


def test_one_failing_search_keeps_the_others(monkeypatch):
    def fetch(url, session=None, *, pace=None, data_api=False):
        if 'engenharia+mec' in url:
            raise ValueError('500 Server Error: Internal Server Error for url: x')
        return url, json.dumps(RESPONSE).encode(), 'application/json'

    monkeypatch.setattr(evidence, 'fetch_official', fetch)
    found, added, ok = gazettes.scan_source(SOURCE)
    assert (found, added, ok) == (2, 2, False)
    error = repo.source_health()[0]['error']
    assert error.startswith('Cobertura PARCIAL: 2 de 8') and 'for url' not in error


APPOINTMENT = (
    'a partir de 16 de outubro de 2026, o Senhor FULANO DE TAL, CPF. 123.456.789-09, para exercer o cargo '
    'estatutário de ENGENHEIRO CIVIL, Nível Salarial RL1A, com jornada de 40 horas semanais, tendo em vista a '
    'aprovação e classificação no Concurso Público - Edital 01/2023. Artigo 2º - Esta'
)


def test_appointment_of_an_approved_candidate_is_not_an_opening():
    assert not gazettes.relevant(APPOINTMENT)
    # even without the other markers, a CPF number means the excerpt is about a person
    assert not gazettes.relevant('Concurso público edital 01/2026 Engenheiro Civil, CPF 123.456.789-09')
    assert gazettes.relevant('Edital de abertura do concurso público para Engenheiro Civil. Inscrições abertas.')


def test_old_cards_with_personal_data_are_hidden_and_wiped():
    keep, _ = repo.upsert(
        dict(title='Aberto', position='Engenheiro Civil', source='x', fingerprint='keep', notes='Edital de abertura')
    )
    leak, _ = repo.upsert(
        dict(
            title='Antigo', position='Engenheiro Civil', source='x', fingerprint='leak', notes=f'Trecho: {APPOINTMENT}'
        )
    )
    repo.upsert_candidate(
        'https://data.queridodiario.ok.org.br/a.pdf', 'x', 'Antigo', '', state='gazette_eng', detail=APPOINTMENT
    )
    assert repo.scrub_personal_data() == 2
    assert repo.fetch_one(leak)['dismissed'] == 1 and '123.456.789-09' not in repo.fetch_one(leak)['notes']
    assert not repo.fetch_one(keep)['dismissed']
    assert all('123.456.789-09' not in c['detail'] for c in repo.candidates())
    assert repo.scrub_personal_data() == 0


RANKING = (
    'Vigia, Encarregado do Setor de Arrecadação e Atendimento – PCD e Vigia - PCD, classificados em ordem '
    'decrescente de notas, conforme Edital de Concurso Público 001/2026, de 18 de agosto de 2026, a saber: '
    'ENGENHEIRO CIVIL ---------'
)


def test_ranking_list_of_a_finished_contest_is_not_an_opening():
    assert not gazettes.relevant(RANKING)
    assert gazettes.blocked(RANKING)
    assert gazettes.relevant('Edital de abertura do concurso público para Engenheiro Civil. Inscrições abertas.')


def test_old_cards_with_blocked_excerpts_are_hidden_but_user_marked_ones_are_kept(monkeypatch):
    def card(fp, notes, **extra):
        oid, _ = repo.upsert(
            dict(
                title=fp, position='Engenheiro Civil', source='Querido Diário — x', fingerprint=fp, notes=notes, **extra
            )
        )
        return oid

    ranking = card('ranking', f'Encontrado no Diário. Trecho: “{RANKING}”. Diário: https://x')
    starred = card('starred', f'Trecho: “{RANKING}”', favorite=1)
    opening = card('opening', 'Trecho: “Edital de abertura do concurso público para Engenheiro Civil.”')
    assert gazettes.dismiss_stale_discoveries() == 1
    assert repo.fetch_one(ranking)['dismissed'] == 1 and 'Ocultado automaticamente' in repo.fetch_one(ranking)['notes']
    assert not repo.fetch_one(starred)['dismissed'] and not repo.fetch_one(opening)['dismissed']
    assert gazettes.dismiss_stale_discoveries() == 0


def test_role_keeps_its_closing_parenthesis():
    assert gazettes.role_of('Especialidade Engenharia (graduação civil), vagas') == 'Engenharia (graduação civil)'


def test_teaching_post_keeps_professor_in_the_role():
    text = 'Processo seletivo para Professor de Engenharia Civil, graduação exigida. Inscrições abertas.'
    assert gazettes.role_of(text) == 'Professor – Engenharia Civil'
    assert gazettes.role_of('Processo seletivo para Engenheiro Civil, edital de abertura.') == 'Engenheiro Civil'
    assert gazettes.relevant(text + ' Edital de abertura.')
    assert textnorm.is_target('Professor – Engenharia Civil')


def test_known_portal_is_attached_to_gazette_cards(monkeypatch):
    from app import portals

    portal = 'https://concursos.curitiba.pr.gov.br/listar/1/2'
    assert portals.for_territory('4106902') == portal
    assert portals.for_gazette_url('https://data.queridodiario.ok.org.br/4106902/2026-10-09/x.pdf') == portal
    assert portals.for_territory('9999999') is None
    old = repo.upsert(
        dict(
            title='Curitiba',
            position='Engenheiro Civil',
            source='Querido Diário — x',
            fingerprint='cwb',
            official_url='https://data.queridodiario.ok.org.br/4106902/2026-10-09/x.pdf',
        )
    )[0]
    assert portals.attach_existing() == 1
    assert repo.fetch_one(old)['official_url'] == portal
