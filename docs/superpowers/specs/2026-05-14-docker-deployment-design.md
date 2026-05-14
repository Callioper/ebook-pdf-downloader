# Docker 部署版本 — 设计文档

> 从 `Callioper/ebook-pdf-downloader` 派生，不破坏原项目。

## 目标

将 ebook-pdf-downloader 打包为 Docker 镜像，支持一键部署到 NAS（如 QNAP TS-464C2）或 Linux 服务器。

## 架构

```
docker-compose.yml
├── app (自建镜像, ~2GB)
│   ├── Python 3.11 FastAPI 后端
│   ├── React/Vite 前端 (构建产物)
│   ├── Tesseract OCR + chi_sim/eng
│   ├── PaddleOCR (本地, CPU版)
│   └── local-llm-pdf-ocr (Surya版面检测)
├── stacks (ebook searcher, 已有Docker镜像, 端口7788)
└── flaresolverr (CF绕过, 已有Docker镜像, 端口8191)
```

所有OCR引擎内置：Tesseract（默认）、PaddleOCR、LLM OCR。

## 功能降级

| 功能 | Docker 行为 |
|------|------------|
| 检查更新 | 隐藏下载/安装按钮，提示 `docker pull` |
| 打开PDF | 改为浏览器下载文件 |
| 打开文件夹 | 不改动（原样保留） |
| FlareSolverr | 跳过本地进程管理，仅做健康检查 |
| 浏览器自启 | `--no-browser` |
| PaddleOCR 路径 | 兼容 Linux `venv-paddle311/bin/python` |

## 需要修改的文件

全部在新目录 `D:\opencode\ebook-pdf-downloader-docker\` 中修改，不动原项目。

| 文件 | 改动 |
|------|------|
| `backend/config.py` | Docker 默认路径：`/downloads` `/finished` `/tmp/bdw` |
| `backend/engine/pipeline.py` | PaddleOCR 搜索加 Linux venv 路径 |
| `backend/engine/flaresolverr.py` | Docker 跳过本地进程启停 |
| `backend/api/search.py` | `/install-update` 返回 Docker 提示 |
| `backend/platform_utils.py` | 加 `is_docker()` 函数 |
| `frontend/.../Layout.tsx` | 隐藏更新安装按钮，显示 `docker pull` 提示 |
| `frontend/.../ConfigSettings.tsx` | "打开PDF"→"下载文件"；检查更新改提示 |
| `Dockerfile` | 多阶段构建 |
| `docker-compose.yml` | 3 服务编排 |
| `.dockerignore` | 排除不必要文件 |

## 目录结构

```
D:\opencode\ebook-pdf-downloader-docker\
├── backend/                  (复制自原项目，含修改)
├── frontend/                 (复制自原项目，含修改)
├── config.default.json       (复制自原项目)
├── Dockerfile                (新建)
├── docker-compose.yml        (新建)
├── .dockerignore             (新建)
└── README.md                 (Docker版说明)
```

## 镜像内容

| 组件 | 来源 | 体积 |
|------|------|------|
| python:3.11-slim-bookworm | Docker Hub | ~150 MB |
| tesseract-ocr + chi_sim | apt-get | ~50 MB |
| ghostscript | apt-get | ~30 MB |
| fonts-noto-cjk | apt-get | ~80 MB |
| Python 依赖 (requirements.txt) | pip | ~300 MB |
| paddleocr (CPU) + ocrmypdf_paddleocr | pip (venv) | ~200 MB |
| local-llm-pdf-ocr + surya + uv | git clone + uv sync | ~1 GB |
| 前端构建产物 | 多阶段构建 | ~2 MB |
| **合计** | | **~1.8-2 GB** |
