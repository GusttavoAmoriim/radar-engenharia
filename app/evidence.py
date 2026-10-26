"""Fail-closed proof checks. Official HTTPS + original edital + role-specific evidence.
No headline, salary band from a landing page or mere organizer domain is proof.
"""

import hashlib
import io
import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from . import __version__, polite, robots, textnorm

# Exact hosts or government / public-school namespaces. No partial substring matches.
ORGANIZERS = frozenset(
    {
        'www.vunesp.com.br',
        'vunesp.com.br',
        'documento.vunesp.com.br',
        'www.concursosfcc.com.br',
        'concursosfcc.com.br',
        'conhecimento.fgv.br',
        'portal.conhecimento.fgv.br',
        'www.cebraspe.org.br',
        'cebraspe.org.br',
        'cdn.cebraspe.org.br',
        'www.ibam-concursos.org.br',
        'ibam-concursos.org.br',
        'abcp.selecao.net.br',
        'www.ibamsp-concursos.org.br',
        'www.institutoaocp.org.br',
        'institutoaocp.org.br',
    }
)
EDU_HOSTS = (
    'ifsp.edu.br',
    'unicamp.br',
    'usp.br',
    'unesp.br',
    'ufscar.br',
    'unifesp.br',
    'ufabc.edu.br',
    'ufscar.edu.br',
)
# Public data APIs that are allowed to be queried but are never proof of an edital.
DATA_APIS = frozenset({'api.queridodiario.org.br'})
# A municipal gazette with a dozen editais easily reaches 15 MB.
MAX_BYTES = 30_000_000
MAX_TEXT = 3_000_000
# Sites must be able to tell who is reading them. RADAR_CONTACT (a URL or e-mail) is appended when set.
_CONTACT = os.getenv('RADAR_CONTACT', '').strip()[:120]
UA = (
    f'RadarEngenharia/{__version__} (fork of radar-public-sector; official-notice verification, 8 scans/day'
    + (f'; {_CONTACT}' if _CONTACT else '')
    + ')'
)


def official_host(host):
    host = (host or '').lower().rstrip('.')
    return (
        host in ORGANIZERS
        or host.endswith(('.gov.br', '.jus.br', '.leg.br'))
        or any(host == ed or host.endswith('.' + ed) for ed in EDU_HOSTS)
    )


def data_api_url(url):
    try:
        p = urlparse(str(url))
        return p.scheme == 'https' and p.port in (None, 443) and (p.hostname or '').lower() in DATA_APIS
    except (ValueError, TypeError):
        return False


def official_url(url):
    try:
        p = urlparse(str(url))
        return (
            p.scheme == 'https'
            and not p.username
            and not p.password
            and p.port in (None, 443)
            and official_host(p.hostname)
        )
    except (ValueError, TypeError):
        return False


def guard_public(host):
    # Prevent server-side requests to internal/private addresses, including DNS rebinding.
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    for a in addresses:
        ip = ipaddress.ip_address(a[4][0])
        if not ip.is_global:
            raise ValueError('Destino de rede não público')


def unwrap_viewer(url):
    """FCC links open PDFs through an accessibility viewer: .../rybena/web/index.html?file=<pdf>.

    The viewer page is not the document, so use the PDF address it points to
    (only when that address is itself an allowed official URL).
    """
    parts = urlparse(url)
    if '/rybena/' in parts.path.lower():
        for value in parse_qs(parts.query).get('file', []):
            if official_url(value):
                return value
    return url


def decode_html(raw):
    """Decode page bytes: UTF-8 when valid, otherwise the declared charset (default Windows-1252)."""
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    found = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', raw[:4096], re.I)
    for name in ([found.group(1).decode('ascii')] if found else []) + ['cp1252']:
        try:
            return raw.decode(name, errors='replace')
        except LookupError:
            continue
    return raw.decode('utf-8', errors='replace')


