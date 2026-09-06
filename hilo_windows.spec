# -*- mode: python ; coding: utf-8 -*-
# hilo_windows.spec — PyInstaller spec pour Hilo (Windows)
# Généré pour V8.8.30

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['launch_hilo.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates',  'templates'),
        ('static',     'static'),
        # Fichiers Python additionnels embarqués comme data (importés dynamiquement)
        ('app.py',             '.'),
        ('hilo_db.py',         '.'),
        ('hilo_core.py',       '.'),
        ('hilo_colors.py',     '.'),
        ('sommeil_db.py',      '.'),
        ('am_rapport.py',      '.'),
        ('dashboard_template.py', '.'),
        ('migrate_hilo_db.py', '.'),
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Hilo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # Pas de fenêtre console (mode GUI)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icons/dashboard_sante.ico',
    onefile=True,           # Tout dans un seul .exe
)
