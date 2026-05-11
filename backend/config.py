# -*- coding: utf-8 -*-
# ==== config.py ====
# 职责：配置文件管理，加载、保存和更新应用配置
# 入口函数：init_config(), get_config(), update_config(), load_config(), save_config()
# 依赖：无
# 注意：支持frozen模式和跨平台（Windows/macOS/Linux）

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

def _get_app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        from platform_utils import get_app_data_dir as _get_ad
        new_dir = _get_ad('ebook-pdf-downloader')
        old_dir = new_dir.parent / 'BookDownloader'  # same parent, old name
        # Prefer new dir; fall back to old if it has data
        if old_dir.is_dir():
            if not new_dir.is_dir():
                try:
                    old_dir.rename(new_dir)
                except OSError:
                    pass
            if not new_dir.is_dir() or not (new_dir / "config.json").exists():
                return old_dir
        new_dir.mkdir(parents=True, exist_ok=True)
        return new_dir
    return Path(__file__).resolve().parent.parent

CONFIG_FILE = _get_app_dir() / "config.json"
APP_DATA_DIR = _get_app_dir()

def _get_default_config_path() -> Path:
    from platform_utils import get_default_config_file
    return get_default_config_file()

DEFAULT_CONFIG_FILE = _get_default_config_path()

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8000,
    "download_dir": "",
    "finished_dir": "",
    "tmp_dir": "",
    "stacks_base_url": "http://localhost:7788",
    "zfile_base_url": "",
    "zfile_external_url": "",
    "zfile_storage_key": "1",
    "http_proxy": "",
    "ocr_jobs": 1,
    "ocr_languages": "chi_sim+eng",
    "ocr_timeout": 3600,
    "ocr_oversample": 200,  # DPI for rendering pages before OCR, lower = faster, 150-400
    "llm_ocr_endpoint": "http://127.0.0.1:1234/v1",
    "llm_ocr_model": "qwen3-vl-4b-instruct",
    "llm_ocr_concurrency": 1,
    "llm_ocr_detect_batch": 20,
    "mineru_token": "",
    "mineru_model": "vlm",
    "paddleocr_online_token": "",
    "paddleocr_online_endpoint": "",
    "nlc_max_workers": 5,
    "ebook_data_geter_path": "",
    "ebook_db_path": "",
    "zlib_email": "",
    "zlib_password": "",
    "aa_membership_key": "",
    "ocr_engine": "tesseract",
    "flaresolverr_port": 8191,
    "stacks_api_key": "",
    "stacks_username": "",
    "stacks_password": "",
    "stacks_timeout": 180,
    "libgen_enabled": True,
    "pdf_compress": False,
    "pdf_compress_half": True,
    "ai_vision_enabled": True,
    "ai_vision_endpoint": "",
    "ai_vision_model": "",
    "ai_vision_api_key": "",
    "ai_vision_provider": "openai_compatible",
    "ai_vision_max_pages": 5,
    "ai_vision_dpi": 150,
}


def _default_paths() -> Dict[str, str]:
    home = Path.home()
    default_download = str(home / "Downloads" / "book-downloader")
    return {
        "download_dir": default_download,
        "finished_dir": os.path.join(default_download, "finished"),
        "tmp_dir": str(home / "tmp" / "bdw"),
        "ebook_data_geter_path": str(Path(__file__).resolve().parent / "nlc"),
        "ebook_db_path": str(Path(__file__).resolve().parent / "data"),
    }


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else CONFIG_FILE

    config = dict(DEFAULT_CONFIG)
    config.update(_default_paths())

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config.update(saved)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load config from {path}: {e}")
    return config


def save_config(data: Dict[str, Any], config_path: Optional[str] = None) -> None:
    path = Path(config_path) if config_path else CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (PermissionError, OSError) as e:
        raise IOError(f"Cannot write config to {path}: {e}")


CONFIG: Dict[str, Any] = {}


def init_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    global CONFIG
    CONFIG = load_config(config_path)
    return CONFIG


def get_config() -> Dict[str, Any]:
    return CONFIG


def update_config(data: Dict[str, Any]) -> Dict[str, Any]:
    global CONFIG
    CONFIG.update(data)
    save_config(CONFIG)
    return CONFIG