def fetch_official(url, session=None, *, pace=None, data_api=False):
    """Fetch a real official URL; refuse forbidden domains/redirects and obey 403/429.

    Injectable sessions default to unpaced for deterministic unit tests. Real
    worker and API traffic is paced and shares the persisted backoff table.
    """

    def allowed(target):
        return official_url(target) or (data_api and data_api_url(target))

    if not allowed(url):
        raise ValueError('Endereço fora dos domínios oficiais permitidos')
    if pace is None:
        pace = session is None
    client = session or requests.Session()
    current = url
    for _redirects in range(5):
        if not allowed(current):
            raise ValueError('Redirecionamento para destino não oficial')
        host = urlparse(current).hostname
        if session is None:
            guard_public(host)
            robots.check(current)
        from contextlib import nullcontext

        with polite.request_lane(host) if pace else nullcontext():
            response = client.get(
                current,
                headers={'User-Agent': UA, 'Accept': 'text/html,application/pdf;q=0.9,*/*;q=0.5'},
                timeout=(8, 25),
                allow_redirects=False,
                stream=True,
            )
            if response.status_code in (403, 429):
                code = response.status_code
                retry = response.headers.get('Retry-After')
                response.close()
                # Tests may supply a fake session; keep 403/429 handling in tests
                # but do not mutate persisted limiter state for unpaced sessions.
                if pace:
                    raise polite.reject(host, code, retry)
                raise ValueError(f'HTTP {code}: acesso recusado pelo domínio oficial {host}')
            if response.status_code in (301, 302, 303, 307, 308):
                target = requests.compat.urljoin(response.url, response.headers.get('location', ''))
                response.close()
                if not allowed(target):
                    raise ValueError('Redirecionamento para destino não oficial')
                current = target
                continue
            try:
                response.raise_for_status()
                size = 0
                parts = []
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError('Documento excede 30 MB')
                    parts.append(chunk)
                data = b''.join(parts)
                mime = response.headers.get('Content-Type', '').lower().split(';')[0]
                return response.url, data, mime
            finally:
                response.close()
    raise ValueError('Muitos redirecionamentos')


def extract(url, raw, mime):
    if raw.startswith(b'%PDF'):
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise ValueError('PDF protegido')
        if len(reader.pages) > 500:
            raise ValueError('PDF muito longo')
        return '\n'.join((p.extract_text() or '') for p in reader.pages)[:MAX_TEXT], 'pdf'
    if mime in ('text/html', 'application/xhtml+xml') or raw.lstrip().lower().startswith((b'<!doctype html', b'<html')):
        soup = BeautifulSoup(raw, 'html.parser')
        for e in soup(['script', 'style', 'footer', 'nav', 'header']):
            e.decompose()
        return soup.get_text(' ', strip=True)[:1_000_000], 'html'
    raise ValueError('Tipo de documento não reconhecido')


@dataclass
class Proof:
    url: str
    sha256: str
    text: str
    kind: str
    role_excerpt: str
    temporary: bool = False


KINDS = ('concurso publico', 'processo seletivo publico', 'processo seletivo simplificado')
DISCIPLINES = ('civil', 'mecanic')
GENERIC_ROLE_WORDS = ('engenh', 'analista', 'junior', 'pleno', 'senior', 'tecnico', 'especialista')


def stem(word):
    """'engenheiro/engenheira/engenharia' -> 'engenh', 'mecanico/mecanica' -> 'mecanic'."""
    for root in ('engenh', 'mecanic'):
        if word.startswith(root):
            return root
    return word


def notice_proof(url, *, session=None, position=''):
    # PDFs are preferred. Explicitly titled official edital HTML is acceptable only if text is substantive.
    resolved, raw, mime = fetch_official(url, session)
    return prove_document(resolved, raw, mime, position)


# Opening-edital titles that can start a section inside a gazette ("EDITAL NORMATIVO DE PROCESSO SELETIVO
# SIMPLIFICADO Nº 09/2026", "EDITAL DE ABERTURA DO CONCURSO PÚBLICO Nº 01/2026"). The number is required, so
# cross-references like "este Edital Normativo" do not split a section.
EDITAL_HEADING = re.compile(
    r'edital\s+(?:normativo\s+)?(?:de\s+|do\s+)?(?:abertura\s+)?(?:de\s+|do\s+)?'
    r'(?:concurso\s+publico|processo\s+seletivo\s+(?:publico|simplificado))\s+n[o.]?\s*\d+\s*/\s*20\d\d'
)
# A heading right after one of these words is an amendment of an edital, not the opening.
AMENDMENT = re.compile(r'retifica|errata|aditamento|suspens|cancelamento|prorrogacao|resultado|homologa')
OPENING = re.compile(r'edital\s+(?:n[ºo°.]?\s*0?1\b|de\s+abertura|de\s+inscricoes|0?1\s*/\s*20\d\d)')


def is_gazette(norm):
    return 'diario oficial' in norm[:4000]


