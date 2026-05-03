# Book Downloader — 运行说明

## 前置要求
- Python 3.10+
- Node.js 18+
- Windows x64

## 源码运行

### 1. 虚拟环境
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 构建前端
```bash
cd frontend
npm install
npm run build
```

### 3. 启动
```bash
cd backend
python main.py
# → http://localhost:8000
```

## 构建 exe
```bash
python release.py
# dist/BookDownloader.exe + dist/book-downloader-setup.exe
```

## 测试
```bash
python test_smoke.py
```

## 项目结构
```
book-downloader/
├── backend/       # FastAPI 后端
│   ├── main.py   # 入口
│   ├── api/      # REST API
│   └── engine/   # 核心引擎
├── frontend/     # React 前端
├── dist/         # 构建输出
└── release.py    # 构建脚本
```
