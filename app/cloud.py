"""Uma coleta completa para rodar no GitHub Actions (sem servidor): coleta, valida, gera a página e avisa.

python -m app.cloud            # coleta + valida + gera site/index.html + avisa no Telegram
python -m app.cloud testar-telegram
"""

import logging
import sys
from pathlib import Path

from . import collectors, database, gazettes, kv, staticsite, telegram, verification
from . import repository as repo

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger('radar.cloud')
WORTH = ('new', 'new-gazette', 'site_changed')


def tidy():
    repo.prune_candidates()
    gazettes.dismiss_stale_discoveries()
    repo.scrub_personal_data()


def notify():
    """Telegram: one message with what is new since the last run. The first run only sends a summary."""
    if not telegram.configured():
        LOG.info('Telegram não configurado: avisos só no painel')
        return 0
    alerts = repo.get_alerts(200)
    last = int(kv.get('telegram_last_alert') or 0)
    top = max((a['id'] for a in alerts), default=0)
    if not kv.get('telegram_started'):
        kv.put('telegram_started', '1')
        kv.put('telegram_last_alert', str(top))
        open_now = [i for i in repo.query_opportunities(include_dismissed=False) if i['status'] != 'closed']
        telegram.send(f'Radar de engenharia ativo. {len(open_now)} concursos na lista. Você será avisado dos novos.')
        return 0
    lines = []
    for alert in sorted((a for a in alerts if a['id'] > last), key=lambda a: a['id']):
        if alert['kind'] not in WORTH:
            continue
        item = repo.fetch_one(alert['opportunity_id']) if alert.get('opportunity_id') else None
        if item and (item.get('dismissed') or item['status'] == 'closed'):
            continue  # found, then discarded (old contest, ranking list...): not worth a message
        lines.append('• ' + alert['text'])
    kv.put('telegram_last_alert', str(top))
    if lines:
        telegram.send('Radar de engenharia — novidades:\n\n' + '\n\n'.join(lines[:10]))
    return len(lines)


def main(argv):
    if argv[:1] == ['testar-telegram']:
        telegram.send('Teste do Radar de engenharia: o aviso chegou.')
        print('Mensagem enviada.')
        return 0
    database.init_db()
    tidy()
    result = collectors.run_all()
    LOG.info('Coleta: %s', result.get('state'))
    verification.auto_verify(limit=30)
    verification.hide_old_autofilled()
    out = Path('site')
    out.mkdir(exist_ok=True)
    (out / 'index.html').write_text(staticsite.build(), encoding='utf-8')
    try:
        LOG.info('Avisos enviados: %s', notify())
    except RuntimeError as err:
        LOG.warning('Telegram: %s', err)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
