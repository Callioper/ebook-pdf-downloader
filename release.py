# Ebook PDF Downloader - Build & Release Script
# Usage: python release.py [version] [--dry-run]
#
# === Feature Requirements (must persist across releases) ===
#
# 1. Version footer on every page
#    - Pages bottom bar shows: "v{version}" (left) + "github.com/Callioper/ebook-pdf-downloader" (right, clickable link)
#    - Version string comes from backend/version.py VERSION, embedded via /api/v1/check-update endpoint
#    - Must always display version, not just when update is available
#    - Implementation: Layout.tsx <footer>, uses check-update's "current" field
#
# 2. Auto-update check with dedup
#    - On app mount, GET /api/v1/check-update fetches latest GitHub release
#    - Respons returns { current, latest, has_update, download_url, setup_url, body, published_at }
#    - If has_update and latest != localStorage("last_update_seen"), show blue banner
#    - Dismiss button writes latest to localStorage("last_update_seen"), same version never re-shows
#    - "Re-check" button re-fetches; concurrent banner + re-check button visible
#    - No popups/notifications — only inline banner in Layout.tsx header
#
# 3. External search fallback
#    - When local SQLite search (DX_2.0-5.0.db + DX_6.0.db) returns 0 results, trigger external
#    - Anna's Archive: scrape search page for MD5 links, parse detail pages for metadata
#    - Z-Library: use zlib_downloader.py (curl_cffi) search API (requires login config)
#    - Results grouped by source: "外部来源 - Anna's Archive" / "外部来源 - Z-Library"
#    - External BookCard shows: title, author, publisher, year, format, size, language, ISBN
#    - "开始任务" button creates download task via POST /api/v1/tasks
#
# 4. Local search: both DBs simultaneously
#    - search_engine.py iterates both DX_2.0-5.0.db and DX_6.0.db, merged + deduped
#    - NO source selector dropdown — both DBs are always searched together
#    - ResultsPage shows combined results, source auto-detected from book.source field
#

import sys
import os
import re
import subprocess
import urllib.request
import json

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(PROJECT_DIR, "backend")
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
VERSION_FILE = os.path.join(BACKEND_DIR, "version.py")
SPEC_FILE = os.path.join(BACKEND_DIR, "book-downloader.spec")
SETUP_ISS = os.path.join(PROJECT_DIR, "setup.iss")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "Callioper/ebook-pdf-downloader"
INNO_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    os.path.expandvars(r"%ProgramFiles%\Inno Setup 6\ISCC.exe"),
]
INNO_SETUP = None
for p in INNO_PATHS:
    if os.path.exists(p):
        INNO_SETUP = p
        break

# Read current version
version_ns = {}
with open(VERSION_FILE, encoding="utf-8") as f:
    exec(f.read(), version_ns)
current_version = version_ns.get("VERSION", "0.0.0")

new_version = sys.argv[1] if len(sys.argv) > 1 else current_version
dry_run = "--dry-run" in sys.argv


def run(cmd, cwd=None, desc=""):
    print(f"  [{desc}] {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    if dry_run:
        print("    (dry-run, skipped)")
        return True
    result = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd,
                            capture_output=False, text=True)
    if result.returncode != 0:
        print(f"  ERROR: exit code {result.returncode}")
        return False
    return True


def step(name):
    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}")
    return name


