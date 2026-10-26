"""One independent Docker worker, retries failed collection on next tick."""

import logging
import time
from datetime import datetime

from . import clock, collectors, config, database, gazettes, kv, verification
from . import repository as repo

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger('radar.worker')


def slot(instant):
    return instant.date().isoformat() + ':' + str(instant.hour // 3)


def tick():
    stamp = datetime.now(clock.TZ)
    current = slot(stamp)
    if kv.get('last_complete_slot') == current:
        return 'already'
    # One immediate slot attempt + at most one retry; protects the official
    # websites when a JS-only/blocked adapter repeatedly returns partial.
    retry_state = kv.get('slot_attempts')
    old_slot, _, old_count = retry_state.partition('|')
    attempts = int(old_count) if old_slot == current and old_count.isdigit() else 0
    if attempts >= 2:
        return 'cooldown'
    kv.put('slot_attempts', current + '|' + str(attempts + 1))
    result = collectors.run_all()
    if result.get('state') == 'ok':
        kv.put('last_complete_slot', current)
        return 'complete'
    return result.get('state', 'failed')


def main():
    database.init_db()
    repo.close_interrupted_runs()
    repo.prune_candidates()
    stale = gazettes.dismiss_stale_discoveries()
    if stale:
        LOG.info('%s cartões antigos de diários ocultados (não eram abertura)', stale)
    if repo.scrub_personal_data():
        LOG.info('Dados pessoais de diários antigos removidos')
    LOG.info('Worker started: official only, every 3h America/Sao_Paulo')
    try:
        validated, failed = verification.auto_verify()
        LOG.info('Validação automática: %s validados, %s pendentes', validated, failed)
        old = verification.hide_old_autofilled()
        if old:
            LOG.info('%s editais antigos ocultados (inscrições já encerradas)', old)
    except Exception:
        LOG.exception('Validação automática falhou')
    while True:
        state = 'failed'
        try:
            state = tick()
            LOG.info('Collection: %s', state)
        except Exception:
            LOG.exception('Unexpected collection failure')
        if state in ('already', 'complete', 'cooldown'):
            current = datetime.now(clock.TZ)
            # Sleep until the next 3-hour boundary, checking again immediately.
            next_hour = ((current.hour // 3) + 1) * 3
            from datetime import timedelta

            next_run = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=next_hour)
            delay = max(60, (next_run - current).total_seconds())
        else:
            delay = config.retry_seconds()
        time.sleep(delay)


if __name__ == '__main__':
    main()
