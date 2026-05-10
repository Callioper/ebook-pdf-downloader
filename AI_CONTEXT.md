# ebook-pdf-downloader — 项目上下文（AI 用）

## 项目概述
全自动电子书下载与处理工具。从本地 SQLite 数据库和在线书源（Anna's Archive、Z-Library）检索、下载、OCR 识别、PDF 压缩到最终输出，提供一站式管道处理。vibe coding 项目，由 AI 维护。

## 当前状态
- 版本：v1.2.0
- 功能数：约 20 个
- 后端源文件数：15 个 (Python)
- 前端源文件数：15+ 个 (TypeScript/TSX)
- 最后修改：2026-05-11

## 文件结构
| 文件 | 职责 | 稳定性 |
|------|------|--------|
| backend/main.py | FastAPI 入口，静态文件托管，CORS | 稳定 |
| backend/config.py | 配置加载/保存（JSON），全局 CONFIG | 核心，慎改 |
| backend/search_engine.py | SQLite DB 搜索（DX_2.0-5.0 + DX_6.0） | 稳定 |
| backend/task_store.py | 任务持久化（JSON 文件） | 稳定 |
| backend/version.py | 版本号 + GitHub 仓库信息 | 稳定 |
| backend/ws_manager.py | WebSocket 广播管理 | 稳定 |
| backend/api/search.py | REST API 路由（搜索/配置/OCR/Flare/代理/更新） | 活跃开发 |
| backend/api/tasks.py | 任务 CRUD API | 稳定 |
| backend/api/ws.py | WebSocket 连接管理 | 稳定 |
| backend/engine/flaresolverr.py | FlareSolverr 进程管理 + Cloudflare 绕过 | 活跃开发 |
| backend/engine/aa_downloader.py | Anna's Archive 搜索 + MD5 提取 | 活跃开发 |
| backend/engine/stacks_client.py | stacks Docker 下载管理器 | 活跃开发 |
| backend/engine/pipeline.py | 7 步处理管道 | 核心，慎改 |
| backend/engine/zlib_downloader.py | Z-Library curl_cffi 集成（三层检索）| 活跃开发 |
| backend/nlc/nlc_isbn.py | NLC ISBN 元数据查询 | 稳定 |
| frontend/src/App.tsx | React 路由入口 | 稳定 |
| frontend/src/components/ConfigSettings.tsx | 设置页面 | 活跃开发 |
| frontend/src/components/Layout.tsx | 布局框架 | 活跃开发 |

## 数据流
1. 用户搜索 → search_engine.py 查 SQLite
2. 无本地结果 → _search_annas_archive() / _search_zlib() 在线回退
3. 创建任务 → task_store.py 持久化
4. 执行任务 → pipeline.py 7 步处理
   - Step 3 多级下载降级：AA搜索→MD5→stacks→AA直连 → ZL三层检索 → LibGen
5. 实时更新 → ws_manager.py WebSocket 广播

## 技术约定
- Python 3.10+ / TypeScript 5.x
- 后端：FastAPI + Uvicorn
- 前端：React 18 + React Router + Tailwind CSS
- 构建：Vite + PyInstaller + Inno Setup
- 所有 Python 函数参数和返回值均有类型标注

## 已做出的设计决策
1. 使用 curl_cffi 用于 Z-Library（需 TLS 指纹模拟）
2. FlareSolverr 用 subprocess.Popen 管理，CREATE_NO_WINDOW
3. OCR 引擎用 subprocess 调用（避免 DLL 冲突）
4. 配置存 JSON 文件
5. 前端用 Tailwind CSS

## 已知限制
- FlareSolverr 安装仅支持 Windows
- AppleOCR 仅 macOS 可用
- Z-Library 需要有效邮箱+密码
- OCRmyPDF 需要 Tesseract 系统二进制
- requirements.txt 用 >= 而非精确版本锁定

## 待实现功能
- 已实现 - 书签处理（三源合并 + AI Vision TOC）
