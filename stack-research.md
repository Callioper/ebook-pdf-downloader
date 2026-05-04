# Stacks 匹配逻辑调研报告

## 项目概述

**Stacks** (github.com/zelestcarlyone/stacks) 是一个 Docker 容器化的下载队列管理器，专为 Anna's Archive 设计。核心定位是"已知道 MD5 后的下载工具"，而非检索工具。

---

## Stacks 的匹配逻辑

### 核心发现：Stacks 没有"匹配逻辑"

Stacks **不做任何搜索或模糊匹配**。它的完整流程是：

1. **用户安装 Tampermonkey 脚本** → 脚本在 AA 搜索结果页和 MD5 详情页注入 "Download" 按钮
2. **用户自己在 AA 上浏览** → 找到想下载的书 → 点击 Stacks 注入的按钮
3. **Tampermonkey 提取 MD5** → 从 AA 页面 URL 中提取 `/md5/{md5}` 的 32 位 hex
4. **提交到 Stacks API** → `POST /api/queue/add { "md5": "...", "source": "search-page" }`
5. **Stacks 下载** → 用 MD5 请求 AA 的 `/md5/{md5}` 页面，解析下载链接

```mermaid
flowchart LR
    User[用户在AA浏览] --> Browse[AA搜索/详情页]
    Browse --> Extract[Tampermonkey提取MD5]
    Extract --> Queue[POST /api/queue/add]
    Queue --> MD5AA[GET /md5/{md5}]
    MD5AA --> Parse[BeautifulSoup解析]
    Parse --> Fast[Fast Download?]
    Fast -->|No| Slow[slow_download链接]
    Slow --> Mirror[外部镜像]
    Mirror --> Download[下载文件]
    Download --> Verify[MD5校验]
```

### MD5 来源路径

`src/stacks/utils/md5utils.py`:
```python
def extract_md5(input_string):
    """从URL中提取MD5，或返回MD5本身"""
    if re.match(r'^[a-f0-9]{32}$', input_string.lower()):
        return input_string.lower()
    match = re.search(r'/md5/([a-f0-9]{32})', input_string)
    if match:
        return match.group(1)
    return None
```

**它只做两件事**：验证输入是 MD5（32hex）或从 `/md5/{md5}` URL 中提取。**不做任何针对书名/ISBN 的匹配**。

### 下载链接解析逻辑

`src/stacks/downloader/html.py` → `get_download_links()` → `_get_download_links_single_domain()`:

1. GET `https://{domain}/md5/{md5}`
2. BeautifulSoup 解析 HTML
3. 查找 `#md5-panel-downloads` 面板
4. 提取两类下载链接：
   - **slow_download 链接**：`<li class="list-disc"><a href="/slow_download/">`
     - 只接受 **no waitlist** 的服务器
     - 跳过带 "slightly faster but with waitlist" 描述的服务器
     - 跳过 fast_download 链接
   - **外部镜像链接**：`<ul class="js-show-external">` 内的 `<a>`
     - 跳过 `.onion` URL
5. 同时从页面提取书名（用于命名文件）

`src/stacks/downloader/html.py` → `parse_download_link_from_html()`:
1. 先尝试 Z-Library 特定解析器
2. 通用解析：找包含 MD5 前缀（前12字符）的 `<a href>`
3. 跳过非文件域名（jdownloader.org, telegram, social media 等）
4. 跳过 slow_download 页面（要找的是最终文件 URL，不是另一个 slow_download 页面）
5. 兜底：找可点击的 span/button 中的 URL

### 下载优先级

`src/stacks/downloader/orchestrator.py` → `orchestrate_download()`:

```
1. Fast Download (AA 会员 API) → 如果有会员 key 且启用
2. Slow Download (no waitlist 服务器) → 通过 FlareSolverr
3. 外部镜像 (libgen, zlib等) → 遍历所有链接
```

### 下载后校验

`src/stacks/downloader/direct.py` 中实现了：
- **断点续传**：基于 Range header + `.part` 临时文件
- **MD5 校验**：下载完成后计算文件 MD5，与预期 MD5 比对
- 不匹配时保留文件并添加 `_MISMATCH` 后缀用于调试

---

## 与本书下载器的对比

