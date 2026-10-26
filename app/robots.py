"""robots.txt for official sites. Checked before real traffic, cached per host for a day.

Rules: a site without robots.txt (404/410) is allowed; a robots.txt that disallows the path for
our agent blocks the page; if robots.txt cannot be read (5xx, timeout, 401/403) we stay conservative
and skip the host for this run instead of guessing.
"""

import threading
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

AGENT = 'RadarEngenharia'
TTL_SECONDS = 24 * 3600
# A robots.txt that could not be read is retried soon: one hiccup must not silence a host for a day.
FAILURE_TTL_SECONDS = 600
_CACHE: dict[str, tuple[float, robotparser.RobotFileParser | None]] = {}
_LOCK = threading.Lock()


class RobotsBlocked(ValueError):
    pass


def _fetch(host, session):
    parser = robotparser.RobotFileParser()
    url = f'https://{host}/robots.txt'
    response = None
    for attempt in range(2):
        try:
            response = (session or requests).get(
                url, timeout=(8, 15), allow_redirects=False, headers={'User-Agent': AGENT}
            )
        except requests.RequestException:
            response = None  # unreachable now: caller treats as blocked for this run
        if response is not None and response.status_code < 500:
            break
        if attempt == 0:
            time.sleep(2)
    if response is None:
        return None
    if response.status_code in (404, 410):
        parser.parse([])  # nothing disallowed
        return parser
    if response.status_code != 200:
        return None
    parser.parse(response.text.splitlines())
    return parser


def parser_for(host, session=None, now=None):
    now = time.time() if now is None else now
    with _LOCK:
        cached = _CACHE.get(host)
        if cached and cached[0] > now:
            return cached[1]
    parser = _fetch(host, session)
    with _LOCK:
        _CACHE[host] = (now + (TTL_SECONDS if parser else FAILURE_TTL_SECONDS), parser)
    return parser


def check(url, session=None, now=None):
    """Raise RobotsBlocked unless robots.txt allows fetching this URL."""
    host = urlparse(url).hostname or ''
    parser = parser_for(host, session, now)
    if parser is None:
        raise RobotsBlocked(f'robots.txt de {host} indisponível; página pulada nesta varredura')
    if not parser.can_fetch(AGENT, url):
        raise RobotsBlocked(f'robots.txt de {host} proíbe esta página para o radar')


def clear():
    with _LOCK:
        _CACHE.clear()
