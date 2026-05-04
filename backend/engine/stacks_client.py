# ==== stacks_client.py ====
# 职责：stacks Docker下载管理器客户端，提交MD5任务、轮询状态、查找下载文件
# 入口函数：StacksClient.add_task(), wait_for_download(), download_book()
# 依赖：aa_downloader (get_stacks_api_key)
# 注意：两种认证方式——队列提交用X-API-Key，状态查询用Bearer

import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# PDG 文件签名 (DuXiu 私有图片格式，前2字节通常是 00 01 / 01 00)
PDG_SIGNATURES = [b"\x00\x01", b"\x01\x00", b"\x15\x00"]


class StacksClient:
    """stacks Docker 下载管理器客户端"""

    def __init__(self, base_url: str = "http://localhost:7788", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._status_endpoint = f"{self.base_url}/api/status"
        self._queue_endpoint = f"{self.base_url}/api/queue/add"

        # 文件可能存在的两个路径（Docker volume 映射嵌套问题）
        home = Path.home()
        self._search_paths = [
            home / "stacks" / "stacks" / "download",  # cwd=~/stacks → ./download = ~/stacks/stacks/download
            home / "stacks" / "download",              # 直接映射
        ]

    def _headers_queue(self) -> Dict[str, str]:
        """队列提交用 X-API-Key 认证"""
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _headers_status(self) -> Dict[str, str]:
        """状态查询用 Bearer 认证"""
        h = {"Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """异步 HTTP 请求 — 通过 asyncio.to_thread 避免阻塞事件循环"""
        return await asyncio.to_thread(requests.request, method, url, **kwargs)

    async def add_task(self, md5: str) -> Dict[str, Any]:
        """提交MD5下载任务到stacks队列"""
        try:
            payload = {"md5": md5, "action": "download"}
            r = await asyncio.wait_for(
                self._request("POST", self._queue_endpoint, json=payload,
                              headers=self._headers_queue(), timeout=10),
                timeout=12,
            )
            data = r.json() if r.text else {}
            if r.status_code in (200, 201, 202):
                # stacks 返回 200 但 success=false 表示"已存在"
                success = data.get("success", True) or data.get("ok", True)
                msg = (data.get("message", "") or "").lower()
                if not success or "already" in msg or "downloaded" in msg:
                    logger.info(f"stacks: {md5} already in history")
                    return {"ok": True, "already_downloaded": True, "data": data}
                logger.info(f"stacks task submitted: md5={md5}, response={data}")
                return {"ok": True, "data": data}
            else:
                msg = data.get("message", "") or r.text[:200]
                if "already" in msg.lower() or "downloaded" in msg.lower():
                    return {"ok": True, "already_downloaded": True, "data": data}
                logger.warning(f"stacks add_task failed: {r.status_code} {r.text[:200]}")
                return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except asyncio.TimeoutError:
            logger.warning("stacks add_task timed out")
            return {"ok": False, "error": "timeout"}
        except requests.ConnectionError:
            logger.warning("stacks service unreachable (Docker not running?)")
            return {"ok": False, "error": "stacks服务不可达"}
        except Exception as e:
            logger.warning(f"stacks add_task error: {e}")
            return {"ok": False, "error": str(e)}

    async def get_status(self) -> Dict[str, Any]:
        """查询stacks服务状态和当前任务进度"""
        try:
            r = await self._request("GET", self._status_endpoint, headers=self._headers_status(), timeout=10)
            if r.status_code == 200:
                return {"ok": True, "data": r.json()}
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def history_clear(self) -> bool:
        """清除 stacks 下载历史"""
        try:
            r = await self._request("POST", f"{self.base_url}/api/history/clear",
                                     headers=self._headers_queue(), timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    async def history_retry(self, md5: str) -> bool:
        """重试 stacks 历史中的失败任务"""
        try:
            r = await self._request("POST", f"{self.base_url}/api/history/retry",
                                     json={"md5": md5},
                                     headers=self._headers_queue(), timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    async def wait_for_download(self, md5: str, timeout: int = 300, log_callback=None,
                                 download_dir: str = "") -> Optional[str]:
        """轮询等待stacks完成下载，返回文件路径或None"""
        import asyncio
        start = time.time()
        last_count = -1
        last_log = 0

        def _log(msg):
            logger.info(f"stacks: {msg}")
            if log_callback:
                try:
                    log_callback(msg)
                except Exception:
                    pass

        while time.time() - start < timeout:
            # 查询状态（优先，因为 status 接口返回 job 的 filepath）
            status = await self.get_status()
            if status.get("ok"):
                data = status["data"]
                jobs = data.get("jobs", data.get("queue", []))
                recent_history = data.get("recent_history", [])
                active = data.get("active", data.get("current", 0))
                completed = data.get("completed", data.get("done", 0))
                queue_size = data.get("queue_size", 0)
                workers = data.get("workers", [])

                # 检查 recent_history（stacks 已完成任务在此）
                for item in recent_history:
                    if isinstance(item, dict) and item.get("md5") == md5:
                        hist_path = item.get("filepath", "")
                        if hist_path:
                            # 解析容器内路径 → 主机路径
                            host_path = self._resolve_host_path(hist_path, md5, download_dir)
                            if host_path and os.path.exists(host_path) and os.path.getsize(host_path) > 1024:
                                _log(f"found in history: {host_path}")
                                return host_path

                # 检查当前任务
                for job in jobs:
                    if isinstance(job, dict) and job.get("md5") == md5:
                        job_status = job.get("status", "")
                        # 尝试从 job 中获取 filepath
                        job_path = job.get("filepath", "")
                        if job_path:
                            host_path = self._resolve_host_path(job_path, md5, download_dir)
                            if host_path and os.path.exists(host_path) and os.path.getsize(host_path) > 1024:
                                _log(f"download completed: {host_path}")
                                return host_path
                        if job_status in ("completed", "done", "finished"):
                            # 没有 filepath 时，用文件名搜索
                            filepath = self._find_downloaded_file(md5)
                            if filepath:
                                _log(f"download completed")
                                return filepath
                        elif job_status == "failed":
                            err = job.get("error", "unknown error")
                            _log(f"job failed: {err}")
                            return None
                        else:
                            _log(f"status: {job_status}")

                # 进度日志（每5秒输出一次）
                now = time.time()
                workers_active = sum(1 for w in workers if w.get("current_download_id")) if workers else 0
                remaining = int(timeout - (now - start))
                if now - last_log > 5:
                    _log(f"waiting... queue={queue_size or '?'}, active_workers={workers_active}, remaining={remaining}s")
                    last_log = now

                total = active + completed
                if total != last_count:
                    logger.debug(f"stacks: active={active}, completed={completed}")
                    last_count = total

            # 本地文件搜索兜底
            filepath = self._find_downloaded_file(md5)
            if filepath:
                _log(f"download found: {filepath}")
                return filepath

            await asyncio.sleep(2)

        _log(f"timed out ({timeout}s)")
        return self._find_downloaded_file(md5)

    def _resolve_host_path(self, container_path: str, md5: str, download_dir: str = "") -> Optional[str]:
        """将 stacks 容器内的路径解析为主机路径"""
        # 情况 1: 已经是主机路径
        if os.path.exists(container_path) and os.path.getsize(container_path) > 1024:
            return container_path
        # 情况 2: 检查两个可能的 Docker volume 映射路径
        base_name = os.path.basename(container_path)
        for search_base in self._search_paths:
            candidate = search_base / base_name
            if candidate.exists() and candidate.stat().st_size > 1024:
                return str(candidate)
        # 情况 3: 检查下载目录
        if download_dir:
            candidate = Path(download_dir) / base_name
            if candidate.exists() and candidate.stat().st_size > 1024:
                return str(candidate)
        # 情况 4: 递归搜索（慢，兜底）
        for search_base in self._search_paths:
            try:
                for f in search_base.rglob(base_name):
                    if f.is_file() and f.stat().st_size > 1024:
                        return str(f)
            except Exception:
                pass
        return None

    def _find_downloaded_file(self, md5: str, download_dir: str = "") -> Optional[str]:
        """在两个可能路径中查找与MD5匹配的下载文件（含 download_dir）"""
        # 优先级 1: 下载目录中按 MD5 搜索
        target_dirs = list(self._search_paths)
        if download_dir:
            target_dirs.insert(0, Path(download_dir))
        for base in target_dirs:
            if not base.exists():
                continue
            # 查找包含 MD5 的文件名
            for pattern in [f"*{md5}*", f"*{md5[:8]}*"]:
                for f in base.glob(pattern):
                    if f.is_file() and f.stat().st_size > 1024:
                        return str(f)
            # 深度查找（Max 2层）
            try:
                for f in base.rglob(f"*{md5}*"):
                    if f.is_file() and f.stat().st_size > 1024:
                        return str(f)
            except Exception:
                pass
        # docker cp 兜底
        return self._docker_cp_fallback(md5)

    def _docker_cp_fallback(self, md5: str) -> Optional[str]:
        """Docker volume映射未生效时，用docker cp从容器中拷贝文件"""
        try:
            # 查找stacks容器
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=stacks", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5,
            )
            container_name = result.stdout.strip()
            if not container_name:
                logger.warning("stacks container not found for docker cp fallback")
                return None

            # 在容器中查找文件
            find_result = subprocess.run(
                ["docker", "exec", container_name, "find", "/downloads", "-name", f"*{md5}*", "-type", "f"],
                capture_output=True, text=True, timeout=5,
            )
            remote_paths = [p.strip() for p in find_result.stdout.strip().split("\n") if p.strip()]
            for remote_path in remote_paths:
                local_dir = self._search_paths[0]  # ~/stacks/stacks/download
                local_dir.mkdir(parents=True, exist_ok=True)
                local_path = local_dir / os.path.basename(remote_path)
                cp_result = subprocess.run(
                    ["docker", "cp", f"{container_name}:{remote_path}", str(local_path)],
                    capture_output=True, text=True, timeout=30,
                )
                if cp_result.returncode == 0 and local_path.exists():
                    logger.info(f"docker cp fallback succeeded: {local_path}")
                    return str(local_path)
        except FileNotFoundError:
            logger.warning("docker not found in PATH, cannot use docker cp fallback")
        except Exception as e:
            logger.warning(f"docker cp fallback failed: {e}")
        return None

    @staticmethod
    def validate_and_fix_file(filepath: str, output_dir: str) -> Optional[str]:
        """
        验证并修复下载的文件：
        1. .zip 文件但内容是纯PDF → 直接改名
        2. ZIP内含PDG/JPG图片页 → 解压后用PyMuPDF拼接成PDF
        3. 其他格式 (.epub, .mobi) → 保留原样
        """
        if not os.path.exists(filepath) or os.path.getsize(filepath) < 1024:
            return None

        fname = os.path.basename(filepath)
        os.makedirs(output_dir, exist_ok=True)

        # 检查1: 文件头是PDF但扩展名不对 → 改名
        try:
            with open(filepath, "rb") as f:
                header = f.read(4)
        except OSError:
            logger.warning(f"validate_and_fix: cannot read {filepath}")
            return None

        if header.startswith(b"%PDF"):
            if not fname.lower().endswith(".pdf"):
                new_path = os.path.join(output_dir, fname.rsplit(".", 1)[0] + ".pdf")
                shutil.move(filepath, new_path)
                logger.info(f"Renamed PDF from wrong extension: {fname} → {os.path.basename(new_path)}")
                return new_path
            # 已经是 .pdf 且确实是PDF
            dest = os.path.join(output_dir, fname)
            if os.path.abspath(filepath) != os.path.abspath(dest):
                shutil.move(filepath, dest)
            return dest

        # 检查2: ZIP文件 → 解压并检查内容
        if fname.lower().endswith(".zip"):
            return _process_zip_file(filepath, output_dir)

        # 其他格式：保留并移动
        dest = os.path.join(output_dir, fname)
        shutil.move(filepath, dest)
        logger.info(f"Kept file as-is: {fname}")
        return dest

    async def download_book(
        self,
        md5: str,
        output_dir: str,
        timeout: int = 300,
    ) -> Optional[str]:
        """完整的stacks下载流程：提交任务 → 等待 → 验证修复"""
        # 提交任务
        result = await self.add_task(md5)
        if not result.get("ok"):
            logger.warning(f"stacks add_task failed: {result.get('error', 'unknown')}")
            return None

        # 等待下载完成
        filepath = await self.wait_for_download(md5, timeout)
        if not filepath:
            return None

        # 验证修复
        return self.validate_and_fix_file(filepath, output_dir)


def _process_zip_file(zip_path: str, output_dir: str) -> Optional[str]:
    """处理ZIP文件：检查是PDF伪装还是PDG/JPG图片集合"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if not names:
                logger.warning("Empty ZIP file")
                os.remove(zip_path)
                return None

            # 检查是否全是图片（JPG/PNG/BMP/TIFF/PDG）
            img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".pdg", ".gif"}
            img_names = [n for n in names if os.path.splitext(n.lower())[1] in img_exts]

            if len(img_names) >= len(names) * 0.7:
                # 大部分是图片 → 拼接成PDF
                return _images_zip_to_pdf(zip_path, output_dir, zf, img_names)

            # 检查是否有单个PDF在里面
            pdf_names = [n for n in names if n.lower().endswith(".pdf")]
            if len(pdf_names) == 1:
                # ZIP里只有一个PDF → 提取出来
                zf.extract(pdf_names[0], output_dir)
                extracted = os.path.join(output_dir, pdf_names[0])
                logger.info(f"Extracted PDF from ZIP: {pdf_names[0]}")
                os.remove(zip_path)
                return extracted

            # 不能处理的ZIP → 保留
            dest = os.path.join(output_dir, os.path.basename(zip_path))
            shutil.move(zip_path, dest)
            logger.info(f"Kept ZIP as-is: {os.path.basename(zip_path)}")
            return dest
    except zipfile.BadZipFile:
        logger.warning(f"Corrupt ZIP: {zip_path}")
        os.remove(zip_path)
        return None
    except Exception as e:
        logger.warning(f"ZIP processing failed: {e}")
        return None


def _images_zip_to_pdf(
    zip_path: str,
    output_dir: str,
    zf: zipfile.ZipFile,
    img_names: List[str],
) -> Optional[str]:
    """将ZIP中的图片集合拼接成PDF，封面/封底识别，自然排序"""
    import locale
    import tempfile

    # 封面/封底识别 → 放开头
    cover_patterns = re.compile(r"cov|cover|fengmian|!0+1", re.IGNORECASE)
    back_patterns = re.compile(r"bak|封底|back_cover", re.IGNORECASE)

    covers = [n for n in img_names if cover_patterns.search(n)]
    backs = [n for n in img_names if back_patterns.search(n)]
    others = [n for n in img_names if n not in covers and n not in backs]

    # 自然排序（数字感知）
    try:
        sort_key = lambda x: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", x)]
    except Exception:
        try:
            sort_key = locale.strxfrm
        except Exception:
            sort_key = lambda x: x

    sorted_others = sorted(others, key=sort_key)
    sorted_all = covers + sorted_others + backs

    # 提取到临时目录
    tmpdir = tempfile.mkdtemp(prefix="bdw_zip_")
    try:
        zf.extractall(tmpdir)
        img_paths = [os.path.join(tmpdir, n) for n in sorted_all if os.path.exists(os.path.join(tmpdir, n))]

        if not img_paths:
            logger.warning("No images extracted from ZIP")
            return None

        # 用PyMuPDF拼接成PDF
        pdf_name = os.path.splitext(os.path.basename(zip_path))[0] + ".pdf"
        pdf_path = os.path.join(output_dir, pdf_name)

        try:
            import fitz
            doc = fitz.open()
            for img_path in img_paths:
                try:
                    img = fitz.open(img_path)
                    if img.page_count > 0:
                        rect = img[0].rect
                        page = doc.new_page(width=rect.width, height=rect.height)
                        page.insert_image(rect, filename=img_path)
                    img.close()
                except Exception:
                    page = doc.new_page()
                    page.insert_image(page.rect, filename=img_path)
            doc.save(pdf_path)
            doc.close()
            logger.info(f"Created PDF from {len(img_paths)} images: {pdf_name}")
            os.remove(zip_path)
            return pdf_path
        except ImportError:
            logger.warning("PyMuPDF (fitz) not available for image→PDF conversion")
            return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
