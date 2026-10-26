"""Optional outbound email and Telegram digest. Never requires paid services.

dispatch() sends pending alerts and marks them as notified only when a channel accepted them.
send_test() sends one fixed message through the same channels and never touches alerts.
"""

import smtplib
from email.message import EmailMessage

import requests

from . import config, database


def _email(subject, body):
    mail = config.smtp()
    host, sender, to = mail['host'], mail['sender'], mail['to']
    if not (host and sender and to):
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to
    msg.set_content(body)
    port = mail['port']
    with smtplib.SMTP_SSL(host, port, timeout=20) if port == 465 else smtplib.SMTP(host, port, timeout=20) as smtp:
        if port != 465 and mail['starttls']:
            smtp.starttls()
        if mail['username']:
            smtp.login(mail['username'], mail['password'])
        smtp.send_message(msg)
    return True


def _telegram(text):
    tg = config.telegram()
    token, chat = tg['token'], tg['chat_id']
    if not (token and chat):
        return False
    # Telegram API text limit 4096; transmit chunks preserving boundaries.
    for i in range(0, len(text), 3800):
        resp = requests.post(
            'https://api.telegram.org/bot' + token + '/sendMessage',
            json={'chat_id': chat, 'text': text[i : i + 3800], 'disable_web_page_preview': True},
            timeout=20,
        )
        resp.raise_for_status()
    return True


def _deliver(title, lines, subject):
    """Send through every configured channel. Returns the channels that accepted the message."""
    sent_to = []
    body = f'{title}\n\n' + '\n\n'.join(lines)
    if _email(subject, body):
        sent_to.append('email')
    if _telegram(f'🔔 {title}\n\n' + '\n\n'.join(lines)):
        sent_to.append('telegram')
    return sent_to


def dispatch():
    with database.connection() as db:
        pending = [dict(r) for r in db.execute('SELECT * FROM alerts WHERE notified=0 ORDER BY id LIMIT 100')]
    if not pending:
        return {'sent': 0, 'reason': 'no pending events'}
    lines = [f'• {a["text"]}' for a in pending]
    sent_to = _deliver(
        f'{config.app_name()} — alertas pendentes',
        lines,
        f'[{config.app_name()}] {len(pending)} aviso(s) de concurso',
    )
    if sent_to:
        with database.DB_LOCK, database.connection() as db:
            db.executemany('UPDATE alerts SET notified=1 WHERE id=?', [(a['id'],) for a in pending])
            db.commit()
    return {'sent': len(pending) if sent_to else 0, 'channels': sent_to}


def send_test():
    """One fixed message through the configured channels. Does not change any alert."""
    sent_to = _deliver(
        f'{config.app_name()} — teste de aviso',
        ['Se você recebeu esta mensagem, o canal de avisos está funcionando.'],
        f'[{config.app_name()}] teste de aviso',
    )
    return {'channels': sent_to, 'configured': config.notifications_configured()}
