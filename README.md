# Book Downloader

<p align="center">
  <img src="icon.png" width="128" alt="Book Downloader">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-green" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="License">
  <img src="https://img.shields.io/badge/platform-Windows%20x64-lightgrey" alt="Platform">
</p>

全自动电子书下载与处理工具。从本地 SQLite 数据库和在线书源检索、下载、OCR、压缩到最终输出，提供一站式管道处理。

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#功能">功能</a> ·
  <a href="#配置">配置</a> ·
  <a href="#依赖安装">依赖安装</a> ·
  <a href="#构建">构建</a> ·
  <a href="#致谢">致谢</a>
</p>

## 快速开始

### 便携版（推荐）

从 [Releases](https://github.com/Callioper/book-downloader/releases) 下载 `BookDownloader.exe`，双击运行即可。

```
BookDownloader.exe → 自动打开浏览器 → http://localhost:8000
```

### 安装版

下载 `book-downloader-setup.exe`，安装到 `Program Files`，自动创建桌面快捷方式和开始菜单项，支持自定义安装目录和卸载。

### 源码运行

```bash
git clone https://github.com/Callioper/book-downloader.git
cd book-downloader/backend
pip install -r requirements.txt
python main.py
```

## 功能

<table>
<tr><td width="50%">

### 🔍 检索
- **本地 SQLite 数据库** — 直读 `DX_2.0-5.0.db` / `DX_6.0.db`
- **高级搜索** — 多字段组合（书名/作者/ISBN/SS码）
- **外部回退** — 本地无结果自动搜索 Anna's Archive + Z-Library
- **自动去重** — 按 ISBN + SS码 去重

</td><td width="50%">

### 📥 下载
- **FlareSolverr 绕过** — 自动解决 Cloudflare/DDoS-Guard
- **Anna's Archive** — 会员高速 + 慢速下载
- **Z-Library eAPI** — 邮箱密码登录，自动搜索下载
- **IPFS / aria2c BT** — 去中心化下载回退

</td></tr>
<tr><td>

### ⚙️ 处理管道
1. 检索信息（NLC 数据库 + 书葵网目录）
2. 下载 PDF（多源自动选择）
3. OCR 文字识别（4 种引擎）
4. PDF 压缩
5. 生成书签
6. 保存到本地 + 生成报告

</td><td>

### 🎨 界面
- **Edge App 模式** — 内嵌窗口，无需浏览器
- **WebSocket 实时更新** — 下载速度、OCR 进度、ETA
- **响应式设计** — 适配不同屏幕
- **任务管理** — 重试、清除、批量操作

</td></tr>
</table>

## 配置

在设置页（右上角 ⚙️）中配置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| SQLite 数据库目录 | 存放 `.db` 文件的路径 | 自动检测 |
| 下载目录 | PDF 临时存放 | `~/Downloads/book-downloader` |
| 保存目录 | 最终输出位置 | `~/Downloads/book-downloader/finished` |
| HTTP 代理 | 访问外网所需 | （可选） |
| AA 会员 Key | 高速下载 | （可选） |
| Z-Library 邮箱/密码 | 自动搜索下载 | （可选） |
| OCR 引擎 | Tesseract/PaddleOCR/EasyOCR/AppleOCR | Tesseract |

## 依赖安装

### 必需（手动安装）

| 组件 | 用途 | 安装 |
|------|------|------|
| **Python 3.10+** | 运行环境 | [python.org](https://www.python.org/downloads/) |
| **数据库文件** | 本地检索 | [EbookDatabase 下载文档](https://github.com/Hellohistory/EbookDatabase/blob/main/Markdown/%E6%95%B0%E6%8D%AE%E5%BA%93%E4%B8%8B%E8%BD%BD%E6%96%87%E6%A1%A3.md) |
| **Tesseract OCR** | OCR 默认引擎二进制 | `winget install UB-Mannheim.TesseractOCR`（安装时勾选中英文语言包） |

> 下载数据库文件（`DX_2.0-5.0.db` / `DX_6.0.db`）后，放入 `backend/data/` 目录或任意目录，在设置页配置路径即可。应用提供「智能查找」按钮一键扫描常见位置。

### 一键安装

在设置页对应面板中点击安装按钮：

| 组件 | 用途 | 安装方式 |
|------|------|----------|
| **FlareSolverr** | Cloudflare 绕过 | 设置页 → 下载栏 → 一键安装 |
| **PaddleOCR** | 中文 OCR（推荐） | 设置页 → OCR 面板 → 安装 |
| **EasyOCR** | 多语言 OCR | 设置页 → OCR 面板 → 安装 |
| **aria2c** | BT 下载引擎 | 已内置 |

### 前端开发

```bash
cd frontend
npm install
npm run build
```

## 构建

```bash
# 便携版 exe
cd backend
pip install pyinstaller
pyinstaller --noconfirm book-downloader.spec

# 安装版（需 Inno Setup）
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/search` | 搜索电子书 |
| POST | `/api/v1/tasks` | 创建下载任务 |
| POST | `/api/v1/tasks/{id}/start` | 启动处理管道 |
| POST | `/api/v1/tasks/{id}/retry` | 重试失败任务 |
| DELETE | `/api/v1/tasks/completed` | 清除已完成 |
| GET | `/api/v1/tasks/{id}/open` | 打开 PDF |
| POST | `/api/v1/check-proxy` | 代理连通性检测 |
| POST | `/api/v1/zlib-fetch-tokens` | Z-Library 登录 |
| GET | `/api/v1/zlib-quota` | 下载额度查询 |
| GET/POST | `/api/v1/check-ocr` | OCR 检测/安装 |
| GET | `/api/v1/check-flare` | FlareSolverr 状态 |
| POST | `/api/v1/install-flare` | 安装 FlareSolverr |
| GET | `/api/v1/detect-paths` | 智能查找数据库 |

## 项目结构

```
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置管理
│   ├── search_engine.py     # SQLite 检索引擎
│   ├── task_store.py        # 任务持久化
│   ├── api/                 # REST API（search/tasks/ws）
│   ├── engine/              # 核心引擎
│   │   ├── pipeline.py      # 6 步处理管道
│   │   ├── flaresolverr.py  # FlareSolverr 集成
│   │   └── zlib_downloader.py # Z-Library curl_cffi
│   ├── nlc/                 # NLC 元数据爬虫
│   └── data/                # 数据库文件（自动检测）
├── frontend/                # React + TypeScript + Tailwind
├── setup.iss                # Inno Setup 安装脚本
└── 启动.cmd                  # Windows 启动器
```

## 致谢

本项目参考、使用或借鉴了以下开源项目：

| 项目 | 用途 |
|------|------|
| [stacks](https://github.com/zelestcarlyone/stacks) | AA 下载架构、fast_download API、FlareSolverr 集成、cookie 管理 |
| [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) | Cloudflare/DDoS-Guard 自动绕过 |
| [ZlibraryAPI](https://github.com/cu-sanjay/ZlibraryAPI) | Z-Library eAPI 封装参考 |
| [zlibrary](https://github.com/sertraline/zlibrary) | Z-Library 客户端参考 |
| [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) | PDF OCR 引擎 |
| [aria2](https://github.com/aria2/aria2) | BitTorrent/HTTP 下载引擎 |
| [cookie-editor](https://github.com/moustachauve/cookie-editor) | Cookie 导出格式参考 |
| [NLCISBNPlugin](https://github.com/DoiiarX/NLCISBNPlugin) | NLC ISBN 查询原始项目 |
| [书葵网](https://www.shukui.net/) | 图书目录/书签数据 |
| [Anna's Archive](https://annas-archive.org/) | 开放图书数据源 |
| [Z-Library](https://z-lib.sk/) | 图书下载源 |

## License

MIT © Book Downloader