def main():
    print(f"\n  Ebook PDF Downloader Release Builder")
    print(f"  Version: {current_version} -> {new_version}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print()

    # Step 1: Syntax check
    step("1/8: Syntax check")
    errors = []
    for root, dirs, files in os.walk(BACKEND_DIR):
        dirs[:] = [d for d in dirs if d not in ("venv", "__pycache__", "dist", "data")]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                try:
                    compile(open(path, encoding='utf-8').read(), path, "exec")
                except SyntaxError as e:
                    errors.append(f"{path}:{e.lineno}: {e.msg}")
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        sys.exit(1)
    print("  All Python files OK")

    # Step 2: Update version
    step("2/8: Update version")
    with open(VERSION_FILE, "w") as f:
        f.write(f'VERSION = "{new_version}"\n')
        f.write(f'GITHUB_REPO = "{GITHUB_REPO}"\n')
        f.write(f'UPDATE_CHECKED_KEY = "last_update_seen"\n')
    print(f"  Version: {new_version}")

    # Update version in setup.iss
    setup_iss_content = open(SETUP_ISS, encoding="utf-8").read()
    setup_iss_content = re.sub(r'^AppVersion=\S+', f'AppVersion={new_version}', setup_iss_content, flags=re.MULTILINE)
    with open(SETUP_ISS, "w", encoding="utf-8") as f:
        f.write(setup_iss_content)
    print(f"  Setup.iss AppVersion: {new_version}")

    # Step 3: Build frontend
    step("3/8: Build frontend")
    if not run("npm run build", cwd=FRONTEND_DIR, desc="npm build"):
        sys.exit(1)

    # Step 4: Self-check frontend
    step("4/8: Self-check frontend")
    frontend_dist = os.path.join(FRONTEND_DIR, "dist")
    checks = {
        "index.html": os.path.join(frontend_dist, "index.html"),
        "assets dir": os.path.join(frontend_dist, "assets"),
    }
    for label, path in checks.items():
        if not os.path.exists(path):
            print(f"  FAIL: {label} missing at {path}")
            sys.exit(1)
    # Check no version.js in dist (must use vite define, not public/ version.js)
    bad_version = os.path.join(frontend_dist, "version.js")
    if os.path.exists(bad_version):
        print(f"  FAIL: version.js found in dist root - use vite.config.ts define instead")
        sys.exit(1)
    # Verify APP_VERSION is embedded in JS bundle
    try:
        assets_dir = os.path.join(frontend_dist, "assets")
        for fname in os.listdir(assets_dir):
            if fname.endswith('.js'):
                with open(os.path.join(assets_dir, fname), 'r', encoding='utf-8', errors='ignore') as f:
                    js = f.read()
                if new_version in js:
                    print(f"  Frontend OK (v{new_version} in bundle, {fname})")
                    break
        else:
            print("  WARNING: Could not find version in JS bundle")
    except Exception:
        print("  WARNING: Could not verify version in JS bundle")

    # Step 5: Build exe
    step("5/8: Build exe (PyInstaller)")
    python = os.path.join(BACKEND_DIR, "venv", "Scripts", "python.exe")
    if not os.path.exists(python):
        print("  ERROR: venv not found. Run: python -m venv backend/venv && pip install -r backend/requirements.txt")
        sys.exit(1)
    # Kill any running instance that locks the exe
    if os.name == "nt":
        subprocess.run(["taskkill", "/f", "/im", "ebook-pdf-downloader.exe"], capture_output=True, shell=True)
    if not run([python, "-m", "PyInstaller", "--noconfirm", SPEC_FILE], cwd=BACKEND_DIR, desc="pyinstaller"):
        # Retry once after kill
        if os.name == "nt":
            subprocess.run(["taskkill", "/f", "/im", "ebook-pdf-downloader.exe"], capture_output=True, shell=True)
        if not run([python, "-m", "PyInstaller", "--noconfirm", SPEC_FILE], cwd=BACKEND_DIR, desc="pyinstaller retry"):
            sys.exit(1)
    built_exe = os.path.join(BACKEND_DIR, "dist", "ebook-pdf-downloader.exe")
    exe_path = os.path.join(PROJECT_DIR, "dist", "ebook-pdf-downloader.exe")
    os.makedirs(os.path.dirname(exe_path), exist_ok=True)
    import shutil as _shutil
    _shutil.copy2(built_exe, exe_path)
    print(f"  Copied: {built_exe} -> {exe_path}")
    exe_size = os.path.getsize(exe_path) if os.path.exists(exe_path) else 0
    print(f"  Exe: {exe_size/1024/1024:.1f} MB")

    # Step 6: Self-check exe
    step("6/8: Self-check exe")
    if exe_size < 10 * 1024 * 1024:
        print(f"  FAIL: Exe too small ({exe_size/1024/1024:.1f} MB), likely build error")
        sys.exit(1)
    if not dry_run:
        import subprocess as sp, time as _time, urllib.request as ur, json as _json
        proc = sp.Popen([exe_path, "--no-browser"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        tests_passed = 0
        tests_total = 6
        try:
            # Wait for startup
            for _ in range(30):
                try:
                    ur.urlopen("http://localhost:8000/api/v1/health", timeout=1)
                    break
                except Exception:
                    _time.sleep(0.5)
            else:
                print("  FAIL: Health endpoint not reachable")
                proc.kill()
                sys.exit(1)

            def api_test(name, path, method="GET", body=None, timeout=8):
                nonlocal tests_passed
                try:
                    req = ur.Request(f"http://localhost:8000{path}", data=body, method=method)
                    req.add_header("Content-Type", "application/json")
                    resp = ur.urlopen(req, timeout=timeout)
                    data = _json.loads(resp.read())
                    print(f"  PASS: {name}")
                    tests_passed += 1
                    return data
                except Exception as e:
                    print(f"  FAIL: {name} - {e}")
                    return None

            api_test("Health", "/api/v1/health")
            data = api_test("Config GET", "/api/v1/config")
            api_test("Config POST", "/api/v1/config", method="POST",
                     body=_json.dumps({"ocr_jobs": 1, "ocr_languages": "chi_sim+eng", "ocr_timeout": 1800}).encode())
            api_test("Search (empty db)", "/api/v1/search?query=&field=title", timeout=12)
            api_test("Detect Paths", "/api/v1/detect-paths", timeout=12)
            api_test("Check Update", "/api/v1/check-update", timeout=12)

            print(f"  Self-check: {tests_passed}/{tests_total} passed")
            if tests_passed < tests_total:
                print(f"  FAIL: not all tests passed")
                proc.kill()
                sys.exit(1)
        finally:
            proc.kill()
            _time.sleep(1)

    # Step 7: Build installer
    step("7/8: Build installer (Inno Setup)")
    setup_path = os.path.join(PROJECT_DIR, "dist", "ebook-pdf-downloader-setup.exe")
    if INNO_SETUP and os.path.exists(INNO_SETUP):
        if not run(f'"{INNO_SETUP}" "{SETUP_ISS}"', desc="inno setup"):
            sys.exit(1)
        print(f"  Setup: {os.path.getsize(setup_path)/1024/1024:.1f} MB")
    else:
        print("  Inno Setup not found, skipped")
        setup_path = None

    # Step 7: Git commit and release
    if dry_run:
        print(f"\n{'='*50}")
        print("  DRY RUN COMPLETE")
        print(f"{'='*50}")
        return

    step("8/8: Commit, push, and release")
    if not run("git add -A", cwd=PROJECT_DIR, desc="git add"):
        sys.exit(1)

    # Check if there are changes to commit
    status = subprocess.run("git status --porcelain", shell=True, cwd=PROJECT_DIR,
                            capture_output=True, text=True).stdout.strip()
    if status:
        if not run(f'git commit -m "release: v{new_version}"', cwd=PROJECT_DIR, desc="git commit"):
            sys.exit(1)
    else:
        print("  No changes to commit")

    if not run("git push", cwd=PROJECT_DIR, desc="git push"):
        sys.exit(1)

    # Create GitHub release
    if GITHUB_TOKEN:
        body = f"""## v{new_version}

### 新增
- 启动检测超时机制：软件启动时检测系统状态超过30秒将自动跳过，直接进入主界面

### 优化
- 提升启动体验，避免因后端组件不可用导致界面长时间卡在加载页
"""
        data = json.dumps({
            "tag_name": f"v{new_version}",
            "name": f"v{new_version}",
            "body": body,
            "draft": False,
            "prerelease": False,
        }).encode()

        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases",
            data=data,
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "User-Agent": "Python",
                "Accept": "application/vnd.github+json",
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=15)
        release = json.loads(resp.read())
        release_id = release["id"]
        print(f"  Release: {release.get('html_url')}")

        # Upload assets
        for name, path in [
            ("ebook-pdf-downloader.exe", exe_path),
            ("ebook-pdf-downloader-setup.exe", setup_path),
        ]:
            if not path or not os.path.exists(path):
                continue
            size = os.path.getsize(path)
            print(f"  Uploading {name} ({size/1024/1024:.1f} MB)...")
            upload_url = f"https://uploads.github.com/repos/{GITHUB_REPO}/releases/{release_id}/assets?name={name}"
            with open(path, "rb") as f:
                asset_data = f.read()
            req = urllib.request.Request(
                upload_url, data=asset_data,
                headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "User-Agent": "Python",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                    "Accept": "application/vnd.github+json",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=120)
            print(f"    Done")
    else:
        print("  GITHUB_TOKEN not set, skipping release creation")

    print(f"\n{'='*50}")
    print(f"  RELEASE v{new_version} COMPLETE")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
