"""Avisos por Telegram. Os erros nunca incluem o token."""

import os

import requests


def settings():
    return os.getenv('TELEGRAM_BOT_TOKEN', '').strip(), os.getenv('TELEGRAM_CHAT_ID', '').strip()


def configured():
    return all(settings())


def send(text):
    token, chat = settings()
    if not (token and chat):
        raise RuntimeError('Telegram não configurado (TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID)')
    try:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat, 'text': text[:4000], 'disable_web_page_preview': True},
            timeout=30,
        )
    except requests.RequestException as err:
        raise RuntimeError(f'falha de rede ao falar com o Telegram ({type(err).__name__})') from None
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not body.get('ok'):
        raise RuntimeError(f'Telegram recusou ({response.status_code}): {body.get("description", "sem detalhe")}')
