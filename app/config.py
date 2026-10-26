"""All runtime configuration, read from environment variables (see .env.example).

Values are read on every call so tests and `docker compose up` restarts pick up changes.
"""

import os
import re


def _int(name, default, low=None, high=None):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def _float(name, default, low=None, high=None):
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def db_path():
    return os.getenv('RADAR_DB', '/data/radar.sqlite3')


def admin_password():
    return os.getenv('RADAR_PASSWORD', '')


def public_mode():
    """RADAR_PUBLIC=1 (default): anyone can browse the list; 0: everything requires the admin login."""
    return os.getenv('RADAR_PUBLIC', '1') != '0'


def app_name():
    """Name shown in the interface, page titles and notifications (RADAR_APP_NAME)."""
    return os.getenv('RADAR_APP_NAME', '').strip()[:60] or 'Radar Engenharia'


def default_uf():
    """Two-letter state (UF) preselected in the public list; empty = all of Brazil (RADAR_DEFAULT_UF)."""
    value = os.getenv('RADAR_DEFAULT_UF', '').strip().upper()
    return value if re.fullmatch(r'[A-Z]{2}', value) else ''


def trusted_proxies():
    """Comma-separated IPs/CIDRs of reverse proxies whose X-Forwarded-For is trusted (e.g. 172.16.0.0/12)."""
    return [item.strip() for item in os.getenv('RADAR_TRUSTED_PROXIES', '').split(',') if item.strip()]


def cookie_secure():
    return os.getenv('RADAR_COOKIE_SECURE', '1') == '1'


def mfa_encryption_key():
    return os.getenv('RADAR_MFA_ENCRYPTION_KEY', '')


def retry_seconds():
    return _int('RADAR_RETRY_SECONDS', 900, low=60)


def detail_limit():
    return _int('RADAR_DETAIL_LIMIT', 50, low=1)


def source_workers():
    return _int('RADAR_SOURCE_WORKERS', 3, low=1, high=5)


def domain_interval_seconds():
    return _float('RADAR_DOMAIN_INTERVAL_SECONDS', 8.0, low=3.0, high=60.0)


def smtp():
    return {
        'host': os.getenv('SMTP_HOST', ''),
        'port': _int('SMTP_PORT', 587),
        'starttls': os.getenv('SMTP_STARTTLS', '1') == '1',
        'username': os.getenv('SMTP_USERNAME', ''),
        'password': os.getenv('SMTP_PASSWORD', ''),
        'sender': os.getenv('ALERT_EMAIL_FROM', ''),
        'to': os.getenv('ALERT_EMAIL_TO', ''),
    }


def telegram():
    return {'token': os.getenv('TELEGRAM_BOT_TOKEN', ''), 'chat_id': os.getenv('TELEGRAM_CHAT_ID', '')}


def notifications_configured():
    mail, tg = smtp(), telegram()
    return bool((tg['token'] and tg['chat_id']) or (mail['host'] and mail['to']))
