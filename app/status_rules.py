"""How an opportunity's situation is derived. Only documented facts can make it open/upcoming."""

from datetime import date

from . import clock


def compute_status(item, reference=None):
    reference = reference or clock.today()
    if not item.get('document_verified'):
        return 'verify'
    if item.get('status_override') in ('announced', 'suspended', 'cancelled'):
        return item['status_override']
    if item.get('status_override') == 'open' and item.get('confidence') == 'official' and item.get('reviewed'):
        end = item.get('registration_end')
        return 'closed' if end and date.fromisoformat(end) < reference else 'open'
    start, end = item.get('registration_start'), item.get('registration_end')
    # Unverified scraped hints may not pretend to be officially open.
    if item.get('confidence') != 'official' or not item.get('reviewed'):
        return 'verify'
    if end and date.fromisoformat(end) < reference:
        return 'closed'
    if start and date.fromisoformat(start) > reference:
        return 'upcoming'
    if start and end and date.fromisoformat(start) <= reference <= date.fromisoformat(end):
        return 'open'
    return 'verify'


def present(item, reference=None):
    reference = reference or clock.today()
    item['status'] = compute_status(item, reference)
    item['days_left'] = (
        (date.fromisoformat(item['registration_end']) - reference).days
        if item.get('registration_end') and item['status'] in ('open', 'upcoming')
        else None
    )
    item['eligible_sp'] = bool(item.get('exam_in_sp') or item.get('work_in_sp'))
    item['salary_highlight'] = (
        bool(item.get('salary_verified')) and max(item.get('salary_max') or 0, item.get('salary_min') or 0) >= 7000
    )
    item['priority'] = (
        3 if item['status'] == 'open' else 2 if item['status'] == 'upcoming' else 1 if item['status'] == 'verify' else 0
    )
    return item
