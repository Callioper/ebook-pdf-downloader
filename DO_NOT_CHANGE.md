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

## AI 常见错误（千万不要犯）
- 不要用空 except: pass 静默异常 — 至少打印错误信息
- 不要删除前端 Handler 函数而不检查 JSX 引用 — 导致 TS 编译错误
- 不要修改已有函数的签名 — 新增功能用新函数
- 不要引入新的第三方库
- 不要用 assert 做业务验证 — 用 if/raise
- 全局变量不是线程安全的 — 勿并发调用
