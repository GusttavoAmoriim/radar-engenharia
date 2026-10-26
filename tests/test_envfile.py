from app import envfile


def test_parse_handles_comments_quotes_and_equals_in_values():
    text = '# comentário\n\nRADAR_PASSWORD="minha senha longa"\nRADAR_MFA_ENCRYPTION_KEY=abc123==\nVAZIA=\nsem igual\n  RADAR_PUBLIC = 0 \n'
    assert envfile.parse(text) == {
        'RADAR_PASSWORD': 'minha senha longa',
        'RADAR_MFA_ENCRYPTION_KEY': 'abc123==',
        'VAZIA': '',
        'RADAR_PUBLIC': '0',
    }


def test_load_accepts_windows_notepad_bom_and_missing_file(tmp_path):
    file = tmp_path / '.env'
    file.write_bytes('﻿RADAR_PASSWORD=segredo-longo\r\nRADAR_PUBLIC=1\r\n'.encode())
    assert envfile.load(file) == {'RADAR_PASSWORD': 'segredo-longo', 'RADAR_PUBLIC': '1'}
    assert envfile.load(tmp_path / 'nao-existe') == {}
