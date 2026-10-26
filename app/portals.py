"""Official portals where a municipality publishes its editais, keyed by IBGE code (file portais.yaml).

A gazette only announces a contest. When the municipality has a known portal, the card points to it, so the
validator can look for the edital there by itself. The gazette is never used as proof.
"""

import re
from functools import lru_cache
from pathlib import Path

import yaml

from . import evidence
from . import repository as repo

FILE = Path(__file__).resolve().parent.parent / 'portais.yaml'
GAZETTE_URL = re.compile(r'^https://data\.queridodiario\.ok\.org\.br/(\d{7})/')


@lru_cache(maxsize=1)
def load():
    try:
        data = yaml.safe_load(FILE.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {str(k): str(v).strip() for k, v in data.items() if evidence.official_url(str(v).strip())}


def for_territory(code):
    return load().get(str(code or ''))


def for_gazette_url(url):
    match = GAZETTE_URL.match(url or '')
    return for_territory(match.group(1)) if match else None


def attach_existing():
    """Cards found in a gazette before the portal was known: point them to the portal. Returns how many."""
    changed = 0
    for item in repo.query_opportunities(include_dismissed=False):
        portal = for_gazette_url(item.get('official_url'))
        if portal and not item.get('document_verified'):
            repo.update_opportunity(item['id'], {'official_url': portal})
            changed += 1
    return changed
