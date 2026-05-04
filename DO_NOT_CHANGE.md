# 绝对不能改的东西

## 技术约束
- 不要改变 /api/v1/ 前缀的 API 路径（前端硬编码）
- 不要移除 config.py 的 CONFIG 全局变量
- 不要改变 version.py 的 VERSION / GITHUB_REPO 变量名
- 前端 APP_VERSION 通过 vite.config.ts define 注入
- 连接/SSL 错误标记为绿色+说明文字，而非红色

## 设计决策（不要推翻）
- FlareSolverr 用 subprocess 管理而非 Docker
- OCR 用 subprocess 调用而非 Python import
- Z-Library 用 curl_cffi 而非 requests
- Anna's Archive 通过 FlareSolverr + 直接请求双路径（Cloudflare 反爬）
- stacks Docker 服务为可选组件，不可用时自动降级到 AA 直接下载
- 下载降级顺序不可更改：AA/stacks → ZL(三层检索) → LibGen(兜底)

## 系统知识（出现过的坑，记住避免）
- `start /B` 在同一控制台启动进程 → bash tool 会卡死等待进程结束。
  正确做法：用 `pty_spawn` 启动长时间运行的进程，或用 `start "" cmd /c` 在新窗口启动。
- `requirements.txt` 锁定版本前必须先查 venv 实际安装版本，不能直接改 `>=` → `==`。
  用 `venv\Scripts\python.exe -m pip list --format=freeze` 获取实际版本。
- 中文注释/字符串在 Windows 上 `open()` 默认 `gbk` 编码会报错。
  所有 `open()` 调用必须显式指定 `encoding="utf-8"`。
- 代码修改后必须重建 exe（`python release.py`），否则用户运行的仍然是旧版。
- 关闭浏览器/前端页面时后端不会自动退出，需要前端主动调用 `/api/v1/shutdown`。
- stacks 两种认证方式不同：队列提交用 X-API-Key header，状态查询用 Authorization: Bearer。
- stacks "No mirrors found" 是永久失败，不应重试，应立即切换路径B。
- 不要把 EbookDatabase 的 second_pass_code 当作 MD5 使用，会导致 stacks 返回 "Invalid MD5"。
- AA 下载文件名可能是 .zip 但内容是纯 PDF（%PDF header），需检测后改名。
- ZIP 内含 PDG/JPG 图片页时需解压后用 PyMuPDF 拼接为 PDF。

## AI 常见错误（千万不要犯）
- 不要用空 except: pass 静默异常 — 至少打印错误信息
- 不要删除前端 Handler 函数而不检查 JSX 引用 — 导致 TS 编译错误
- 不要修改已有函数的签名 — 新增功能用新函数
- 不要引入新的第三方库
- 不要用 assert 做业务验证 — 用 if/raise
- 全局变量不是线程安全的 — 勿并发调用
