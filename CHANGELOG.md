# 变更记录

## v1.5.0 — 2026-05-07 — 首次公开发布
- 后端：修复 main.py 重复 import 和硬编码版本号
- 后端：将 os._exit() 替换为优雅的 sys.exit() 关闭流程
- 后端：修复 frozen 模式下 config/tasks 路径解析
- 后端：限制 CORS 为 localhost，隐藏生产环境 API 文档
- 后端：添加 RotatingFileHandler 文件日志（生产模式）
- 构建：隐藏 PyInstaller 控制台窗口 (console=False)
- 构建：修正 .gitignore spec 文件追踪
- 前端：新增 ErrorBoundary 全局崩溃恢复组件
- 前端：修复 FolderPicker 按钮文案，footer emoji 替换为纯文本
- 文档：CHANGELOG 和 AI_CONTEXT 版本号对齐到 v1.5.0

## v1.4.0 — 2026-05-04 — OCR 修复 + 状态持久化
- 新增 backend/api/search.py : appleocr 检测和安装支持
- 新增 backend/api/search.py : check-zlib / check-proxy-status 状态持久化端点
- 新增 backend/api/search.py : Tesseract OCR 自动安装（UB-Mannheim GitHub 下载 + 静默安装）
- 修复 frontend/src/components/ConfigSettings.tsx : 10 个缺失的 handler 函数
- 修复 backend/api/search.py : _check_url() 连接/SSL 错误视为可达（绿色）

## v1.3.0 — FlareSolverr 安装 + 源站连通性
- 新增 FlareSolverr 一键安装功能
- 新增源站连通性检测面板
- 新增 Z-Library 登录 + 余额显示
