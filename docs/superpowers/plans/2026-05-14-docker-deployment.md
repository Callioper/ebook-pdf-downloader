# Docker 部署版本 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从原项目复制代码到新目录，添加 Docker 相关修改，打包为 Docker 镜像并上传到新 GitHub 仓库 `Callioper/ebook-pdf-downloader-docker`。

**Architecture:** 多阶段 Docker 构建（Node 20 编译前端 + Python 3.11 运行后端），docker-compose 编排 app + stacks + flaresolverr 三服务，全 OCR 引擎内置（Tesseract + PaddleOCR + LLM OCR）。

**Tech Stack:** Docker, Python 3.11, Node 20, FastAPI, React/Vite, Tesseract, PaddleOCR, Surya, uv

---

### Task 0: 创建新项目目录并复制代码

**Files:**
- Create: `D:\opencode\ebook-pdf-downloader-docker\` (entire directory tree)

- [ ] **Step 1: 创建目录结构**

```powershell
$src = "D:\opencode\book-downloader"
$dst = "D:\opencode\ebook-pdf-downloader-docker"
New-Item -ItemType Directory -Path "$dst\backend" -Force | Out-Null
New-Item -ItemType Directory -Path "$dst\frontend" -Force | Out-Null
```

- [ ] **Step 2: 复制 backend**

```powershell
$src = "D:\opencode\book-downloader"
$dst = "D:\opencode\ebook-pdf-downloader-docker"
Copy-Item -LiteralPath "$src\backend\*" -Destination "$dst\backend\" -Recurse -Force -Exclude "__pycache__",".pytest_cache","build","dist","*.spec"
Copy-Item -LiteralPath "$src\config.default.json" -Destination "$dst\config.default.json"
```

- [ ] **Step 3: 复制 frontend**

```powershell
$src = "D:\opencode\book-downloader"
$dst = "D:\opencode\ebook-pdf-downloader-docker"
Copy-Item -LiteralPath "$src\frontend\*" -Destination "$dst\frontend\" -Recurse -Force -Exclude "node_modules","dist",".vite"
```

- [ ] **Step 4: 初始化 git 并首次提交**

```powershell
Set-Location -LiteralPath "D:\opencode\ebook-pdf-downloader-docker"
git init
git add -A
git commit -m "init: copy source from Callioper/ebook-pdf-downloader"
```

---

### Task 1: 添加 `is_docker()` 工具函数

**Files:**
- Modify: `D:\opencode\ebook-pdf-downloader-docker\backend\platform_utils.py`

- [ ] **Step 1: 在文件开头、import 区之后添加 `is_docker()` 函数**

在 `is_linux()` 函数定义后（约第 22 行）插入：

```python
def is_docker() -> bool:
    """Detect if running inside a Docker container."""
    return os.environ.get("DOCKER", "").lower() == "true"
```

- [ ] **Step 2: 提交**

```bash
git add backend/platform_utils.py
git commit -m "feat: add is_docker() utility function"
```

---

### Task 2: 修改 config.py — Docker 默认路径

**Files:**
- Modify: `D:\opencode\ebook-pdf-downloader-docker\backend\config.py`

`DEFAULT_CONFIG` 字典（约第 42 行），修改 `download_dir`、`finished_dir`、`tmp_dir` 三个默认值：

- [ ] **Step 1: 修改 DEFAULT_CONFIG 中三个路径字段**

查找：
```python
    "download_dir": "",
    "finished_dir": "",
    "tmp_dir": "",
```

替换为：
```python
    "download_dir": "/downloads" if os.environ.get("DOCKER", "").lower() == "true" else "",
    "finished_dir": "/finished" if os.environ.get("DOCKER", "").lower() == "true" else "",
    "tmp_dir": "/tmp/bdw" if os.environ.get("DOCKER", "").lower() == "true" else "",
```

- [ ] **Step 2: 提交**

```bash
git add backend/config.py
git commit -m "feat: set Docker default paths via DOCKER env var"
```

---

### Task 3: 修改 pipeline.py — PaddleOCR Linux 路径

**Files:**
- Modify: `D:\opencode\ebook-pdf-downloader-docker\backend\engine\pipeline.py`

在 PaddleOCR venv 搜索段（约第 2237 行），添加 Linux 路径。

- [ ] **Step 1: 在 PaddleOCR 搜索候选列表中添加 Linux 路径**

查找：
```python
            for _cand in [
                r"D:\opencode\book-downloader\venv-paddle311\Scripts\python.exe",
                os.path.join(_base_dir, "venv-paddle311", "Scripts", "python.exe"),
            ]:
