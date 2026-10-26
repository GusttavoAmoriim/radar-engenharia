"""FastAPI app: public read-only portal (optional) + single-admin area, with a hard gate for verified notices."""

import csv
import io
import logging
import re
from contextlib import asynccontextmanager
from html import escape as html_escape
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import (
    __version__,
    auth,
    clock,
    collectors,
    config,
    database,
    evidence,
    kv,
    notifications,
    polite,
    suggest,
    verification,
)
from . import repository as repo
from . import (
    sources as source_catalog,
)

BASE = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app):
    database.init_db()
    if not auth.password_configured():
        raise RuntimeError(
            f'Defina RADAR_PASSWORD com pelo menos {auth.MIN_PASSWORD_LENGTH} caracteres no .env (sem valor de exemplo)'
        )
    auth.bootstrap_password()
    collectors.deadline_alerts()
    yield


app = FastAPI(
    title='Radar Engenharia',
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(GZipMiddleware, minimum_size=800)

# Always reachable without a session.
LOG = logging.getLogger(__name__)

AUTH_FREE = {'/healthz', '/', '/favicon.ico', '/robots.txt', '/api/auth/login', '/api/auth/status'}
# Read-only endpoints opened to visitors when RADAR_PUBLIC=1. Everything else is admin-only (deny by default).
PUBLIC_READ = (
    re.compile(r'^/api/opportunities(/\d+)?$'),
    re.compile(r'^/api/(alerts|sources)$'),
    re.compile(r'^/api/export\.csv$'),
)
# Personal admin data never shown to visitors.
PRIVATE_FIELDS = ('notes', 'favorite', 'applied', 'dismissed', 'stage')
STATIC_DIR = (BASE / 'static').resolve()
STATIC_TYPES = {
    '.css': 'text/css; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.ico': 'image/x-icon',
    '.webmanifest': 'application/manifest+json',
}


def needs_admin(path, method):
    if path in AUTH_FREE or path.startswith('/static/'):
        return False
    if method in ('GET', 'HEAD') and config.public_mode():
        return not any(pattern.match(path) for pattern in PUBLIC_READ)
    return True


def is_admin(request):
    return bool(getattr(request.state, 'session', None))


def visible(items, request):
    """Admins see everything; visitors get the public view (no hidden items, no personal fields)."""
    if is_admin(request):
        return items
    return [{k: v for k, v in item.items() if k not in PRIVATE_FIELDS} for item in items if not item.get('dismissed')]


@app.middleware('http')
async def gate(request: Request, call_next):
    path = request.url.path
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Origem bloqueada'}, status_code=403)
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            return JSONResponse({'detail': 'Apenas application/json'}, status_code=415)
    session = auth.validate_session(request.cookies.get(auth.COOKIE))
    request.state.session = session
    admin_only = needs_admin(path, request.method)
    if admin_only and not session:
        return JSONResponse({'detail': 'Autenticação necessária'}, status_code=401)
    if (
        admin_only
        and request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
        and not auth.csrf_valid(session, request.headers.get('X-CSRF-Token', ''))
    ):
        return JSONResponse({'detail': 'CSRF inválido'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    # Static assets revalidate with ETag (always fresh after an update); everything else is never cached.
    response.headers['Cache-Control'] = 'no-cache' if path.startswith('/static/') else 'no-store'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    return response


@app.get('/robots.txt')
def robots():
    body = 'User-agent: *\nAllow: /\n' if config.public_mode() else 'User-agent: *\nDisallow: /\n'
    return Response(body, media_type='text/plain')


@app.get('/healthz')
def health():
    return {'service': 'ok', 'version': __version__, 'date': clock.today().isoformat()}


@app.get('/')
def index():
    name = html_escape(config.app_name(), quote=True)
    html = (
        (STATIC_DIR / 'index.html')
        .read_text(encoding='utf-8')
        .replace('__VERSION__', __version__)
        .replace('__APP_NAME__', name)
    )
    return HTMLResponse(html)


@app.get('/favicon.ico')
def classic_favicon():
    return FileResponse(BASE / 'static/favicon.ico')


@app.get('/static/{file_path:path}')
def static(file_path: str):
    target = (STATIC_DIR / file_path).resolve()
    media_type = STATIC_TYPES.get(target.suffix)
    if not media_type or not target.is_file() or not target.is_relative_to(STATIC_DIR) or target.name.startswith('.'):
        raise HTTPException(404)
    return FileResponse(target, media_type=media_type)


@app.get('/api/auth/status')
def status(request: Request):
    # The CSRF token is only echoed back to an authenticated same-origin session.
    authenticated = is_admin(request)
    return {
        'authenticated': authenticated,
        'public': config.public_mode(),
        'default_uf': config.default_uf(),
        'mfa_enabled': auth.mfa_enabled() if authenticated else None,
        'csrf': request.cookies.get('radar_csrf', '') if authenticated else None,
    }


def request_ip(request):
    peer = request.client.host if request.client else ''
    return auth.client_ip(peer, request.headers.get('x-forwarded-for', ''))


def session_cookie_args(max_age):
    return {'httponly': True, 'samesite': 'strict', 'secure': config.cookie_secure(), 'path': '/', 'max_age': max_age}


@app.post('/api/auth/login')
async def login(request: Request):
    data = await request.json()
    password = str(data.get('password', ''))
    code = str(data.get('code', '')).strip()
    remember = data.get('remember') is True
    ip = request_ip(request)
    agent = request.headers.get('user-agent', '')
    if not auth.can_attempt(ip):
        raise HTTPException(429, 'Muitas tentativas. Aguarde 15 minutos.')
    if not auth.password_ok(password):
        auth.failed(ip)
        raise HTTPException(401, 'Senha inválida')
    trusted = auth.device_trusted(request.cookies.get(auth.TRUSTED_COOKIE))
    if auth.mfa_enabled() and not trusted:
        if not code:
            return {'mfa_required': True}
        if not auth.mfa_check(code, True):
            auth.failed(ip)
            raise HTTPException(401, 'Código MFA inválido')
    auth.successful(ip)
    token, csrf = auth.new_session(ip, agent, remember)
    response = JSONResponse({'authenticated': True, 'mfa_enabled': auth.mfa_enabled(), 'csrf': csrf})
    max_age = auth.REMEMBER_DAYS * 86400 if remember else None
    response.set_cookie(auth.COOKIE, token, **session_cookie_args(max_age))
    # Readable by same-origin JS only; the CSRF token is not an authentication credential.
    response.set_cookie('radar_csrf', csrf, **{**session_cookie_args(max_age), 'httponly': False})
    if remember and auth.mfa_enabled() and not trusted:
        response.set_cookie(
            auth.TRUSTED_COOKIE, auth.trust_device(ip, agent), **session_cookie_args(auth.REMEMBER_DAYS * 86400)
        )
    return response


@app.post('/api/auth/logout')
def logout(request: Request):
    auth.logout(request.cookies.get(auth.COOKIE))
    response = JSONResponse({'ok': True})
    response.delete_cookie(auth.COOKIE, path='/')
    response.delete_cookie('radar_csrf', path='/')
    return response


@app.get('/api/auth/sessions')
def sessions(request: Request):
    return {
        'sessions': auth.list_sessions(request.state.session['id']),
        'trusted_devices': auth.trusted_device_count(),
        'events': auth.recent_events(),
    }


@app.post('/api/auth/sessions/revoke')
async def revoke_session(request: Request):
    data = await request.json()
    try:
        ok = auth.revoke_session(str(data.get('id', '')), request.state.session['id'], request_ip(request))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if not ok:
        raise HTTPException(404, 'Sessão não encontrada')
    return {'ok': True}


@app.post('/api/auth/sessions/revoke-others')
def revoke_others(request: Request):
    return {'revoked': auth.revoke_other_sessions(request.state.session['id'], request_ip(request))}


@app.post('/api/auth/trusted-devices/revoke')
def revoke_trusted(request: Request):
    return {'revoked': auth.revoke_trusted_devices(request_ip(request))}


@app.post('/api/auth/password')
async def change_password(request: Request):
    data = await request.json()
    try:
        auth.change_password(str(data.get('current', '')), str(data.get('new', '')), str(data.get('code', '')))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    ip = request_ip(request)
    auth.revoke_other_sessions(request.state.session['id'], ip)
    auth.revoke_trusted_devices(ip)
    auth.event(ip, 'password_changed')
    return {'ok': True}


@app.post('/api/auth/mfa/setup')
async def mfa_setup(request: Request):
    data = await request.json()
    if auth.mfa_enabled():
        raise HTTPException(409, 'MFA já ativado')
    if not auth.password_ok(str(data.get('password', ''))):
        raise HTTPException(403, 'Confirme sua senha')
    try:
        return auth.begin_mfa()
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post('/api/auth/mfa/confirm')
async def mfa_confirm(request: Request):
    data = await request.json()
    try:
        codes = auth.finish_mfa(data.get('code', ''))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {'active': True, 'recovery_codes': codes}


@app.post('/api/auth/mfa/disable')
async def mfa_disable(request: Request):
    data = await request.json()
    if not auth.disable_mfa(str(data.get('password', '')), str(data.get('code', ''))):
        raise HTTPException(403, 'Senha/código inválidos')
    return {'active': False}


@app.get('/api/opportunities')
def opportunities(request: Request):
    return {'items': visible(repo.query_opportunities(), request), 'as_of': clock.now()}


@app.get('/api/opportunities/{oid}')
def opportunity(oid: int, request: Request):
    item = repo.fetch_one(oid)
    shown = visible([item], request) if item else []
    if not shown:
        raise HTTPException(404)
    return shown[0]


@app.post('/api/opportunities', status_code=201)
async def add_opportunity(request: Request):
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(422)
    if (
        not data.get('title')
        or not evidence.official_url(data.get('official_url', ''))
        or not evidence.official_url(data.get('notice_url', ''))
    ):
        raise HTTPException(422, 'Informe título, página oficial e link HTTPS de edital em domínio oficial')
    # Never allow manual flags to circumvent technical verification.
    data['confidence'] = 'discovery'
    data['reviewed'] = 0
    data['status_override'] = None
    data['source'] = 'Cadastro manual (verificação pendente)'
    try:
        oid, _ = repo.upsert(data, enrich_only=False)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    return repo.fetch_one(oid)


@app.patch('/api/opportunities/{oid}')
async def edit_opportunity(oid: int, request: Request):
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(422)
    for k in ('official_url', 'notice_url', 'apply_url'):
        if k in data and data[k] and not evidence.official_url(data[k]):
            raise HTTPException(422, f'{k} não é endereço oficial permitido')
    try:
        ok = repo.update_opportunity(oid, data)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    if not ok:
        raise HTTPException(404)
    return repo.fetch_one(oid)


@app.post('/api/opportunities/{oid}/verify')
def verify(oid: int):
    try:
        item, warnings = verification.verify(oid)
    except LookupError as e:
        raise HTTPException(404) from e
    except Exception as e:
        raise HTTPException(422, 'Conferência documental reprovada: ' + str(e)) from e
    return {**item, 'warnings': warnings}


@app.post('/api/opportunities/{oid}/suggest')
def suggest_fields(oid: int):
    """Read the official notice and propose values. Only suggestions: nothing is saved."""
    item = repo.fetch_one(oid)
    if not item:
        raise HTTPException(404)
    url = item.get('notice_url') or item.get('official_url') or ''
    if not evidence.official_url(url):
        raise HTTPException(422, 'Informe um link oficial (HTTPS) do edital primeiro')
    try:
        resolved, raw, mime = evidence.fetch_official(url)
        text, _kind = evidence.extract(resolved, raw, mime)
    except ValueError as e:  # our own checks: messages are written for people
        raise HTTPException(422, 'Não foi possível ler o edital: ' + str(e)) from e
    except Exception as e:  # network or parsing failures: keep details in the log only
        LOG.warning('Leitura de edital falhou (%s): %s', url, e)
        raise HTTPException(422, 'Não foi possível acessar o edital agora. Tente novamente mais tarde.') from e
    found = suggest.suggest(text, item.get('position') or '')
    return {
        'suggestions': {field: {'value': value, 'snippet': snippet} for field, (value, snippet) in found.items()},
        'note': 'Sugestões extraídas do texto do documento. Confira cada uma antes de salvar.',
    }


@app.get('/api/candidates')
def candidates():
    return {'items': repo.candidates()}


@app.get('/api/alerts')
def alerts():
    return {'items': repo.get_alerts()}


@app.get('/api/sources')
def sources():
    host_state = polite.snapshot()
    return {
        'health': repo.source_health(),
        'cron': 'A cada 3 horas (00, 03, 06, 09, 12, 15, 18, 21 BRT)',
        'running': collectors.LOCK.locked(),
        'configured': len(collectors.SOURCES),
        'catalog': [
            {
                'name': s.name,
                'url': s.url,
                'mode': s.mode,
                'agency': s.agency,
                'uf': s.uf,
                'enabled': s.enabled,
                'pacing': host_state.get(polite.hostname(s.url), {}),
            }
            for s in all_sources()
        ],
        'notifications_configured': config.notifications_configured(),
    }


def all_sources():
    """Every source in sources.yaml, enabled or not. Falls back to the active list if the file is broken."""
    try:
        return source_catalog.load()
    except source_catalog.SourceError:
        return collectors.SOURCES


@app.post('/api/notifications/test')
def notifications_test():
    try:
        result = notifications.send_test()
    except Exception as e:  # network or SMTP errors: do not expose internals to the browser
        LOG.warning('Teste de aviso falhou: %s', e)
        raise HTTPException(
            422, 'Não foi possível enviar o teste. Confira as variáveis SMTP_* ou TELEGRAM_* no .env.'
        ) from e
    if not result['channels']:
        raise HTTPException(422, 'Nenhum canal configurado. Defina SMTP_* ou TELEGRAM_* no .env.')
    return result


@app.post('/api/scan', status_code=202)
def scan_now(background_tasks: BackgroundTasks):
    if collectors.LOCK.locked() or (kv.get('scan_lease_until') or '') > clock.now():
        raise HTTPException(409, 'Coleta já em execução')
    background_tasks.add_task(collectors.run_all)
    return {'queued': True}


@app.get('/api/export.csv')
def export_csv(request: Request):
    rows = visible(repo.query_opportunities(), request)
    fields = [
        'title',
        'agency',
        'position',
        'type',
        'status',
        'salary_min',
        'salary_max',
        'salary_verified',
        'registration_start',
        'registration_end',
        'exam_date',
        'exam_cities',
        'work_cities',
        'official_url',
        'notice_url',
        'apply_url',
        'document_verified',
        'favorite',
        'applied',
        'stage',
        'notes',
    ]
    if not is_admin(request):
        fields = [f for f in fields if f not in PRIVATE_FIELDS]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        '\ufeff' + out.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="concursos-engenharia.csv"'},
    )
