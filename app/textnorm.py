"""Text normalisation and the engineering vocabulary shared by collectors, evidence checks and search.

The radar follows higher-education (nível superior) roles in civil and mechanical engineering.
A role counts only when "engenheiro/engenheira/engenharia" and "civil/mecânico/mecânica" sit
together (optionally with up to three words between them, as in "Engenheiro de Equipamentos
Júnior – Mecânica"). "Civil" or "mecânico" alone never counts: that would pull in Polícia Civil,
Defesa Civil, direito civil and mechanic/technician jobs.
"""

import re
import unicodedata

AREA = 'engenharia civil ou mecânica'

# Stored in the triage table when a readable edital has no role of the area. The text is also
# the prefix used to recognise and prune those rows, so it lives here, in one place.
NO_ROLE = 'Edital sem cargo de engenharia civil ou mecânica'


def fold(value):
    """Lower-case and strip accents: 'Engenharia Mecânica' -> 'engenharia mecanica'."""
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '')) if not unicodedata.combining(c)).lower()


_GAP = r'[\s\-–—/:()]+'
_TARGET = re.compile(
    r'\bengenh(?:eiros?|eiras?|aria)(?:\((?:a|o)\))?'
    r'(?:' + _GAP + r'[a-z]+){0,3}?' + _GAP + r'(civil|civis|mecanic[oa]s?)\b'
)

# "<word> civil" that is not engineering even when "engenharia" appears a few words before it
# ("Engenheiro Eletricista – Polícia Civil").
_NOT_ENGINEERING = (
    'policia',
    'defesa',
    'direito',
    'codigo',
    'processo',
    'guarda',
    'justica',
    'registro',
    'sociedade',
    'responsabilidade',
    'servico',
    'servidor',
    'protecao',
)


def find_target(text):
    """Regex matches of a civil or mechanical engineering role in text that was already folded."""
    found = []
    for m in _TARGET.finditer(text):
        words = re.findall(r'[a-z]+', m.group(0))
        if m.group(1) in ('civil', 'civis') and len(words) >= 3 and words[-2] in _NOT_ENGINEERING:
            continue
        found.append(m)
    return found


def is_target(text):
    """True when a cargo/description clearly names a civil or mechanical engineering role."""
    return bool(find_target(fold(text)))


_TEMPORARY = re.compile(
    r'processo\s+seletivo\s+simplificado|\bpss\b|contratacao\s+temporaria|regime\s+especial\s+de\s+contratacao'
)


def is_temporary(text):
    """True for temporary hiring (processo seletivo simplificado, regime especial de contratação).

    These are not "concursos públicos": the contract has a term and there is no stability.
    """
    return bool(_TEMPORARY.search(fold(text)))
