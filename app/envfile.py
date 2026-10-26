"""Reads a .env file (KEY=VALUE lines) so the radar can run without Docker Compose."""

from pathlib import Path


def parse(text):
    """KEY=VALUE per line. Blank lines and # comments are ignored; matching quotes are removed."""
    values = {}
    for raw in str(text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load(path):
    """Values of the file, or {} when it does not exist. utf-8-sig because Windows Notepad adds a BOM."""
    file = Path(path)
    return parse(file.read_text(encoding='utf-8-sig')) if file.is_file() else {}