```

替换为：
```python
            for _cand in [
                r"D:\opencode\book-downloader\venv-paddle311\Scripts\python.exe",
                os.path.join(_base_dir, "venv-paddle311", "Scripts", "python.exe"),
                os.path.join(_base_dir, "venv-paddle311", "bin", "python"),      # Linux Docker
                os.path.join(_base_dir, "venv-paddle311", "bin", "python3"),     # Linux Docker alt
                sys.executable,  # fallback: paddleocr installed in main env
            ]:
```

- [ ] **Step 2: 提交**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: add Linux PaddleOCR venv paths for Docker"
```

---

### Task 4: 修改 flaresolverr.py — Docker 跳过本地进程

**Files:**
- Modify: `D:\opencode\ebook-pdf-downloader-docker\backend\engine\flaresolverr.py`

- [ ] **Step 1: 在文件顶部 import 区添加 `platform_utils` 导入**

查找现有 import（约文件开头），在合适位置添加：
```python
from platform_utils import is_docker
```

- [ ] **Step 2: 修改 `start_flaresolverr()` — 函数开头加 Docker 跳过逻辑**

在 `start_flaresolverr()` 函数体开头（`global _flare_process` 之后，约第 174 行），添加：

```python
    if is_docker():
        # In Docker, FlareSolverr runs as a separate container.
        # Just do a health check.
        if await check_flaresolverr(config):
            return (True, "FlareSolverr container is running")
        else:
            return (False, "FlareSolverr container not reachable at " + _flare_url(_get_flare_port(config)))
```

- [ ] **Step 3: 修改 `stop_flaresolverr()` — 函数开头加 Docker 跳过逻辑**

在 `stop_flaresolverr()` 函数体开头（`global _flare_process` 之后，约第 241 行），添加：

```python
    if is_docker():
        # FlareSolverr managed by docker-compose, not this process
        _flare_process = None
        return
```

- [ ] **Step 4: 提交**

```bash
git add backend/engine/flaresolverr.py
git commit -m "feat: skip local FlareSolverr process management in Docker"
```

---

### Task 5: 修改 search.py — `/install-update` Docker 提示

**Files:**
- Modify: `D:\opencode\ebook-pdf-downloader-docker\backend\api\search.py`

- [ ] **Step 1: 在 import 区添加 `is_docker` 导入**

在文件顶部 import 区添加：
```python
from platform_utils import is_docker
```

- [ ] **Step 2: 在 `install_update()` 函数开头添加 Docker 检测**

在 `install_update()` 函数体开头（`try:` 之前，约第 1775 行），添加：

```python
    if is_docker():
        return {"ok": False, "error": "Docker 版本请使用 docker compose pull && docker compose up -d 升级"}
```

- [ ] **Step 3: 提交**

```bash
git add backend/api/search.py
git commit -m "feat: return docker pull hint from install-update in Docker"
```

---

### Task 6: 修改前端 — 隐藏更新安装按钮、下载文件替代打开PDF

**Files:**
- Modify: `D:\opencode\ebook-pdf-downloader-docker\frontend\src\components\Layout.tsx`
- Modify: `D:\opencode\ebook-pdf-downloader-docker\frontend\src\components\ConfigSettings.tsx`
- (可选) Modify: `D:\opencode\ebook-pdf-downloader-docker\frontend\src\components\PDFPreviewPanel.tsx` / `TOCModal.tsx` 中"打开PDF"按钮

先探索前端组件找精确位置：

- [ ] **Step 1: 探索前端组件中所有"打开PDF"/"打开"/"更新/install"相关代码**

用 agent 搜索：
```
在 D:\opencode\ebook-pdf-downloader-docker\frontend\src\ 中搜索：
- "打开PDF" 或 "打开文件" 或 "openFile" 或 "open_file"
- "安装" 或 "install" 或 "handleInstall" 或 "update"
- "下载更新" 或 "重新检测" 或 "checkUpdate" 或 "handleDownload"
返回所有文件、行号、周围5行上下文。
```

- [ ] **Step 2: Layout.tsx — 隐藏更新安装按钮**

在 `Layout.tsx` 中，找到 `handleInstall` 和更新 banner 相关代码。
- 添加环境检测：从 API 获取 docker 状态（或检查 `window.location` 无法判断）
- **方案**：在 `/api/v1/health` 响应中添加 `platform: "docker"` 字段，前端据此隐藏按钮

