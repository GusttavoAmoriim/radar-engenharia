"""Uma coleta completa para rodar no GitHub Actions (sem servidor): coleta, valida, gera a página e avisa.

python -m app.cloud            # coleta + valida + gera site/index.html + avisa no Telegram
python -m app.cloud testar-telegram
"""

import logging
import sys
from pathlib import Path

from . import collectors, database, gazettes, kv, portals, staticsite, telegram, verification
from . import repository as repo

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger('radar.cloud')


def tidy():
    repo.prune_candidates()
    gazettes.dismiss_stale_discoveries()
    repo.scrub_personal_data()
    portals.attach_existing()


def notify():
    """Telegram: the alerts themselves go out through notifications.dispatch (run by the collector).

    Here, only a one-time message on the first run, so you know the channel works.
    """
    if not telegram.configured() or kv.get('telegram_started'):
        return 0
    kv.put('telegram_started', '1')
    count = len([i for i in repo.query_opportunities(include_dismissed=False) if i['status'] != 'closed'])
    word = 'concurso' if count == 1 else 'concursos'
    telegram.send(f'Radar de engenharia ativo: {count} {word} na lista. Você será avisado dos novos.')
    return 1


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
