"""Admin account: hashed password, optional TOTP MFA, sessions per device, trusted devices,
login throttling and a security event log."""

import base64
import hashlib
import hmac
import io
import ipaddress
import secrets
import time
import uuid
from datetime import datetime, timedelta

from cryptography.fernet import Fernet

from . import clock, config, database, kv

COOKIE = 'radar_session'
TRUSTED_COOKIE = 'radar_trusted_device'
REMEMBER_DAYS = 7
SESSION_HOURS = 12
MIN_PASSWORD_LENGTH = 7  # accepted for RADAR_PASSWORD (bootstrap); the panel asks for at least 12
NEW_PASSWORD_LENGTH = 12
LAST_SEEN_EVERY = 300  # seconds between last_seen updates of a session


# ---------- passwords ----------


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f'scrypt$16384$8$1${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}'


def verify_password(password, stored):
    try:
        _, n, r, p, salt, key = stored.split('$')
        expected = base64.b64decode(key)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def env_password_valid():
    value = config.admin_password()
    return len(value) >= MIN_PASSWORD_LENGTH and 'SUBSTITUA' not in value.upper()


def bootstrap_password():
    """Adopt RADAR_PASSWORD as the admin password the first time, and again whenever it changes
    in .env (an intentional reset). A password changed in the panel is kept until then."""
    env = config.admin_password()
    if not env_password_valid():
        return bool(kv.get('admin_password_hash'))
    if not kv.get('admin_password_hash') or not verify_password(env, kv.get('admin_password_env')):
        had_password = bool(kv.get('admin_password_hash'))
        kv.put('admin_password_hash', hash_password(env))
        kv.put('admin_password_env', hash_password(env))
        if had_password:
            revoke_all_sessions()
            event('local', 'password_reset_env')
    return True


def password_configured():
    return env_password_valid() or bool(kv.get('admin_password_hash'))


def password_ok(password):
    if not bootstrap_password():
        return False
    return verify_password(str(password), kv.get('admin_password_hash'))


def change_password(current, new, code=''):
    if not password_ok(current):
        raise ValueError('Senha atual incorreta')
    if mfa_enabled() and not mfa_check(code, consume_recovery=True):
        raise ValueError('Código do autenticador inválido')
    if len(new) < NEW_PASSWORD_LENGTH:
        raise ValueError(f'A nova senha precisa ter pelo menos {NEW_PASSWORD_LENGTH} caracteres')
    if new == current:
        raise ValueError('A nova senha precisa ser diferente da atual')
    kv.put('admin_password_hash', hash_password(new))


# ---------- MFA (TOTP) ----------


def fernet():
    raw = config.mfa_encryption_key()
    if not raw:
        raise ValueError('Configure RADAR_MFA_ENCRYPTION_KEY antes de ativar MFA')
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as ex:
        raise ValueError('Chave Fernet inválida') from ex


def mfa_enabled():
    return bool(kv.get('mfa_secret'))