| 维度 | Stacks | 我们的项目 |
|------|--------|-----------|
| **输入** | MD5（用户从 AA 浏览获取） | SS code / ISBN / 书名（从数据库/搜索获取） |
| **搜索能力** | ❌ 无 — 依赖用户手动在 AA 上找 | ✅ 自动搜索 AA + ZL + LibGen |
| **MD5 匹配** | ❌ 不匹配 — 信任用户提供的 MD5 | ✅ 标题+ISBN 相关性校验 |
| **搜索引擎** | 无（只下载） | AA 全文搜索（SS/ISBN/书名 → MD5 列表） |
| **反爬** | FlareSolverr（内置） | FlareSolverr + cookie 提取 |
| **HTML 解析** | BeautifulSoup ✅ 稳健 | 纯 Regex ❌ 脆弱 |
| **MD5 校验** | ✅ 下载后计算校验 | ❌ 未实现 |
| **断点续传** | ✅ 有 | ❌ 无 |
| **下载源** | AA slow_download + 外部镜像 | AA(stacks/直连) → ZL → LibGen |
| **用户确认** | 通过 Tampermonkey 按钮隐含确认 | 需要前端弹窗确认 ZL 额度消耗 |
| **文件命名** | 从 AA 页面提取书名 | MD5.xxx |

---

## 关键差异分析

### 1. Stacks 不做匹配的原因

Stacks 不需要做匹配，因为它的 Tampermonkey 脚本利用**用户已经在 AA 上找到了想要的书**这个事实。用户在浏览器中搜索 AA → 看到搜索结果的标题 → 点击 Stacks 按钮 → Stacks 只提取 URL 中的 MD5。

**这意味著：Stacks 把"找到书"这个任务留给了人。**

### 2. 我们的项目需要做匹配的原因

我们的项目是**全自动管道**。Step 1 从本地数据库获取 SS code / ISBN / 书名 → Step 2 需要自动找到并下载。我们必须**自动在 AA 上搜索**，然后从搜索结果中找到正确的 MD5。这比 Stacks 难得多，因为：
- AA 搜索页可能返回多个结果
- AA 搜索结果的 HTML 结构可能变化
- Cloudflare 反爬可能影响搜索结果获取

### 3. Stacks 值得借鉴的点

| 借鉴点 | 说明 |
|--------|------|
| **BeautifulSoup 解析** | 比纯 regex 稳定，尤其对 AA 这种频繁改 HTML 的网站 |
| **MD5 校验** | 下载后计算 MD5 比对，确保文件完整 |
| **slow_download 分类** | 区分 no-waitlist 和 waitlist 服务器，优先 no-waitlist |
| **外部镜像** | 从 AA MD5 页面提取 libgen/zlib 等镜像链接，增加成功概率 |
| **域名轮询** | `try_domains_until_success` 自动尝试 `.gd`/`.se`/`.org` 等 |
| **断点续传** | 大文件下载中断后可续传 |

### 4. 当前匹配策略的根因问题

目前 `_calc_title_relevance()` 的工作方式是：
1. 从搜索结果页解析每个 MD5 区块 → 提取其中的标题文本
2. 与 Step 1 的书名做 CJK 字符重叠率计算

**问题**：AA 搜索结果的标题提取依赖 regex 上下文窗口（`<h\d>([^<]+)</h\d>`），如果 AA 搜索结果页的 HTML 结构变化，提取会失败。

**更好的方案（借鉴 Stacks）**：
1. 搜索 AA 拿到结果页
2. 对每个搜索结果 MD5，用 BeautifulSoup 解析 `/md5/{md5}` 详情页的标题（stacks 做法）
3. 使用 stacks 的 `extract_from_title()` 逻辑（查找特定 class 的 div）
4. 匹配通过后再下载

这就把"匹配"从**搜索页级**提升到了**详情页级**，更准确也更稳健。

---

## 结论

| 结论 | 内容 |
|------|------|
| **Stacks 不做搜索匹配** | 它假设 MD5 已经由用户找到，只负责下载 |
| **我们的匹配逻辑本身正确** | 但依赖 regex 解析 AA 搜索结果 HTML，脆弱 |
| **最佳方案** | 搜索时用 regex 找到所有 MD5 → BeautifulSoup 解析每个 MD5 的详情页获取标题/ISBN → 与元数据匹配 |
| **下载后校验** | 需要实现 MD5 checksum 验证 |
| **慢速下载优化** | 需要解析 AA 的 slow_download 类型（no waitlist vs waitlist）并优先 no-waitlist |
