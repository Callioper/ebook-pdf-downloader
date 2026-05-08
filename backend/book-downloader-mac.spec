# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent

a = Analysis(
    [str(BACKEND_DIR / 'main.py')],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=[
        (str(PROJECT_DIR / 'config.default.json'), '.'),
        (str(BACKEND_DIR / 'static'), 'static'),
        (str(BACKEND_DIR / 'addbookmark'), 'addbookmark'),
    ],
    hiddenimports=[
        'engine.pipeline', 'engine.aa_downloader', 'engine.stacks_client',
        'engine.flaresolverr', 'engine.zlib_downloader',
        'api.search', 'api.tasks', 'api.ws',
        'nlc', 'book_sources', 'addbookmark',
        'task_store', 'ws_manager', 'search_engine', 'config',
        'platform_utils',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ebook-pdf-downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ebook-pdf-downloader',
)

app = BUNDLE(
    coll,
    name='ebook-pdf-downloader.app',
    bundle_identifier='com.ebook-pdf-downloader',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
    },
)
