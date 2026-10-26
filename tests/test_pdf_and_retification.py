from io import BytesIO

from reportlab.pdfgen import canvas

from app import collectors, evidence
from app import repository as repo


def official_pdf_text(text):
    b = BytesIO()
    c = canvas.Canvas(b, pagesize=(595, 842))
    y = 800
    for line in text.split('\n'):
        c.drawString(35, y, line)
        y -= 18
    c.save()
    return b.getvalue()


def test_extract_real_pdf_and_verify_role():
    raw = official_pdf_text(
        'EDITAL Nº 1 DE ABERTURA - CONCURSO PUBLICO\n'
        'Cargo Engenheiro Civil R$ 9.800,00\n'
        'Inscricoes de 01/10/2026 a 20/10/2026\n'
        'Prova objetiva no dia 13/12/2026\n'
        'Requisitos: Curso superior em Engenharia Civil com registro no CREA\n' * 8
    )
    text, kind = evidence.extract('https://www.gov.br/edital.pdf', raw, 'application/pdf')
    assert kind == 'pdf' and 'Engenheiro Civil' in text
    proof = evidence.Proof('https://www.gov.br/edital.pdf', 'a' * 64, text, kind, 'engenheiro civil')
    evidence.check_assertions(
        proof,
        {
            'position': 'Engenheiro Civil',
            'registration_start': '2026-10-01',
            'registration_end': '2026-10-20',
            'exam_date': '2026-12-13',
            'salary_min': 9800,
        },
    )


def test_new_retification_revokes_previous_proof():
    url = 'https://conhecimento.fgv.br/concursos/test26'
    eid, _ = repo.upsert(
        {
            'title': 'Concurso Engenharia',
            'agency': 'Orgao',
            'position': 'Engenheiro Civil',
            'official_url': url,
            'registration_start': '2026-10-01',
            'registration_end': '2026-10-20',
            'confidence': 'official',
            'reviewed': 1,
        }
    )
    repo.record_proof(
        eid, evidence.Proof('https://conhecimento.fgv.br/edital.pdf', 'a' * 64, '', 'pdf', 'analista'), {}
    )
    assert repo.fetch_one(eid)['document_verified']
    assert collectors.monitor_changes(url, [('Retificacao 01', url + '/ret1.pdf')]) == 0
    assert repo.fetch_one(eid)['document_verified']
    assert (
        collectors.monitor_changes(url, [('Retificacao 01', url + '/ret1.pdf'), ('Retificacao 02', url + '/ret2.pdf')])
        == 1
    )
    assert not repo.fetch_one(eid)['document_verified']
    assert any('retificação' in x['text'] for x in repo.get_alerts())