def totp(secret, at=None):
    t = int((at if at is not None else time.time()) // 30)
    key = base64.b32decode(secret, casefold=True)
    raw = hmac.new(key, t.to_bytes(8, 'big'), hashlib.sha1).digest()
    index = raw[-1] & 15
    return str((int.from_bytes(raw[index : index + 4], 'big') & 0x7FFFFFFF) % 1_000_000).zfill(6)


def check_totp(secret, code):
    if not isinstance(code, str) or not code.isdigit() or len(code) != 6:
        return False
    t = time.time()
    return any(hmac.compare_digest(totp(secret, t + 30 * n), code) for n in (-1, 0, 1))


def mfa_check(code, consume_recovery=False):
    enc = kv.get('mfa_secret')
    if not enc:
        return True
    secret = fernet().decrypt(enc.encode()).decode()
    if check_totp(secret, str(code)):
        return True
    if not consume_recovery:
        return False
    key = digest(str(code).strip().upper())
    used = False
    with database.DB_LOCK, database.connection() as db:
        val = db.execute("SELECT value FROM app_settings WHERE key='mfa_recovery'").fetchone()
        saved = val[0].split(',') if val else []
        if key in saved:
            saved.remove(key)
            db.execute("UPDATE app_settings SET value=? WHERE key='mfa_recovery'", (','.join(saved),))
            used = True
    if used:  # outside the transaction: event() opens its own connection
        event('local', 'mfa_recovery_used')
    return used


def begin_mfa():
    secret = base64.b32encode(secrets.token_bytes(20)).decode().strip('=')
    kv.put('mfa_pending', fernet().encrypt(secret.encode()).decode())
    uri = f'otpauth://totp/Radar%20Public%20Sector:admin?secret={secret}&issuer=Radar%20Public%20Sector&algorithm=SHA1&digits=6&period=30'
    import qrcode  # imported lazily: only needed while enabling MFA

    img = qrcode.make(uri)
    file = io.BytesIO()
    img.save(file, format='PNG')
    return {'secret': secret, 'qr': 'data:image/png;base64,' + base64.b64encode(file.getvalue()).decode()}


def finish_mfa(code):
    enc = kv.get('mfa_pending')
    if not enc:
        raise ValueError('Configuração MFA não iniciada')
    secret = fernet().decrypt(enc.encode()).decode()
    if not check_totp(secret, str(code)):
        raise ValueError('Código inválido ou expirado')
    codes = ['-'.join((secrets.token_hex(4).upper(), secrets.token_hex(4).upper())) for _ in range(8)]
    kv.put('mfa_recovery', ','.join(digest(c) for c in codes))
    kv.put('mfa_secret', enc)
    kv.delete('mfa_pending')
    revoke_trusted_devices()
    event('local', 'mfa_enabled')
    return codes


def disable_mfa(password, code):
    if not password_ok(password) or not mfa_check(str(code), True):
        return False
    kv.delete('mfa_secret')
    kv.delete('mfa_pending')
    kv.delete('mfa_recovery')
    revoke_trusted_devices()
    event('local', 'mfa_disabled')
    return True


# ---------- client IP behind reverse proxies ----------


def _trusted(ip, networks):
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for item in networks:
        try:
            if address in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(peer, forwarded_for=''):
    """Real client IP: walk X-Forwarded-For right-to-left skipping trusted proxies only."""
    networks = config.trusted_proxies()
    if not peer or not _trusted(peer, networks):
        return peer or 'unknown'
    hops = [h.strip() for h in (forwarded_for or '').split(',') if h.strip()]
    for hop in reversed(hops):
        if not _trusted(hop, networks):
            return hop
    return peer


# ---------- login throttling ----------


def can_attempt(ip):
    with database.connection() as db:
        r = db.execute('SELECT * FROM login_failures WHERE ip=?', (ip,)).fetchone()
    return not (r and r['blocked_until'] and r['blocked_until'] > clock.now())


def failed(ip):
    with database.DB_LOCK, database.connection() as db:
        row = db.execute('SELECT * FROM login_failures WHERE ip=?', (ip,)).fetchone()
        attempts = (row['attempts'] if row else 0) + 1
        if (
            row
            and (datetime.fromisoformat(clock.now()) - datetime.fromisoformat(row['updated_at'])).total_seconds() > 900
        ):
            attempts = 1
        blocked = (
            (datetime.now(clock.TZ) + timedelta(minutes=15)).isoformat(timespec='seconds') if attempts >= 5 else None
        )
        db.execute(
            """INSERT INTO login_failures(ip,attempts,blocked_until,updated_at) VALUES(?,?,?,?)
          ON CONFLICT(ip) DO UPDATE SET attempts=excluded.attempts,blocked_until=excluded.blocked_until,updated_at=excluded.updated_at""",
            (ip, attempts, blocked, clock.now()),
        )
    event(ip, 'ip_blocked' if blocked else 'login_failed')


def successful(ip):
    with database.DB_LOCK, database.connection() as db:
        db.execute('DELETE FROM login_failures WHERE ip=?', (ip,))
    event(ip, 'login_ok')


# ---------- sessions (one per device) ----------


def _expiry(**delta):
    return (datetime.now(clock.TZ) + timedelta(**delta)).isoformat(timespec='seconds')


def new_session(ip='', user_agent='', remember=False):
    token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
    stamp = clock.now()
    expires = _expiry(days=REMEMBER_DAYS) if remember else _expiry(hours=SESSION_HOURS)
    with database.DB_LOCK, database.connection() as db:
        db.execute(
            'INSERT INTO admin_sessions(id,token_hash,csrf_hash,ip,user_agent,created_at,last_seen_at,expires_at) VALUES (?,?,?,?,?,?,?,?)',
            (str(uuid.uuid4()), digest(token), digest(csrf), ip, user_agent[:300], stamp, stamp, expires),
        )
        db.execute('DELETE FROM admin_sessions WHERE expires_at<? OR revoked_at IS NOT NULL', (clock.now(),))
    return token, csrf


def validate_session(token):
    if not token:
        return None
    with database.connection() as db:
        row = db.execute('SELECT * FROM admin_sessions WHERE token_hash=?', (digest(token),)).fetchone()
        if not row or row['revoked_at'] or row['expires_at'] <= clock.now():
            return None
        last = datetime.fromisoformat(row['last_seen_at'])
        if (datetime.now(clock.TZ) - last).total_seconds() > LAST_SEEN_EVERY:
            db.execute('UPDATE admin_sessions SET last_seen_at=? WHERE id=?', (clock.now(), row['id']))
    return row


def logout(token):
    """Ends this session only; a trusted device stays trusted until revoked or expired."""
    if token:
        with database.DB_LOCK, database.connection() as db:
            db.execute('UPDATE admin_sessions SET revoked_at=? WHERE token_hash=?', (clock.now(), digest(token)))


def csrf_valid(session, csrf):
    return bool(session and csrf and hmac.compare_digest(session['csrf_hash'], digest(csrf)))


def list_sessions(current_id):
    with database.connection() as db:
        rows = db.execute(
            'SELECT id,ip,user_agent,created_at,last_seen_at,expires_at FROM admin_sessions'
            ' WHERE revoked_at IS NULL AND expires_at>? ORDER BY last_seen_at DESC',
            (clock.now(),),
        ).fetchall()
    return [{**dict(r), 'current': r['id'] == current_id} for r in rows]


def revoke_session(session_id, current_id, ip=''):
    if session_id == current_id:
        raise ValueError('Use “Sair” para encerrar a sessão atual')
    with database.DB_LOCK, database.connection() as db:
        changed = db.execute(
            'UPDATE admin_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL', (clock.now(), session_id)
        ).rowcount
    if changed:
        event(ip, 'session_revoked')
    return bool(changed)


def revoke_other_sessions(current_id, ip=''):
    with database.DB_LOCK, database.connection() as db:
        changed = db.execute(
            'UPDATE admin_sessions SET revoked_at=? WHERE id<>? AND revoked_at IS NULL', (clock.now(), current_id)
        ).rowcount
    event(ip, 'other_sessions_revoked', str(changed))
    return changed


def revoke_all_sessions():
    with database.DB_LOCK, database.connection() as db:
        db.execute('UPDATE admin_sessions SET revoked_at=? WHERE revoked_at IS NULL', (clock.now(),))


# ---------- trusted devices (skip MFA for 7 days) ----------


def trust_device(ip='', user_agent=''):
    token = secrets.token_urlsafe(40)
    with database.DB_LOCK, database.connection() as db:
        db.execute(
            'INSERT INTO trusted_devices(id,token_hash,ip,user_agent,created_at,expires_at) VALUES (?,?,?,?,?,?)',
            (str(uuid.uuid4()), digest(token), ip, user_agent[:300], clock.now(), _expiry(days=REMEMBER_DAYS)),
        )
    return token


def device_trusted(token):
    if not token:
        return False
    with database.connection() as db:
        row = db.execute(
            'SELECT expires_at,revoked_at FROM trusted_devices WHERE token_hash=?', (digest(token),)
        ).fetchone()
    return bool(row and not row['revoked_at'] and row['expires_at'] > clock.now())


def trusted_device_count():
    with database.connection() as db:
        return db.execute(
            'SELECT COUNT(*) FROM trusted_devices WHERE revoked_at IS NULL AND expires_at>?', (clock.now(),)
        ).fetchone()[0]


def revoke_trusted_devices(ip='local'):
    with database.DB_LOCK, database.connection() as db:
        changed = db.execute(
            'UPDATE trusted_devices SET revoked_at=? WHERE revoked_at IS NULL', (clock.now(),)
        ).rowcount
    if changed:
        event(ip, 'trusted_devices_revoked', str(changed))
    return changed


# ---------- security events ----------


def event(ip, kind, detail=''):
    with database.DB_LOCK, database.connection() as db:
        db.execute(
            'INSERT INTO security_events(at,ip,type,detail) VALUES (?,?,?,?)', (clock.now(), ip or '', kind, detail)
        )
        db.execute(
            'DELETE FROM security_events WHERE id NOT IN (SELECT id FROM security_events ORDER BY id DESC LIMIT 500)'
        )


def recent_events(limit=30):
    with database.connection() as db:
        rows = db.execute('SELECT at,ip,type FROM security_events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]
