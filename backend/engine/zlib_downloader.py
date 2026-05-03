import os
import time
from typing import Any, Dict, Optional

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
                            return {"ok": True, "message": "登录成功"}
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
                            return {"ok": True, "message": "登录成功"}
                        return {"ok": False, "message": data.get("error", "邮箱或密码错误")}
                except Exception as e:
                    last_error = str(e)
                    time.sleep(1)
        return {"ok": False, "message": f"连接失败: {last_error}"}

    async def zlib_search(self, query: str, page: int = 1, limit: int = 10) -> Dict[str, Any]:
        if not self._logged_in:
            result = await self.zlib_login()
            if not result.get("ok"):
                return {"total": 0, "results": []}

        session = self._get_session()
        last_error = ""
        for attempt in range(MAX_RETRIES):
            for imp in IMPERSONATES:
                try:
                    r = session.post(
                        EAPI_SEARCH_URL,
                        json={
                            "message": query,
                            "yearFrom": 1900,
                            "yearTo": 2026,
                            "lang": "",
                            "ext": "",
                            "order": "",
                        },
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        },
                        impersonate=imp,
                        timeout=20,
                    )
                    if r.status_code == 200:
                        return r.json()
                except Exception as e:
                    last_error = str(e)
                    time.sleep(1)
        return {"total": 0, "results": []}

    async def zlib_download_book(self, book_id: str, book_hash: str, output_dir: str) -> bool:
        if not self._logged_in:
            result = await self.zlib_login()
            if not result.get("ok"):
                return False

        session = self._get_session()
        os.makedirs(output_dir, exist_ok=True)
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
                            dl_r = session.get(download_url, impersonate=imp, timeout=60)
                            if dl_r.status_code == 200:
                                ext = data.get("file", {}).get("extension", "pdf")
                                filepath = os.path.join(output_dir, f"{book_id}.{ext}")
                                with open(filepath, "wb") as f:
                                    f.write(dl_r.content)
                                return True
                    return False
                except Exception:
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
