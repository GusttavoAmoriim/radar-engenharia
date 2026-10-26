"""Assisted extraction: propose values from an official notice. Nothing is saved here.

The administrator sees each suggestion with the sentence it came from and accepts or ignores it.
Only empty fields are offered for filling, and a value is suggested only when the words around it
match the field (for example, a date next to “inscrições … até”).
"""

import re
from datetime import date

from . import textnorm

DATE_RE = re.compile(r'(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)')
MONEY_RE = re.compile(r'R\$\s*([\d.]+,\d{2})')
SENTENCE_END = re.compile(r'[.;\n]')
MAX_SENTENCE = 320


def _sentence(text, start, end):
    """The sentence holding a match, as (folded sentence, match start, match end) inside it."""
    left = max([m.end() for m in SENTENCE_END.finditer(text, 0, start)] or [0])
    left = max(left, start - MAX_SENTENCE)
    right_match = SENTENCE_END.search(text, end)
    right = right_match.start() if right_match else len(text)
    right = min(right, end + MAX_SENTENCE)
    sentence = text[left:right]
    return textnorm.fold(sentence), start - left, end - left


def _snippet(text, start, end):
    return ' '.join(text[max(0, start - 90) : end + 90].split())[:260]


def dates(text):
    """Dates with a label from words in the same sentence. Returns {field: [(iso, snippet), ...]}.

    A date is the end of registration when “até/encerra/termina” comes just before it; the start
    when “das/a partir de/início/abertura” comes just before it, or “até” comes right after it.
    """
    found = {}
    for m in DATE_RE.finditer(text):
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            iso = date(year, month, day).isoformat()
        except ValueError:
            continue
        sentence, s_start, s_end = _sentence(text, m.start(), m.end())
        prefix, after = sentence[:s_start][-60:], sentence[s_end:][:20]
        if 'prova' in sentence and 'inscri' not in sentence:
            field = 'exam_date'
        elif 'inscri' not in sentence:
            continue
        elif re.search(r'\b(ate|encerr|termin)', prefix):
            field = 'registration_end'
        elif re.search(r'(a partir|inicio|inicia|abertura|\bdas\b)', prefix) or re.search(r'^\W*ate\b', after):
            field = 'registration_start'
        else:
            continue
        found.setdefault(field, []).append((iso, _snippet(text, m.start(), m.end())))
    return found


def salaries(text, role=''):
    """Monthly amounts in reais, only when the role words are in the same sentence."""
    words = [w for w in re.findall('[a-z]{4,}', textnorm.fold(role)) if w not in ('cargo', 'concurso', 'publico')]
    out = []
    if not words:
        return out
    for m in MONEY_RE.finditer(text):
        sentence, _s, _e = _sentence(text, m.start(), m.end())
        if not all(w in sentence for w in words[:2]):
            continue
        value = float(m.group(1).replace('.', '').replace(',', '.'))
        if value < 1000 or value > 200000:
            continue
        out.append((value, _snippet(text, m.start(), m.end())))
    return out


def suggest(text, role=''):
    """All suggestions for one notice, keyed by repository field name.

    Each value is (value, snippet). For dates the first unambiguous match wins; if two different
    dates are found for the same field, nothing is suggested for that field.
    """
    result = {}
    for field, items in dates(text).items():
        if len({iso for iso, _ in items}) == 1:
            result[field] = items[0]
    money = salaries(text, role)
    if money and len({v for v, _ in money}) == 1:
        result['salary_min'] = money[0]
    return result