def gazette_sections(norm):
    """Opening-edital sections of a gazette as (start, end) spans of the folded text, in order.

    Returns (spans, titles): titles counts every numbered edital title, amendments included, so the
    caller can tell "no editais here" from "only amendments here".
    """
    found = [m.start() for m in EDITAL_HEADING.finditer(norm)]
    heads = [h for h in found if not AMENDMENT.search(norm[max(0, h - 80) : h])]
    return [(h, heads[i + 1] if i + 1 < len(heads) else len(norm)) for i, h in enumerate(heads)], len(found)


def has_role_nearby(norm, position):
    """The words of the cargo appear together, anchored on the most specific one ("civil", "mecanic")."""
    significant = [
        stem(w)
        for w in re.findall(r'[a-z]{4,}', textnorm.fold(position))
        if w not in ('cargo', 'concurso', 'publico', 'federal', 'superior', 'controle', 'especialidade')
    ]
    if not significant:
        raise ValueError('Cargo pouco específico para validação')
    # Anchor on the most specific word: "engenheiro" alone shows up for every engineering role in a
    # multi-position edital. Then require the other words of the role nearby.
    anchor = next((w for w in significant if w not in GENERIC_ROLE_WORDS), significant[0])
    windows = [norm[max(0, m.start() - 100) : m.end() + 240] for m in re.finditer(re.escape(anchor), norm)]
    return any(sum(w in window for w in significant[:6]) >= min(2, len(significant)) for window in windows)


def prove_document(resolved, raw, mime, position=''):
    """Check already downloaded bytes: opening edital (concurso or temporary selection) with an engineering role.

    A gazette holds many editais: only the section of the edital that names the role is kept as proof, so
    dates and salary of another edital in the same issue can never support this one.
    """
    text, kind = extract(resolved, raw, mime)
    norm = textnorm.fold(text)
    if len(norm) < 350:
        raise ValueError('Edital sem texto legível; revisão manual obrigatória')
    if not ('edital' in norm and any(k in norm for k in KINDS)):
        raise ValueError('O arquivo não demonstra ser edital de concurso público')
    if position and not textnorm.is_target(position):
        raise ValueError('Cargo pouco específico para validação')
    spans, titles = gazette_sections(norm) if kind == 'pdf' and is_gazette(norm) else ([], 0)
    if titles and not spans:
        raise ValueError('Não foi comprovado que o documento seja o edital inicial de abertura')
    if spans:
        # A gazette with numbered editais: judge each one on its own, never the whole issue.
        with_role = [norm[a:b] for a, b in spans if textnorm.find_target(norm[a:b])]
        if not with_role:
            raise ValueError(textnorm.NO_ROLE + ' identificável')
        sections = [sec for sec in with_role if not position or has_role_nearby(sec, position)]
        if not sections:
            raise ValueError('Cargo/especialidade específicos não encontrados juntos no edital')
        norm = sections[0]
        text = norm  # already folded: every later check folds again, which changes nothing
    else:
        head = norm[:5000]
        starts_as_pss = bool(
            re.search(r'edital\s+(?:normativo|de\s+processo\s+seletivo\s+simplificado)', head)
            and re.search(r'processo\s+seletivo\s+simplificado\s+n[o.]?\s*\d+\s*/\s*20\d\d', head)
            and not AMENDMENT.search(norm[:600])
        )
        if not (OPENING.search(head) or starts_as_pss):
            raise ValueError('Não foi comprovado que o documento seja o edital inicial de abertura')
        if kind == 'html' and 'edital' not in urlparse(resolved).path.lower():
            raise ValueError('Página HTML não identifica documento edital no endereço')
    hits = textnorm.find_target(norm)
    if not hits:
        raise ValueError(textnorm.NO_ROLE + ' identificável')
    # Position-specific gate. Reject when role absent, do not borrow salary of a different job.
    if position and not has_role_nearby(norm, position):
        raise ValueError('Cargo/especialidade específicos não encontrados juntos no edital')
    excerpt = norm[max(0, hits[0].start() - 130) : hits[0].end() + 220]
    return Proof(
        resolved, hashlib.sha256(raw).hexdigest(), text, kind, excerpt[:350], textnorm.is_temporary(norm[:3000])
    )


MONTHS = (
    'janeiro',
    'fevereiro',
    'marco',
    'abril',
    'maio',
    'junho',
    'julho',
    'agosto',
    'setembro',
    'outubro',
    'novembro',
    'dezembro',
)


