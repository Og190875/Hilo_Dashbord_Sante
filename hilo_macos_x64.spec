# -*- mode: python ; coding: utf-8 -*-
# hilo_macos_x64.spec — PyInstaller spec pour Hilo (macOS Intel x86_64)
# Build via Rosetta : arch -x86_64 zsh → source ~/venv-hilo-intel/bin/activate

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['launch_hilo.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates',             'templates'),
        ('static',                'static'),
        ('app.py',                '.'),
        ('hilo_db.py',            '.'),
        ('hilo_core.py',          '.'),
        ('hilo_colors.py',        '.'),
        ('sommeil_db.py',         '.'),
        ('am_rapport.py',         '.'),
        ('dashboard_template.py', '.'),
        ('migrate_hilo_db.py',    '.'),
    ],
    hiddenimports=[
        'flask',
        'flask.templating',
        'jinja2',
        'jinja2.ext',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.routing',
        'sqlite3',
        'pdfplumber',
        'pandas',
        'zoneinfo',
        'zoneinfo._tzdata',
        'email.mime.text',
        'email.mime.multipart',
        'requests',
        'urllib3',
        'certifi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Hilo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,       # Important pour macOS
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file=None,
    icon='icons/dashboard_sante.icns',  # macOS utilise .icns
)

app = BUNDLE(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='Hilo.app',
    icon='icons/dashboard_sante.icns',
    bundle_identifier='fr.olivier.hilo',
    info_plist={
        'CFBundleName': 'Hilo',
        'CFBundleDisplayName': 'Hilo',
        'CFBundleVersion': '9.0.2',
        'CFBundleShortVersionString': '9.0.2',
        'NSHighResolutionCapable': True,
        'LSUIElement': False,
    },
)
