from datetime import date

import pytest

from app import evidence, status_rules
from app import repository as repo


def sample(**changes):
    d = {
        'title': 'Concurso municipal Engenharia',
        'agency': 'Prefeitura',
        'position': 'Engenheiro Civil',
        'official_url': 'https://www.gov.br/edital',
        'notice_url': 'https://www.gov.br/edital-abertura.pdf',
        'confidence': 'official',
        'reviewed': 1,
        'registration_start': '2026-10-01',
        'registration_end': '2026-10-20',
        'salary_min': 8000,
        'exam_in_sp': 1,
        'work_cities': 'Brasília/DF',
        'national': 1,
    }
    d.update(changes)
    return d


def test_legacy_unverified_never_open():
    oid, _ = repo.upsert(sample())
    assert repo.fetch_one(oid)['status'] == 'verify'
    assert not repo.fetch_one(oid)['salary_highlight']


def test_cannot_upgrade_by_edit():
    oid, _ = repo.upsert(sample())
    assert repo.update_opportunity(oid, {'confidence': 'official', 'reviewed': 1, 'status_override': 'open'})
    assert repo.fetch_one(oid)['status'] == 'verify'


def test_proof_is_gate():
    oid, _ = repo.upsert(sample())
    p = evidence.Proof('https://www.gov.br/edital.pdf', 'c' * 64, 'editais', 'pdf', 'engenheiro civil')
    repo.record_proof(oid, p, sample())
    item = repo.fetch_one(oid)
    assert item['status'] == 'open' and item['salary_highlight']
    assert item['eligible_sp'] and item['national']
    assert item['proof']['sha256'] == 'c' * 64


def test_factual_edit_revokes_proof():
    oid, _ = repo.upsert(sample())
    p = evidence.Proof('https://www.gov.br/edital.pdf', 'a' * 64, '', 'pdf', 'analista')
    repo.record_proof(oid, p, sample())
    repo.update_opportunity(oid, {'salary_min': 20000})
    assert repo.fetch_one(oid)['status'] == 'verify'


def test_favorite_preserves_proof():
    oid, _ = repo.upsert(sample())
    p = evidence.Proof('https://www.gov.br/edital.pdf', 'a' * 64, '', 'pdf', 'analista')
    repo.record_proof(oid, p, sample())
    repo.update_opportunity(oid, {'favorite': 1, 'applied': 1})
    assert repo.fetch_one(oid)['document_verified'] and repo.fetch_one(oid)['favorite']


def test_dedup_preserves_notes():
    oid, created = repo.upsert(sample())
    assert created
    repo.update_opportunity(oid, {'notes': 'Anotação particular'})
    _, created = repo.upsert(sample())
    assert not created
    assert repo.fetch_one(oid)['notes'] == 'Anotação particular'


def test_manual_confidence_does_not_override_gate():
    item = sample(document_verified=False, status_override='open')
    assert status_rules.compute_status(item, date(2026, 10, 16)) == 'verify'
    item['document_verified'] = True
    assert status_rules.compute_status(item, date(2026, 10, 16)) == 'open'
    assert status_rules.compute_status(item, date(2026, 10, 21)) == 'closed'


def test_inclusive_dates():
    i = sample(document_verified=True)
    assert status_rules.compute_status(i, date(2026, 10, 1)) == 'open'
    assert status_rules.compute_status(i, date(2026, 10, 20)) == 'open'
    assert status_rules.compute_status(i, date(2026, 10, 21)) == 'closed'
    assert status_rules.compute_status(i, date(2026, 9, 30)) == 'upcoming'


def test_salary_threshold_verified_only():
    for value, expected in [(6999.99, False), (7000, True), (7356.77, True), (10000, True)]:
        i = sample(salary_min=value, salary_verified=True, document_verified=True)
        assert status_rules.present(i, date(2026, 10, 16))['salary_highlight'] is expected
        i['salary_verified'] = False
        assert not status_rules.present(i, date(2026, 10, 16))['salary_highlight']


def test_reject_bad_date_and_url():
    with pytest.raises(ValueError):
        repo.upsert(sample(registration_end='26/10/2026'))
    with pytest.raises(ValueError):
        repo.upsert(sample(notice_url='javascript:bad'))


def test_candidate_unique():
    repo.upsert_candidate('https://www.gov.br/edital', 'gov', 'Edital', state='pending')
    repo.upsert_candidate('https://www.gov.br/edital', 'gov', 'Edital', state='edital_eng')
    assert len(repo.candidates()) == 1 and repo.candidates()[0]['state'] == 'edital_eng'
