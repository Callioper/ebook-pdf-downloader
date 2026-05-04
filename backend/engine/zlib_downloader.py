# ==== zlib_downloader.py ====
# 职责：ZLibrary登录、搜索和下载，支持多种浏览器指纹伪装
# 入口函数：ZLibDownloader.zlib_login(), zlib_search(), zlib_download(), download_file()
# 依赖：无
# 注意：使用curl_cffi绕过CloudFlare，支持代理和重试

import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from curl_cffi import requests as curl_requests

IMPERSONATES = ["chrome120", "chrome110", "edge101", "safari15_5"]
MAX_RETRIES = 3
Z_LIB_DOMAIN = "https://z-library.sk"
LOGIN_URL = f"{Z_LIB_DOMAIN}/rpc.php"
EAPI_LOGIN_URL = f"{Z_LIB_DOMAIN}/eapi/user/login"
EAPI_SEARCH_URL = f"{Z_LIB_DOMAIN}/eapi/book/search"


class ZLibDownloader:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.email = config.get("zlib_email", "")
        self.password = config.get("zlib_password", "")
        self.zfile_base = config.get("zfile_base_url", "")
        self.zfile_external = config.get("zfile_external_url", "")
        self.storage_key = config.get("zfile_storage_key", "1")
        self.proxy = config.get("http_proxy", "")
        self._session: Optional[curl_requests.Session] = None
        self._logged_in = False

    @property
    def _proxies(self):
        return {"http": self.proxy, "https": self.proxy} if self.proxy else None

    @property
    def _zfile_url(self):
        return self.zfile_base or self.zfile_external

    def _get_session(self) -> curl_requests.Session:
        if self._session is None:
            self._session = curl_requests.Session()
        if self.proxy:
            self._session.proxies = self._proxies
        return self._session

    async def zlib_login(self, email: str = "", password: str = "") -> Dict[str, Any]:
        email = email or self.email
        password = password or self.password
        if not email or not password:
            return {"ok": False, "message": "需要邮箱和密码"}

        session = self._get_session()
        last_error = ""

        # Method 1: rpc.php login (sertraline/zlibrary approach)
        for attempt in range(MAX_RETRIES):
            for imp in IMPERSONATES:
                try:
                    r = session.post(
                        LOGIN_URL,
                        data={
                            "isModal": True,
                            "email": email,
                            "password": password,
                            "site_mode": "books",
                            "action": "login",
                            "isSingleLogin": 1,
                            "redirectUrl": "",
                            "gg_json_mode": 1,
                        },
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        },
                        impersonate=imp,
                        timeout=20,
                    )
                    if r.status_code == 200:
                        try:
                            data = r.json()
                            resp = data.get("response", data)
                            if resp.get("validationError"):
                                return {"ok": False, "message": resp.get("validationError", "登录失败")}
                            if resp.get("error"):
                                return {"ok": False, "message": resp.get("error", "登录失败")}
                            self._logged_in = True
                            self._cookies = dict(session.cookies)
                            # Try to fetch account balance
                            balance = self._fetch_balance(session, imp)
                            result = {"ok": True, "message": "登录成功"}
                            if balance:
                                result["balance"] = balance
                            return result
                        except Exception:
                            pass
                except Exception as e:
                    last_error = str(e)
                    time.sleep(1)

        # Method 2: Fall back to EAPI login
        for attempt in range(MAX_RETRIES):
            for imp in IMPERSONATES:
                try:
                    r = session.post(
                        EAPI_LOGIN_URL,
                        json={"email": email, "password": password},
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        },
                        impersonate=imp,
                        timeout=20,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("success") == 1:
                            self._logged_in = True
                            balance = self._fetch_balance(session, imp)
                            result = {"ok": True, "message": "登录成功"}
                            if balance:
                                result["balance"] = balance
                            return result
                        return {"ok": False, "message": data.get("error", "邮箱或密码错误")}
                except Exception as e:
                    last_error = str(e)
                    time.sleep(1)
        return {"ok": False, "message": f"连接失败: {last_error}"}

    def _fetch_balance(self, session, imp: str) -> Optional[str]:
        """Fetch account balance/info after successful login."""
        try:
            # EAPI user profile endpoint - response has "user" nested object
            r = session.get(
                f"{Z_LIB_DOMAIN}/eapi/user/profile",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                impersonate=imp,
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                user = data.get("user", {})
                # downloads_limit and downloads_today are the actual fields
                dl_limit = user.get("downloads_limit", 0)
                dl_today = user.get("downloads_today", 0)
                if dl_limit or dl_today:
                    remaining = dl_limit - dl_today if dl_limit else 0
                    return f"今日下载: {dl_today}/{dl_limit if dl_limit else '∞'} (剩余 {remaining})"
                # Fallback: check top-level fields
                if data.get("downloads"):
                    return f"剩余下载: {data.get('downloads')}"
                if data.get("deposit"):
                    return f"余额: ${data.get('deposit')}"
                if data.get("premium"):
                    return f"高级会员: {data.get('premium')}"
        except Exception:
            pass
        return None

    async def zlib_search(self, query: str, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        if not self._logged_in:
            result = await self.zlib_login()
            if not result.get("ok"):
                return {"total": 0, "results": []}

        session = self._get_session()
        last_error = ""
        for attempt in range(MAX_RETRIES):
            for imp in IMPERSONATES:
                try:
                    # 用 form-encoded data（参考代码做法，JSON 可能不被 ZL eAPI 支持）
                    from urllib.parse import quote
                    form_data = f"message={quote(query)}&limit={limit}"
                    r = session.post(
                        EAPI_SEARCH_URL,
                        data=form_data,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        },
                        impersonate=imp,
                        timeout=30,
                    )
                    if r.status_code == 200:
                        result = r.json()
                        books = _extract_books(result)
                        logger.info(f"ZL search '{query[:40]}': HTTP 200, {len(books)} books")
                        return result
                    else:
                        logger.warning(f"ZL search '{query[:40]}': HTTP {r.status_code}")
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"ZL search error: {e}")
                    time.sleep(1)
        return {"total": 0, "results": []}

    async def zlib_download_book(self, book_id: str, book_hash: str, output_dir: str,
                                   filename: str = "") -> bool:
        if not self._logged_in:
            result = await self.zlib_login()
            if not result.get("ok"):
                return False

        session = self._get_session()
        os.makedirs(output_dir, exist_ok=True)
        # Sanitize filename
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)[:100] if filename else ""
        for attempt in range(MAX_RETRIES):
            for imp in IMPERSONATES:
                try:
                    r = session.get(
                        f"{Z_LIB_DOMAIN}/eapi/book/{book_id}/{book_hash}/file",
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        },
                        impersonate=imp,
                        timeout=30,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        download_url = data.get("file", {}).get("downloadLink", "") or data.get("downloadLink", "")
                        if download_url:
                            logger.info(f"ZL download URL obtained for {book_id}")
                            dl_r = session.get(download_url, impersonate=imp, timeout=60)
                            if dl_r.status_code == 200:
                                ext = data.get("file", {}).get("extension", "pdf")
                                # Use provided filename, fall back to book_id
                                fname = f"{safe_name}.{ext}" if safe_name else f"{book_id}.{ext}"
                                filepath = os.path.join(output_dir, fname)
                                with open(filepath, "wb") as f:
                                    f.write(dl_r.content)
                                file_size = os.path.getsize(filepath)
                                logger.info(f"ZL downloaded {filepath} ({file_size}B)")
                                if file_size > 1024:
                                    with open(filepath, "rb") as f:
                                        header = f.read(4)
                                    if ext == "pdf" and header != b"%PDF":
                                        logger.warning(f"ZL {book_id}: non-PDF content (size={file_size}), removed")
                                        try:
                                            os.remove(filepath)
                                        except Exception:
                                            pass
                                    else:
                                        logger.info(f"ZL {book_id}: valid file saved ({file_size}B)")
                                        return True
                                else:
                                    logger.warning(f"ZL {book_id}: file too small ({file_size}B), removed")
                                    try:
                                        os.remove(filepath)
                                    except Exception:
                                        pass
                            else:
                                logger.warning(f"ZL {book_id}: file download failed HTTP {dl_r.status_code}")
                        else:
                            logger.warning(f"ZL {book_id}: no downloadLink in response: {str(data)[:200]}")
                    else:
                        logger.warning(f"ZL {book_id}: API HTTP {r.status_code} (attempt {attempt+1}, imp={imp})")
                except Exception as e:
                    logger.warning(f"ZL {book_id}: exception (attempt {attempt+1}, imp={imp}): {e}")
                    time.sleep(1)
        return False

    async def download_file(self, task_id: str, book_id: str, output_dir: str) -> bool:
        import requests
        os.makedirs(output_dir, exist_ok=True)
        zfile_url = self._zfile_url
        if not zfile_url:
            return False
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            r = requests.get(
                f"{zfile_url}/api/v1/storage/{self.storage_key}/file/{book_id}",
                headers=headers,
                timeout=30,
                proxies=self._proxies,
            )
            if r.status_code == 200:
                pdf_path = os.path.join(output_dir, f"{book_id}.pdf")
                with open(pdf_path, "wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            pass
        return False

    # ==== 增强搜索和下载 ====

    @staticmethod
    def _verify_filesize(actual_bytes: int, expected_bytes: int, tolerance: float = 0.05) -> Tuple[bool, str]:
        """验证文件大小是否在容差范围内。返回(是否匹配, 匹配级别)"""
        if expected_bytes <= 0:
            return True, "size_unknown"
        if actual_bytes < 50000:  # 至少50KB
            return False, "too_small"
        ratio = abs(actual_bytes - expected_bytes) / expected_bytes if expected_bytes > 0 else 999
        if ratio <= 0.01:
            return True, "exact"
        if ratio <= tolerance:
            return True, "approximate"
        return False, "mismatch"

    async def zlib_search_tiered(
        self,
        isbn: str = "",
        title: str = "",
        authors: Optional[List[str]] = None,
        expected_size: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        三层检索策略：ISBN精确 → title+author复合 → title单独
        返回最佳匹配项（含id, hash, size, match_level），或None
        """
        authors = authors or []
        author_str = authors[0] if authors else ""

        # Tier 1: ISBN
        if isbn and len(isbn) >= 10:
            logger.info(f"ZL candidates tier 1: searching by ISBN='{isbn}'")
            result = await self.zlib_search(isbn, page=1, limit=10)
            books = _extract_books(result)
            logger.info(f"ZL candidates tier 1: {len(books)} raw results")
            for book in books:
                book_isbn = str(book.get("isbn", ""))
                if isbn.replace("-", "") in book_isbn.replace("-", ""):
                    match = self._check_book_match(book, expected_size, title, authors)
                    if match:
                        match["tier"] = 1
                        match["strategy"] = "isbn_exact"
                        return match

        # 第2层：title + author 复合搜索
        if title and author_str:
            query = f"{title} {author_str}"
            logger.info(f"ZL tiered search layer 2: title+author='{query[:60]}'")
            result = await self.zlib_search(query, page=1, limit=20)
            books = _extract_books(result)
            for book in books:
                match = self._check_book_match(book, expected_size, title, authors)
                if match:
                    match["tier"] = 2
                    match["strategy"] = "title_author"
                    # 高相关度的才直接返回，否则继续尝试
                    if match.get("title_score", 0) >= 40:
                        return match

            # 如果第2层没有高匹配结果，继续第3层
            best = None
            for book in books:
                match = self._check_book_match(book, expected_size, title, authors)
                if match and match.get("title_score", 0) > 15:
                    if not best or match.get("title_score", 0) > best.get("title_score", 0):
                        best = match
            if best:
                best["tier"] = 2
                best["strategy"] = "title_author_best"
                return best

        # 第3层：仅title搜索
        if title:
            logger.info(f"ZL tiered search layer 3: title='{title[:60]}'")
            result = await self.zlib_search(title, page=1, limit=20)
            books = _extract_books(result)
            best = None
            for book in books:
                match = self._check_book_match(book, expected_size, title, authors)
                if match:
                    if not best or match.get("title_score", 0) > best.get("title_score", 0):
                        best = match
            if best:
                best["tier"] = 3
                best["strategy"] = "title_only"
                return best

        return None

    async def zlib_search_candidates(
        self,
        isbn: str = "",
        title: str = "",
        authors: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索 ZL 并返回所有候选条目（不做标题过滤），供用户选择。
        按三层策略搜索：ISBN → title+author → title，合并去重。
        """
        authors = authors or []
        author_str = authors[0] if authors else ""
        seen = set()
        candidates = []

        # Tier 1: ISBN
        if isbn and len(isbn) >= 10:
            result = await self.zlib_search(isbn, page=1, limit=10)
            for book in _extract_books(result):
                book_id = str(book.get("id", ""))
                book_hash = book.get("hash") or book.get("book_hash") or ""
                if book_id and book_hash and book_id not in seen:
                    seen.add(book_id)
                    book_size = int(book.get("filesize", book.get("filesize_bytes", 0)))
                    candidates.append({
                        "id": book_id, "hash": book_hash,
                        "title": book.get("title", ""),
                        "authors": book.get("author", book.get("authors", "")),
                        "publisher": book.get("publisher", ""),
                        "year": book.get("year", ""),
                        "extension": book.get("extension", book.get("ext", "pdf")),
                        "size": book_size,
                        "source": "zlibrary",
                        "tier": 1, "strategy": "isbn",
                    })

        # Tier 2: title + author
        if title and author_str:
            query = f"{title} {author_str}"
            logger.info(f"ZL candidates tier 2: searching by title+author='{query[:60]}'")
            result = await self.zlib_search(query, page=1, limit=20)
            for book in _extract_books(result):
                book_id = str(book.get("id", ""))
                book_hash = book.get("hash") or book.get("book_hash") or ""
                if book_id and book_hash and book_id not in seen:
                    seen.add(book_id)
                    book_size = int(book.get("filesize", book.get("filesize_bytes", 0)))
                    candidates.append({
                        "id": book_id, "hash": book_hash,
                        "title": book.get("title", ""),
                        "authors": book.get("author", book.get("authors", "")),
                        "publisher": book.get("publisher", ""),
                        "year": book.get("year", ""),
                        "extension": book.get("extension", book.get("ext", "pdf")),
                        "size": book_size,
                        "source": "zlibrary",
                        "tier": 2, "strategy": "title_author",
                    })

        # Tier 3: title only
        if title:
            logger.info(f"ZL candidates tier 3: searching by title='{title[:60]}'")
            result = await self.zlib_search(title, page=1, limit=20)
            for book in _extract_books(result):
                book_id = str(book.get("id", ""))
                book_hash = book.get("hash") or book.get("book_hash") or ""
                if book_id and book_hash and book_id not in seen:
                    seen.add(book_id)
                    book_size = int(book.get("filesize", book.get("filesize_bytes", 0)))
                    candidates.append({
                        "id": book_id, "hash": book_hash,
                        "title": book.get("title", ""),
                        "authors": book.get("author", book.get("authors", "")),
                        "publisher": book.get("publisher", ""),
                        "year": book.get("year", ""),
                        "extension": book.get("extension", book.get("ext", "pdf")),
                        "size": book_size,
                        "source": "zlibrary",
                        "tier": 3, "strategy": "title_only",
                    })

        logger.info(f"ZL search_candidates: {len(candidates)} results for '{title}'")
        return candidates

    def _check_book_match(
        self,
        book: Dict[str, Any],
        expected_size: int = 0,
        search_title: str = "",
        search_authors: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        检查单个搜索结果是否匹配。
        验证项目（按优先级）：
        1. 必须有 id 和 hash
        2. 标题必须匹配（模糊匹配）
        3. 文件大小在容差内（如果有 expected_size）
        """
        book_id = str(book.get("id", ""))
        book_hash = book.get("hash") or book.get("book_hash") or ""
        if not book_id or not book_hash:
            return None

        book_title = book.get("title", "")
        title_score = 0

        if search_title and book_title:
            title_score = _calc_title_match(book_title, search_title, search_authors or [])
            # 低分标题直接拒绝
            if title_score < 10:
                logger.debug(f"ZL book {book_id}: title mismatch '{book_title}' vs '{search_title}' (score={title_score})")
                return None

        # 检查文件大小
        book_size = int(book.get("filesize", book.get("filesize_bytes", 0)))
        if expected_size > 0 and book_size > 0:
            ok, level = self._verify_filesize(book_size, expected_size, 0.05)
            if not ok:
                logger.debug(f"ZL book {book_id}: size mismatch (got {book_size}, expected {expected_size})")
                return None
        else:
            level = "size_unchecked"

        return {
            "id": book_id,
            "hash": book_hash,
            "size": book_size,
            "match_level": level,
            "title": book_title,
            "title_score": title_score,
            "extension": book.get("extension", book.get("ext", "pdf")),
        }

    async def zlib_download_verified(
        self,
        book_id: str,
        book_hash: str,
        output_dir: str,
        expected_size: int = 0,
        filename: str = "",
    ) -> Optional[str]:
        """下载并验证文件（含PDF头检查 + 大小验证），返回文件路径"""
        ok = await self.zlib_download_book(book_id, book_hash, output_dir, filename=filename)
        if not ok:
            return None

        # 查找下载的文件（先用定制的 filename，找不到再用 book_id）
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)[:100] if filename else ""
        if safe_name:
            for ext in ('.pdf', '.epub', '.mobi', '.djvu', '.zip'):
                f = Path(output_dir) / f"{safe_name}{ext}"
                if f.exists():
                    saved_files = [f]
                    break
            else:
                saved_files = list(Path(output_dir).glob(f"{book_id}.*"))
        else:
            saved_files = list(Path(output_dir).glob(f"{book_id}.*"))
        for f in saved_files:
            if f.stat().st_size < 1024:
                try:
                    f.unlink()
                except Exception:
                    pass
                continue

            # PDF 头验证
            if f.suffix.lower() == ".pdf":
                try:
                    with open(f, "rb") as fh:
                        if fh.read(4) != b"%PDF":
                            logger.warning(f"ZL downloaded non-PDF for {book_id}, removed")
                            f.unlink()
                            continue
                except OSError:
                    continue

            # 文件大小验证
            if expected_size > 0:
                ok, level = self._verify_filesize(f.stat().st_size, expected_size, 0.05)
                if not ok:
                    logger.warning(f"ZL size mismatch for {book_id}: {f.stat().st_size} vs {expected_size}")
                    f.unlink()
                    continue

            return str(f)

        return None


def _extract_books(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从Z-Library搜索结果中提取书籍列表"""
    books = result.get("books") or result.get("results") or result.get("data") or []
    if isinstance(books, dict):
        books = books.get("books", books.get("results", []))
    return books if isinstance(books, list) else []


def _calc_title_match(book_title: str, search_title: str, search_authors: Optional[List[str]] = None) -> int:
    """
    计算书籍标题与搜索标题的匹配度 (0-100)。
    基于CJK字符重叠率、关键词命中和作者辅助验证。
    """
    search_authors = search_authors or []
    bt = unicodedata.normalize("NFKC", book_title.lower()).strip()
    st = unicodedata.normalize("NFKC", search_title.lower()).strip()
    if not bt or not st:
        return 0

    # 1. 精确包含 → 100分
    if st in bt or bt in st:
        return 100
    # 2. 一个包含另一个的大部（长度短的80%以上被包含）
    min_len = min(len(st), len(bt))
    if min_len >= 2:
        if st in bt or bt in st:
            return 90

    # 3. CJK 字符重叠率
    bt_chars = set(c for c in bt if '\u4e00' <= c <= '\u9fff')
    st_chars = set(c for c in st if '\u4e00' <= c <= '\u9fff')
    char_score = 0
    if st_chars and bt_chars:
        overlap = len(bt_chars & st_chars)
        max_chars = max(len(st_chars), len(bt_chars))
        char_score = int((overlap / max_chars) * 100)

    # 4. 分词后词级别重叠
    bt_words = set(re.split(r'[\s,，、。．：；！？\-\u4e00-\u9fff]+', bt))
    st_words = set(re.split(r'[\s,，、。．：；！？\-\u4e00-\u9fff]+', st))
    bt_words.discard("")
    st_words.discard("")
    word_score = 0
    if st_words and bt_words:
        overlap_words = bt_words & st_words
        word_score = int((len(overlap_words) / max(len(st_words), 1)) * 100)

    score = max(char_score, word_score)

    # 5. 如果有关键词完全匹配（不含停用词），额外加分
    stop = set("的了不在有是和我对与就也还".strip())
    sig_words = [w for w in st_words if w not in stop and len(w) >= 2]
    if sig_words:
        all_found = all(any(sig in bw for bw in bt_words) for sig in sig_words)
        if all_found:
            score = max(score, 60)

    return min(score, 100)