def date_matches(content, iso):
    """Find a date written as 13/10/2026 or as '13 de outubro de 2026' (also '1º de março de 2026')."""
    y, m, d = iso.split('-')
    numeric = r'(?<!\d)' + re.escape(d) + '[./-]' + re.escape(m) + '[./-]' + re.escape(y) + r'(?!\d)'
    words = (
        r'(?<!\d)0?'
        + str(int(d))
        + r'\s*(?:o|º|°)?\s+de\s+'
        + MONTHS[int(m) - 1]
        + r'\s+(?:de\s+)?'
        + re.escape(y)
        + r'(?!\d)'
    )
    return list(re.finditer(numeric, content)) + list(re.finditer(words, content))


def date_supported(text, iso, kind='registration_end'):
    if not iso:
        return True
    content = textnorm.fold(text)
    for match in date_matches(content, iso):
        around = content[max(0, match.start() - 500) : match.end() + 500]
        context = (
            ('inscri', 'periodo de inscricao', 'cronograma')
            if kind.startswith('registration')
            else ('prova', 'cronograma')
        )
        if any(word in around for word in context):
            return True
    return False


def money_supported_near_role(text, salary, role):
    if salary is None:
        return True
    # Must find the salary on the same extracted line as the specific job.
    # This intentionally rejects edital-wide salary bands.
    if not role:
        return False
    rolewords = [
        stem(w)
        for w in re.findall('[a-z]{4,}', textnorm.fold(role))
        if w not in ('cargo', 'concurso', 'publico', 'especialidade', 'superior')
    ]
    if not rolewords:
        return False
    # Most specific word first ("civil"): every engineering role starts with "engenheiro".
    rolewords.sort(key=lambda w: w in GENERIC_ROLE_WORDS)
    mine = [d for d in DISCIPLINES if any(w.startswith(d) for w in rolewords)]
    br = f'{salary:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    variants = (br, br.replace('.', ''), f'{salary:.2f}')
    for line in textnorm.fold(text).splitlines():
        for variant in variants:
            for m in re.finditer(re.escape(variant), line):
                # Nearby role, not any other role elsewhere in a long sentence.
                previous = line[max(0, m.start() - 140) : m.start()]
                if sum(w in previous for w in rolewords[:5]) < min(2, len(rolewords)):
                    continue
                # A row of another discipline between this role and the amount owns that amount:
                # "Engenheiro Mecânico R$ 8.000 ... Engenheiro Civil" must not credit R$ 8.000 to the civil role.
                if mine:
                    last_mine = max(previous.rfind(d) for d in mine)
                    if any(previous.rfind(d) > last_mine for d in DISCIPLINES if d not in mine):
                        continue
                # If another explicitly labeled cargo occurs AFTER the target role,
                # we cannot attribute the salary with confidence.
                first = previous.rfind(rolewords[0])
                if first < 0:
                    continue
                intervening = previous[first + len(rolewords[0]) :]
                if re.search(r'\bcargo\s+[a-z]{4,}', intervening):
                    continue
                return True
    return money_supported_by_table_header(text, salary, rolewords)


def money_supported_by_table_header(text, salary, rolewords):
    """Accept a 'REMUNERAÇÃO: R$ x' header that precedes a table listing the role.

    The salary must be the closest amount before the role and carry a salary label,
    so a value from another role's row is never borrowed.
    """
    content = textnorm.fold(text)
    br = f'{salary:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    amounts = list(re.finditer(r'r\$\s*([\d.]+,\d{2})', content))
    if not amounts:
        return False
    for m in re.finditer(re.escape(rolewords[0]), content):
        # The role name may start just before the specific word ("engenheiro civil").
        window = content[max(0, m.start() - 60) : m.start() + 120]
        if sum(w in window for w in rolewords[:5]) < min(2, len(rolewords)):
            continue
        before = [a for a in amounts if a.end() <= m.start() and m.start() - a.end() <= 1200]
        if not before:
            continue
        nearest = before[-1]
        label = content[max(0, nearest.start() - 60) : nearest.start()]
        if nearest.group(1) == br and re.search(r'remuneracao|vencimento|salario|subsidio', label):
            return True
    return False


def location_supported(text, city, kind):
    if not city:
        return True
    norm = textnorm.fold(text)
    tokens = [
        t for t in re.findall(r'[a-z]{4,}', textnorm.fold(city)) if t not in ('regiao', 'estado', 'brasil', 'cidade')
    ]
    if not tokens:
        return False
    flags = (
        ('local de prova', 'cidades de realizacao', 'aplicacao da prova', 'provas serao', 'prova objetiva')
        if kind == 'exam'
        else ('lotacao', 'local de trabalho', 'localidade', 'unidade de exercicio', 'municipio')
    )
    for m in re.finditer(re.escape(tokens[0]), norm):
        window = norm[max(0, m.start() - 250) : m.end() + 250]
        if any(f in window for f in flags):
            return True
    # "provas nas 27 capitais" / "em todas as capitais" includes the capital São Paulo.
    if kind == 'exam' and tokens == ['paulo']:
        for m in re.finditer(r'(?:27|vinte e sete|todas as)\s+capitais', norm):
            window = norm[max(0, m.start() - 250) : m.end() + 250]
            if 'prova' in window:
                return True
    return False


