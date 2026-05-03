# 变更记录

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
