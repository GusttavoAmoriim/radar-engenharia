"""Basic structural validation; not a live website test."""

import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from app import collectors, evidence

for name in [
    'app/main.py',
    'app/auth.py',
    'app/evidence.py',
    'app/repository.py',
    'app/database.py',
    'app/config.py',
    'app/collectors.py',
    'app/worker.py',
    'static/index.html',
    'static/css/app.css',
    'static/js/main.js',
    'Dockerfile',
    'compose.yaml',
    '.env.example',
    'sources.yaml',
    'README.md',
]:
    assert (root / name).is_file(), f'Arquivo ausente: {name}'
assert len(collectors.SOURCES) >= 7
assert all(
    evidence.data_api_url(s.url) if s.mode == 'gazette_search' else evidence.official_url(s.url)
    for s in collectors.SOURCES
)
assert all('google.com' not in s.url and 'pciconcursos.com' not in s.url for s in collectors.SOURCES)
assert 'radar-worker:' in (root / 'compose.yaml').read_text()
print('PASS: estrutura, domínios oficiais e worker configurados (não comprova coleta real)')
if not os.getenv('RADAR_PASSWORD'):
    print('ATENÇÃO: configure RADAR_PASSWORD antes de iniciar; não existe senha padrão.')
