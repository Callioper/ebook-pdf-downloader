# ==== main.py ====
# 职责：FastAPI应用入口，启动Web服务器，挂载路由和静态文件
# 入口函数：main(), serve_spa(), serve_root()
# 依赖：config, api.search, api.tasks, api.ws, search_engine, task_store, engine.flaresolverr
# 注意：支持打包后的frozen模式，自动查找frontend目录
import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import init_config, get_config
from config import APP_DATA_DIR as _app_data
from api.search import router as search_router
from api.tasks import router as tasks_router
from api.ws import router as ws_router
from search_engine import search_engine
from task_store import task_store
from version import VERSION
from engine.flaresolverr import stop_flaresolverr

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

logger = logging.getLogger("book-downloader")


def _setup_logging():
    log_dir = _app_data
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'app.log'

    handler = logging.handlers.RotatingFileHandler(
        str(log_file), maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    return log_file

_setup_logging()


def get_frontend_dir() -> Optional[str]:
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = str(Path(__file__).resolve().parent.parent)

    candidates = [
        os.path.join(base, "frontend", "dist"),
        os.path.join(base, "..", "frontend", "dist"),
        os.path.join(os.path.dirname(base), "frontend", "dist"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return os.path.normpath(c)
    return None


is_dev = not getattr(sys, 'frozen', False)

app = FastAPI(
    title="Book Downloader",
    version=VERSION,
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router)
app.include_router(tasks_router)
app.include_router(ws_router)

_last_heartbeat = 0.0


@app.get("/api/v1/heartbeat")
async def heartbeat():
    global _last_heartbeat
    _last_heartbeat = time.time()
    return {"ok": True}


@app.get("/api/v1/health")
async def health():
    return {"ok": True, "status": "running"}


@app.post("/api/v1/shutdown")
async def shutdown():
    def _do_shutdown():
        import time as _time
        _time.sleep(0.3)
        try:
            stop_flaresolverr()
        except Exception:
            pass
        try:
            from task_store import task_store
            task_store.stop()
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return {"ok": True, "message": "shutting down"}


frontend_dir = get_frontend_dir()

if frontend_dir and os.path.isdir(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str = ""):
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return JSONResponse({"error": "SPA not found"}, status_code=404)

    @app.get("/")
    async def serve_root():
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return JSONResponse({"app": "Book Downloader API"}, status_code=200)
else:
    @app.get("/")
    async def serve_root():
        return JSONResponse({"app": "Book Downloader API"}, status_code=200)


def main():
    try:
        config = init_config()
        host = config.get("host", "0.0.0.0")
        port = config.get("port", 8000)
        db_path = config.get("ebook_db_path", "")
        if db_path:
            search_engine.set_db_dir(db_path)

        # Retry on port conflict (stale process may still be releasing socket)
        import socket as _socket
        for attempt in range(1, 6):
            try:
                uvicorn.run(app, host=host, port=port, reload=False, log_level="info")
                break
            except SystemExit:
                break
            except Exception as e:
                err_str = str(e)
                if "10048" in err_str or "address already in use" in err_str.lower():
                    logger.warning(f"Port {port} in use, retrying ({attempt}/5)...")
                    time.sleep(2)
                    continue
                raise
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import webbrowser
    import atexit

    # Ensure FlareSolverr is cleaned up on exit
    atexit.register(stop_flaresolverr)

    from platform_utils import setup_console_handler
    setup_console_handler(stop_flaresolverr)

    config_data = init_config()
    port = config_data.get("port", 8000)
    url = f"http://localhost:{port}"

    if "--no-browser" not in sys.argv:
        def _open_browser():
            time.sleep(2)
            from platform_utils import open_browser
            open_browser(url, app_mode=True)
        threading.Thread(target=_open_browser, daemon=True).start()

    main()
