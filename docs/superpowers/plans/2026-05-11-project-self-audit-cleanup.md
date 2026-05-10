# v1.2.0 项目自检修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清除死代码、修复版本不一致、对齐 README 与实际实现、完善 GitHub 仓库配置。

**Architecture:** 分 6 个独立 Task，互不依赖，可并行执行。

**Tech Stack:** Python, Git, Markdown

---

### Task 1: 清除死代码和冗余文件

**Files:**
- Delete: `backend/addbookmark/bookmark_integrated.py`
- Delete: `backend/engine/stacks_client.py`
- Delete: `backend/nlc/main.py`
- Delete: `backend/nlc/formatting.py`
- Delete: `backend/nlc/bookmarkget.py`（注意：不删 `addbookmark/bookmarkget.py`，那是实际使用的）
- Delete: `backend/engine/__pycache__/llm_ocr.cpython-314.pyc`
- Delete: `backend/engine/__pycache__/pdf_parallel.cpython-314.pyc`
- Delete: `backend/engine/__pycache__/run_surya.cpython-314.pyc`
- Delete: `backend/engine/__pycache__/surya_embed.cpython-314.pyc`
- Modify: `backend/config.py:49,74` — 删除重复的 `stacks_base_url`
- Modify: `backend/config.py:77` — 删除未使用的 `download_timeout`
- Modify: `config.default.json:42` — 删除未使用的 `flaresolverr_binary`

- [ ] **Step 1: 删除死代码模块**

```powershell
cd D:\opencode\book-downloader
Remove-Item backend\addbookmark\bookmark_integrated.py
Remove-Item backend\engine\stacks_client.py
Remove-Item backend\nlc\main.py
Remove-Item backend\nlc\formatting.py
Remove-Item backend\nlc\bookmarkget.py
```

- [ ] **Step 2: 删除 stale .pyc 文件**

```powershell
Remove-Item backend\engine\__pycache__\llm_ocr.cpython-314.pyc
Remove-Item backend\engine\__pycache__\pdf_parallel.cpython-314.pyc
Remove-Item backend\engine\__pycache__\run_surya.cpython-314.pyc
Remove-Item backend\engine\__pycache__\surya_embed.cpython-314.pyc
```

- [ ] **Step 3: 删除 config.py 中重复的 `stacks_base_url`（第 73-74 行）**

读取 `backend/config.py`，找到：
```python
    "stacks_base_url": "http://localhost:7788",
    "stacks_api_key": "",
    "stacks_username": "",
    "stacks_password": "",
    "stacks_base_url": "http://localhost:7788",
```
删除第二行（74 行）`"stacks_base_url": "http://localhost:7788",`

- [ ] **Step 4: 删除 `download_timeout`**

在 `backend/config.py:DEFAULT_CONFIG` 中删除：
```python
    "download_timeout": 600,
```

- [ ] **Step 5: 删除 `flaresolverr_binary`**

在 `config.default.json` 中删除：
```json
    "flaresolverr_binary": ""
```

- [ ] **Step 6: 验证导入链**

