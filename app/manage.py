"""Maintenance commands.

docker compose exec concurso-radar python -m app.manage backup [/data/arquivo.sqlite3]
docker compose exec concurso-radar python -m app.manage migrate
docker compose exec concurso-radar python -m app.manage version
"""

import sys

from . import __version__, database


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    command = args.pop(0) if args else 'help'
    if command == 'backup':
        path = database.backup(args[0] if args else None)
        print(f'Backup criado: {path}')
    elif command == 'migrate':
        version = database.migrate()
        print(f'Banco na versão de esquema {version}')
    elif command == 'version':
        print(f'Radar Public Sector {__version__} · esquema {database.schema_version()}')
    else:
        print(__doc__)
        return 0 if command == 'help' else 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
