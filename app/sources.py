"""Official sources are data, not code: they live in sources.yaml (or RADAR_SOURCES_FILE).

Each entry is validated before the worker uses it. A source can be switched off with
`enabled: false` without deleting its record, so nothing is lost when a body changes its site.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import evidence

MODES = ('catalog', 'notice_index', 'details', 'watch', 'gazette_search')
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    mode: str = 'catalog'
    enabled: bool = True
    uf: str = ''
    agency: str = ''


class SourceError(ValueError):
    pass


def parse(data):
    """Validate a parsed YAML document and return a tuple of Source objects."""
    if not isinstance(data, dict) or not isinstance(data.get('sources'), list):
        raise SourceError('sources.yaml precisa de uma lista "sources"')
    out, seen = [], set()
    for index, item in enumerate(data['sources'], start=1):
        where = f'fonte {index}'
        if not isinstance(item, dict):
            raise SourceError(f'{where}: deve ser um mapa')
        name, url = str(item.get('name', '')).strip(), str(item.get('url', '')).strip()
        mode = str(item.get('mode', 'catalog')).strip()
        if not name:
            raise SourceError(f'{where}: "name" é obrigatório')
        if name in seen:
            raise SourceError(f'{where}: nome repetido "{name}"')
        seen.add(name)
        if mode not in MODES:
            raise SourceError(f'{name}: modo inválido "{mode}" (use {", ".join(MODES)})')
        if mode == 'gazette_search':
            if not evidence.data_api_url(url):
                raise SourceError(f'{name}: gazette_search só aceita a API pública do Querido Diário')
        elif not evidence.official_url(url):
            raise SourceError(f'{name}: a URL precisa ser HTTPS de um domínio oficial')
        uf = str(item.get('uf', '')).strip().upper()
        if uf and len(uf) != 2:
            raise SourceError(f'{name}: "uf" precisa ter duas letras')
        out.append(
            Source(
                name=name,
                url=url,
                mode=mode,
                enabled=item.get('enabled', True) is not False,
                uf=uf,
                agency=str(item.get('agency', '')).strip(),
            )
        )
    return tuple(out)


def sources_file():
    return Path(os.getenv('RADAR_SOURCES_FILE', '') or ROOT / 'sources.yaml')


def load(path=None):
    """Read and validate the source list. Raises SourceError with a readable message."""
    target = Path(path) if path else sources_file()
    try:
        data = yaml.safe_load(target.read_text(encoding='utf-8'))
    except OSError as ex:
        raise SourceError(f'Não foi possível ler {target}: {ex}') from ex
    except yaml.YAMLError as ex:
        raise SourceError(f'YAML inválido em {target}: {ex}') from ex
    return parse(data)


def active(sources=None):
    return tuple(s for s in (sources if sources is not None else load()) if s.enabled)