_NUM_DATE = r'(\d{1,2})[./-](\d{1,2})[./-](20\d\d)'
_WORD_DATE = r'(\d{1,2})\s*(?:o|º|°)?\s+de\s+(' + '|'.join(MONTHS) + r')\s+(?:de\s+)?(20\d\d)'
_ANY_DATE = re.compile(_NUM_DATE + '|' + _WORD_DATE)


def _dates_in(text):
    """(iso, start, end) for every date written as 13/10/2026 or '13 de outubro de 2026'."""
    found = []
    for m in _ANY_DATE.finditer(text):
        try:
            if m.group(1):
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                d, mo, y = int(m.group(4)), MONTHS.index(m.group(5)) + 1, int(m.group(6))
            found.append((date(y, mo, d).isoformat(), m.start(), m.end()))
        except ValueError:
            continue
    return found


def extract_facts(proof, position=''):
    """Dates and salary the edital states without ambiguity. A fact with two readings is left out.

    Registration period: the dates that follow the word "inscrições" and are joined by "a/até/e".
    Exam: the single date written next to "prova objetiva". Salary: the single amount that
    money_supported_near_role attributes to this role. When in doubt the field stays empty.
    """
    norm = textnorm.fold(proof.text)
    facts = {}
    periods = set()
    for m in re.finditer(r'inscri\w*', norm):
        window = norm[m.end() : m.end() + 160]
        if re.search(r'isencao|pedido|recurso|treinamento', window[:60]):
            continue
        dates = _dates_in(window)
        if (
            len(dates) >= 2
            and dates[0][0] <= dates[1][0]
            and re.fullmatch(r'\s*(?:a|as|ate|e|ate o dia|a partir do dia|-|–)?\s*', window[dates[0][2] : dates[1][1]])
        ):
            periods.add((dates[0][0], dates[1][0]))
    if len(periods) == 1:
        facts['registration_start'], facts['registration_end'] = next(iter(periods))
    exams = set()
    for m in re.finditer(r'prova\s+objetiva', norm):
        near = _dates_in(norm[max(0, m.start() - 120) : m.end() + 120])
        exams.update(d[0] for d in near)
    exams.discard(facts.get('registration_end'))
    exams.discard(facts.get('registration_start'))
    if len(exams) == 1:
        exam = next(iter(exams))
        if exam >= facts.get('registration_start', exam):
            facts['exam_date'] = exam
    if position:
        values = set()
        for m in list(re.finditer(r'r\$\s*([\d.]+,\d{2})', norm))[:60]:
            value = float(m.group(1).replace('.', '').replace(',', '.'))
            if value >= 1500 and value not in values and money_supported_near_role(proof.text, value, position):
                values.add(value)
        if len(values) == 1:
            facts['salary_min'] = facts['salary_max'] = next(iter(values))
    return facts


def assertion_failures(proof, data):
    """Every claimed fact that the edital does not support, as (field, message) pairs."""
    failures = []
    for k in ('registration_start', 'registration_end', 'exam_date'):
        if data.get(k) and not date_supported(proof.text, data[k], k):
            failures.append(
                (k, f'{k}: data não localizada no documento. Anexe retificação oficial ou deixe em branco.')
            )
    if data.get('exam_in_sp') and not location_supported(proof.text, 'São Paulo', 'exam'):
        failures.append(('exam_in_sp', 'Prova em SP ainda não demonstrada no edital'))
    if data.get('work_in_sp') and not location_supported(proof.text, 'São Paulo', 'work'):
        failures.append(('work_in_sp', 'Trabalho em SP ainda não demonstrado no edital'))
    for k in ('salary_min', 'salary_max'):
        if data.get(k) is not None and not money_supported_near_role(
            proof.text, float(data[k]), data.get('position', '')
        ):
            failures.append((k, f'{k}: remuneração não comprovada junto ao cargo de engenharia no edital'))
    return failures


def check_assertions(proof, data):
    failures = assertion_failures(proof, data)
    if failures:
        raise ValueError(failures[0][1])