```powershell
cd D:\opencode\book-downloader\backend
python -c "from engine.pipeline import run_pipeline; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: 提交**

```powershell
cd D:\opencode\book-downloader
git add -A
git commit -m "chore: remove dead code - unused modules, stale pyc, duplicate config keys"
```

---

### Task 2: 修复版本和文档不一致

**Files:**
- Modify: `.github/ISSUE_TEMPLATE/bug_report.md:29`
- Modify: `AI_CONTEXT.md:7-11,65`
- Modify: `README.md:206-233`（配置表默认值）

- [ ] **Step 1: 更新 issue template 版本号**

读取 `.github/ISSUE_TEMPLATE/bug_report.md`，找到第 29 行大约：
```
- 版本：v1.0.0
```
改为：
```
- 版本：v1.2.0
```

- [ ] **Step 2: 更新 AI_CONTEXT.md**

读取 `AI_CONTEXT.md`，更新：
- 第 7 行：`版本：v1.5.0` → `版本：v1.2.0`
- 第 11 行：`最后修改：2026-05-04` → `最后修改：2026-05-10`
- 第 65 行：`待实现功能 - 书签处理功能（前端已有占位 UI）` → `已实现 - 书签处理（三源合并 + AI Vision TOC）`

- [ ] **Step 3: 修正 README 配置表默认值**

读取 `README.md` 第 206-233 行，修正：

| 配置项 | README 错误值 | 正确值（来自代码） |
|--------|-------------|-----------------|
| 并发线程 | `1` | `4`（config.default.json） |
| 超时时间 | `3600s` | `7200s`（config.default.json） |
| 下载目录 | `Downloads` | `~/Downloads/book-downloader`（代码实际默认值） |

- [ ] **Step 4: 提交**

```powershell
cd D:\opencode\book-downloader
git add .github/ISSUE_TEMPLATE/bug_report.md AI_CONTEXT.md README.md
git commit -m "docs: fix version strings, correct README config defaults, update AI_CONTEXT"
```

---

### Task 3: 完善 README 结构说明和致谢

**Files:**
- Modify: `README.md`（项目结构 + 暂停行为说明 + 致谢）

- [ ] **Step 1: 更新项目结构**

在 README 第 284-325 行的 "项目结构" 部分补充缺失文件：

```markdown
├── backend/
│   ├── main.py              # FastAPI 入口，uvicorn 启动
│   ├── config.py            # 配置管理（APPDATA 持久化）
│   ├── version.py           # 版本号 + GitHub repo 标识
│   ├── requirements.txt     # Python 依赖列表
│   ├── platform_utils.py    # 跨平台进程管理（挂起/恢复/杀进程树）
│   ├── search_engine.py     # SQLite 双库并行检索引擎
│   ├── task_store.py        # 任务内存字典 + JSON 持久化
│   ├── ws_manager.py        # WebSocket 连接/订阅管理
```

- [ ] **Step 2: 修正暂停行为描述**

在 README 第 258 行，将：
```
| **暂停** | 终止 OCR 子进程树（LLM OCR），恢复后重新开始（已处理进度丢失），释放 LM Studio 资源 |
```
改为：
```
| **暂停** | LLM OCR：终止子进程树，恢复后重新 OCR。Tesseract/PaddleOCR：挂起子进程，恢复后继续 |
```

- [ ] **Step 3: 补充致谢**

在 README 第 367-380 行的 "致谢" 表格中新增两行：

```markdown
| [local-llm-pdf-ocr](https://github.com/ahnafnafee/local-llm-pdf-ocr) | LLM OCR 管道（Surya 检测 + LLM 识别 + PyMuPDF 嵌入） |
| [Surya](https://github.com/VikParuchuri/surya) | 文档版面检测模型（DetectionPredictor） |
```

- [ ] **Step 4: 提交**

```powershell
cd D:\opencode\book-downloader
git add README.md
git commit -m "docs: update project structure, clarify pause behavior, add acknowledgments"
```

---

### Task 4: 添加 GitHub PR 模板和 CI 骨架

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: 创建 PR 模板**

新建 `.github/PULL_REQUEST_TEMPLATE.md`：

```markdown
## 变更说明

简要描述此 PR 做了什么。

## 变更类型

- [ ] 新功能
- [ ] Bug 修复
- [ ] 文档更新
- [ ] 代码重构
- [ ] 构建/依赖

## 测试

- [ ] `python -m compileall backend/` 通过
- [ ] `cd frontend && npm run build` 通过
- [ ] 手动测试通过

## 截图（如有 UI 变更）

## 关联 Issue

Closes #
```

- [ ] **Step 2: 创建 CI 工作流骨架**

新建 `.github/workflows/ci.yml`：

```yaml
name: CI

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - name: Compile check backend
        run: |
          python -c "import ast, os, sys
          errors = 0
          for root, dirs, files in os.walk('backend'):
              dirs[:] = [d for d in dirs if d not in ('__pycache__', '.pytest_cache', 'venv', '.venv', 'dist', 'build')]
              for f in files:
                  if f.endswith('.py'):
                      path = os.path.join(root, f)
                      try:
                          with open(path, 'rb') as fh:
                              ast.parse(fh.read())
                      except SyntaxError as e:
                          print(f'SyntaxError in {path}: {e}')
                          errors = 1
          sys.exit(errors)"
      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: '18'
      - name: TypeScript check
        run: |
          cd frontend
          npm install
          npx tsc --noEmit
```

- [ ] **Step 3: 提交**

```powershell
cd D:\opencode\book-downloader
git add .github/
git commit -m "ci: add PR template and CI workflow skeleton"
```

---

### Task 5: 构建 exe 并推送

**Files:**
- Rebuild: `backend/dist/ebook-pdf-downloader.exe`

- [ ] **Step 1: 构建前端**

```powershell
cd D:\opencode\book-downloader\frontend; powershell -ExecutionPolicy Bypass -Command "npm run build"
```

- [ ] **Step 2: 构建 exe**

```powershell
Get-Process -Name "ebook-pdf-downloader" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 3
cd D:\opencode\book-downloader\backend; python -m PyInstaller book-downloader.spec --noconfirm
```

- [ ] **Step 3: 推送**

```powershell
cd D:\opencode\book-downloader
git push origin master
```

---

## Summary

| Task | 优先级 | 内容 |
|------|:--:|------|
| 1 | 高 | 删除死代码、stale .pyc、重复 config key |
| 2 | 高 | 修正版本号、README 默认值、AI_CONTEXT |
| 3 | 中 | 补充 README 结构说明、暂停行为、致谢 |
| 4 | 中 | 创建 PR 模板和 CI 工作流 |
| 5 | — | 重新构建 exe 并推送 |
