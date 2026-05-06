# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

BACKEND_DIR = Path(SPECPATH)
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
NLC_DIR = BACKEND_DIR / "nlc"

a = Analysis(
    [str(BACKEND_DIR / "main.py")],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=[
        (str(FRONTEND_DIST), "frontend/dist"),
        (str(NLC_DIR / "nlc_isbn.py"), "nlc/nlc_isbn.py"),
        (str(NLC_DIR / "bookmarkget.py"), "nlc/bookmarkget.py"),
        (str(NLC_DIR / "headers.py"), "nlc/headers.py"),
        (str(NLC_DIR / "formatting.py"), "nlc/formatting.py"),
        (str(BACKEND_DIR / "engine"), "engine"),
        (str(BACKEND_DIR / "api"), "api"),
        (str(BACKEND_DIR.parent / "icon.ico"), "icon.ico"),
    ],
    excludes=[
        'torch', 'torchvision', 'torchaudio', 'torchgen',
        'torch._dynamo', 'torch._inductor', 'torch._functorch',
        'tensorboard', 'tensorflow',
        'onnx', 'onnxruntime',
        'matplotlib', 'tkinter',
        'modelscope', 'PIL.ImageShow',
    ],
    hiddenimports=[
        'uvicorn.logging', 'uvicorn.lifespan', 'uvicorn.protocols',
        'fastapi', 'pydantic',
        'bs4', 'bs4.builder', 'bs4.element',
        'requests', 'urllib3',
        'engine', 'engine.pipeline', 'engine.flaresolverr', 'engine.zlib_downloader',
        'api', 'api.search', 'api.tasks', 'api.ws',
        'config', 'search_engine', 'task_store', 'ws_manager', 'version',
        'curl_cffi',
        'engine.pdf_parallel',
        'engine.llm_ocr',
        'httpx', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    [],
    name='BookDownloader',
    debug=False,
    strip=False,
    upx=False,
    console=True,
    runtime_tmpdir=None,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(BACKEND_DIR.parent / "icon.ico"),
)