先修改后端：在 `main.py` 的 `/api/v1/health` 端点添加 docker 信息：

在 `backend/main.py` 中的 `health()` 函数，改为：
```python
@app.get("/api/v1/health")
async def health():
    from platform_utils import is_docker
    return {"ok": True, "status": "running", "docker": is_docker()}
```

前端 Layout.tsx 中：
- 将"下载更新"按钮的渲染条件加入 `&& !isDocker`
- 将"安装并重启"按钮的渲染条件加入 `&& !isDocker`
- 添加"请使用 docker pull 升级"文字提示

具体修改（根据探索结果精确替换）。

- [ ] **Step 3: ConfigSettings.tsx — "打开PDF"→"下载文件"**

找到 ConfigSettings.tsx 中相关代码后：
- "打开PDF" 按钮 → 改为 `<a href={pdfUrl} download>` 下载链接
- 检查更新按钮 → 保留检查功能，但结果显示"docker pull"提示

- [ ] **Step 4: 提交**

```bash
git add frontend/ backend/main.py
git commit -m "feat: adapt UI for Docker (hide update install, download instead of open)"
```

---

### Task 7: 创建 .dockerignore

**Files:**
- Create: `D:\opencode\ebook-pdf-downloader-docker\.dockerignore`

- [ ] **Step 1: 创建 .dockerignore**

```
# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
.eggs/
build/
*.spec

# Node
frontend/node_modules/
frontend/dist/

# Git
.git/
.gitignore
.github/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# App runtime
app.log
tasks.json
config.json

# Docs
docs/

# Build outputs
*.exe
*.dmg

# Tests
tests/
.pytest_cache/

# Misc
*.iss
icon.*
*.cmd
*.ps1
temp_original.py
AI_CONTEXT.md
local-llm-pdf-ocr/
```

- [ ] **Step 2: 提交**

```bash
git add .dockerignore
git commit -m "chore: add .dockerignore"
```

---

### Task 8: 创建 Dockerfile（多阶段构建）

**Files:**
- Create: `D:\opencode\ebook-pdf-downloader-docker\Dockerfile`

- [ ] **Step 1: 创建 Dockerfile**

```dockerfile
# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime
FROM python:3.11-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    ghostscript \
    fonts-noto-cjk \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DOCKER=true

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Install PaddleOCR (CPU version) in a venv for the pipeline to discover
RUN python3 -m venv /app/backend/venv-paddle311 && \
    /app/backend/venv-paddle311/bin/pip install --no-cache-dir \
    paddlepaddle \
    paddleocr \
    ocrmypdf \
    ocrmypdf_paddleocr

# Clone and setup local-llm-pdf-ocr
RUN git clone --depth 1 https://github.com/Callioper/local-llm-pdf-ocr.git /app/local-llm-pdf-ocr && \
    cd /app/local-llm-pdf-ocr && \
    uv sync || echo "uv sync warning: continuing"

COPY backend/ ./backend/
COPY config.default.json ./config.default.json

COPY --from=frontend-builder /src/dist ./frontend/dist/

RUN mkdir -p /downloads /finished /tmp/bdw

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

ENTRYPOINT ["python", "backend/main.py", "--no-browser"]
```

- [ ] **Step 2: 提交**

```bash
git add Dockerfile
git commit -m "feat: add multi-stage Dockerfile with all OCR engines"
```

---

### Task 9: 创建 docker-compose.yml

**Files:**
- Create: `D:\opencode\ebook-pdf-downloader-docker\docker-compose.yml`

- [ ] **Step 1: 创建 docker-compose.yml**

```yaml
version: "3.8"

services:
  app:
    build: .
    image: callioper/ebook-pdf-downloader-docker:latest
    container_name: book-downloader
    ports:
      - "8000:8000"
    volumes:
      - config_data:/app
      - ./downloads:/downloads
      - ./finished:/finished
      - ./tmp:/tmp/bdw
    environment:
      - DOCKER=true
    restart: unless-stopped

  stacks:
    image: ghcr.io/callioper/book-searcher:latest
    container_name: book-searcher
    ports:
      - "7788:7788"
    volumes:
      - ./ebook-db:/data
    restart: unless-stopped
    profiles:
      - full

  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    container_name: flaresolverr
    ports:
      - "8191:8191"
    environment:
      - LOG_LEVEL=info
    restart: unless-stopped
    profiles:
      - full

volumes:
  config_data:
```

- [ ] **Step 2: 提交**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose with stacks and flaresolverr"
```

---

### Task 10: 创建 Docker 版 README.md

**Files:**
- Create: `D:\opencode\ebook-pdf-downloader-docker\README.md`

- [ ] **Step 1: 创建 README.md**

```markdown
# ebook-pdf-downloader (Docker 版)

> 基于 [Callioper/ebook-pdf-downloader](https://github.com/Callioper/ebook-pdf-downloader) v1.3.0

## 快速启动

```bash
# 仅启动核心应用（下载+OCR+书签）
docker compose up -d

# 启动全部服务（含 Stacks 检索引擎 + FlareSolverr CF绕过）
docker compose --profile full up -d
```

访问 `http://<your-ip>:8000`。

## 内置 OCR 引擎

- **Tesseract**（默认）：无需额外配置，中文+英文
- **PaddleOCR**：自动检测，CPU 推理
- **LLM OCR**：需配置外部 LLM API（Ollama / LM Studio / 豆包 / 智谱）

## 升级

```bash
docker compose pull app
docker compose up -d
```

## 数据持久化

| 目录 | 内容 |
|------|------|
| `./downloads/` | 下载的 PDF 文件 |
| `./finished/` | OCR 完成品 |
| `./tmp/` | 临时文件 |
| `./ebook-db/` | Stacks 电子书数据库（需自行放入 *.db 文件） |
| `config_data` (volume) | 应用配置文件 + 任务记录 |

## 配置 Stacks

放入 SQLite 数据库到 `./ebook-db/` 目录，然后在设置页配置：
- stacks_base_url: `http://stacks:7788`

## 配置 FlareSolverr

启用 FlareSolverr 后安娜的档案下载可绕过 Cloudflare 验证。
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: add Docker deployment README"
```

---

### Task 11: 构建镜像并本地验证

- [ ] **Step 1: 构建镜像**

```powershell
Set-Location -LiteralPath "D:\opencode\ebook-pdf-downloader-docker"
docker build -t ebook-pdf-downloader-docker:test .
```

Expected: 构建成功，无错误。时间约 10-15 分钟（首次需要下载 torch 等）。

- [ ] **Step 2: 启动测试容器**

```bash
docker run -d --name bdw-docker-test -p 8000:8000 ebook-pdf-downloader-docker:test
```

- [ ] **Step 3: 验证健康检查**

```bash
Start-Sleep -Seconds 20
docker ps --filter name=bdw-docker-test --format "{{.Status}}"
```

Expected: 包含 "(healthy)"。

- [ ] **Step 4: 验证 API**

```bash
curl -s http://localhost:8000/api/v1/health
```

Expected: `{"ok":true,"status":"running","docker":true}`

- [ ] **Step 5: 验证前端可访问**

```bash
curl -s http://localhost:8000/ | Select-String "root"
```

Expected: 包含 `<div id="root">`

- [ ] **Step 6: 验证 Tesseract 可用**

```bash
curl -s http://localhost:8000/api/v1/system-status
```

Expected: `ocr_tesseract` 组件状态 ok。

- [ ] **Step 7: 验证 PaddleOCR 路径**

```bash
docker exec bdw-docker-test ls /app/backend/venv-paddle311/bin/python
```

Expected: 文件存在。

- [ ] **Step 8: 清理**

```bash
docker rm -f bdw-docker-test
```

---

### Task 12: 上传到 GitHub 新仓库

- [ ] **Step 1: 创建 GitHub 仓库**

```bash
gh repo create Callioper/ebook-pdf-downloader-docker --public --source=. --remote=origin --push
```

- [ ] **Step 2: 推送所有代码**

```bash
git push -u origin master
```

- [ ] **Step 3: 创建 v1.3.0 Release**

```bash
gh release create v1.3.0 --title "v1.3.0 - Docker 初始版本" --notes "首次 Docker 版本发布。内置 Tesseract + PaddleOCR + LLM OCR 全引擎，支持 docker compose 一键部署。"
```

---

### Task 13: 构建并推送 Docker 镜像到 GitHub Container Registry

- [ ] **Step 1: 登录 GHCR**

```bash
echo $env:GITHUB_TOKEN | docker login ghcr.io -u Callioper --password-stdin
```

- [ ] **Step 2: 构建并推送**

```bash
docker build -t ghcr.io/callioper/ebook-pdf-downloader-docker:1.3.0 -t ghcr.io/callioper/ebook-pdf-downloader-docker:latest .
docker push ghcr.io/callioper/ebook-pdf-downloader-docker:1.3.0
docker push ghcr.io/callioper/ebook-pdf-downloader-docker:latest
```
